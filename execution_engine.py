import os
import redis
import json
import time
import logging
import psycopg2
from alpaca.trading.client import TradingClient
from alpaca.trading.requests import MarketOrderRequest
from alpaca.trading.enums import OrderSide, TimeInForce

logging.basicConfig(level=logging.INFO, format='%(asctime)s [%(levelname)s] EXECUTION: %(message)s')

# --- REDIS ---
REDIS_PASSWORD = os.getenv('REDIS_PASSWORD')
redis_client = redis.Redis(
    host=os.getenv('REDIS_HOST', 'apex_redis_queue'),
    port=6379,
    db=0,
    password=REDIS_PASSWORD
)
QUEUE_NAME = "apex_signal_queue"
BUFFER_NAME = "apex_execution_buffer"
RECORD_QUEUE = "apex_record_queue"

# --- ALPACA ---
ALPACA_API_KEY = os.getenv("ALPACA_API_KEY")
ALPACA_SECRET_KEY = os.getenv("ALPACA_SECRET_KEY")
PAPER_TRADING = os.getenv("ALPACA_PAPER_TRADING", "True").lower() == "true"

trading_client = TradingClient(ALPACA_API_KEY, ALPACA_SECRET_KEY, paper=PAPER_TRADING)

DEFAULT_QTY = int(os.getenv("DEFAULT_ORDER_QTY", "1"))


def get_db_conn():
    return psycopg2.connect(
        host=os.getenv('POSTGRES_HOST', 'apex_postgres_vault'),
        dbname=os.getenv('POSTGRES_DB', 'apex_vault'),
        user=os.getenv('POSTGRES_USER', 'apex_admin'),
        password=os.getenv('POSTGRES_PASSWORD')
    )


def write_dead_letter(raw_payload, error, source="execution_engine"):
    """Capture failed/invalid signals to dead_letters table for manual review."""
    try:
        with get_db_conn() as conn:
            with conn.cursor() as cur:
                payload_str = (
                    json.dumps(raw_payload)
                    if isinstance(raw_payload, dict)
                    else str(raw_payload)
                )
                cur.execute(
                    "INSERT INTO dead_letters (source, raw_payload, error_message) VALUES (%s, %s, %s)",
                    (source, payload_str, str(error))
                )
    except Exception as e:
        logging.error(f"Failed to write dead letter: {e}")


def get_strategy_uuid(cur, strategy_name):
    cur.execute("SELECT id FROM strategies WHERE name = %s", (strategy_name,))
    row = cur.fetchone()
    return str(row[0]) if row else None


def has_open_position(cur, strategy_uuid, ticker):
    cur.execute(
        "SELECT COUNT(*) FROM trades WHERE strategy_id = %s AND ticker = %s AND status = 'open'",
        (strategy_uuid, ticker)
    )
    return cur.fetchone()[0] > 0


def check_position(strategy_name, ticker, action):
    """
    Gate: prevent double-buying and selling what you don't own.
    Returns (allowed: bool, reason: str)
    """
    try:
        with get_db_conn() as conn:
            with conn.cursor() as cur:
                strategy_uuid = get_strategy_uuid(cur, strategy_name)

                if not strategy_uuid:
                    # Unknown strategy — allow through, recorder will auto-register it
                    return True, "new strategy"

                open_pos = has_open_position(cur, strategy_uuid, ticker)

                if action == "LONG" and open_pos:
                    return False, f"Blocked: {strategy_name} already has open LONG on {ticker}"
                if action in ("SELL", "SHORT") and not open_pos:
                    return False, f"Blocked: {strategy_name} has no open position on {ticker} to close"

                return True, "ok"

    except Exception as e:
        logging.warning(f"Position check error (allowing through): {e}")
        return True, "position check error — allowing"


def place_order(symbol, side):
    order_request = MarketOrderRequest(
        symbol=symbol,
        qty=DEFAULT_QTY,
        side=side,
        time_in_force=TimeInForce.DAY
    )
    order = trading_client.submit_order(order_request)
    logging.info(f"Order placed: {side.value.upper()} {DEFAULT_QTY}x {symbol} | ID: {order.id}")
    return order


def run_execution_engine():
    logging.info("Apex Execution Engine: ONLINE")
    logging.info(f"Mode: {'PAPER' if PAPER_TRADING else 'LIVE'} | Default Qty: {DEFAULT_QTY}")

    while True:
        raw_payload = None
        try:
            # Atomic move: signal queue → processing buffer
            raw_payload = redis_client.brpoplpush(src=QUEUE_NAME, dst=BUFFER_NAME, timeout=0)
            if not raw_payload:
                continue

            signal = json.loads(raw_payload.decode('utf-8'))
            strategy_name = signal.get("strategy_id", signal.get("strategy_name", "unknown"))
            ticker = signal.get("ticker")
            action = signal.get("action", "").upper()

            if not ticker or not action:
                logging.warning(f"Malformed signal — missing ticker or action: {signal}")
                write_dead_letter(signal, "Missing ticker or action")
                redis_client.lrem(BUFFER_NAME, 1, raw_payload)
                continue

            logging.info(f"Signal: {action} {ticker} from {strategy_name}")

            # Position gate
            allowed, reason = check_position(strategy_name, ticker, action)
            if not allowed:
                logging.warning(f"Position gate blocked: {reason}")
                redis_client.lrem(BUFFER_NAME, 1, raw_payload)
                continue

            # Route to Alpaca
            if action == "LONG":
                order = place_order(ticker, OrderSide.BUY)
            elif action in ("SELL", "SHORT"):
                order = place_order(ticker, OrderSide.SELL)
            else:
                logging.warning(f"Unknown action '{action}' — writing to dead letters")
                write_dead_letter(signal, f"Unknown action: {action}")
                redis_client.lrem(BUFFER_NAME, 1, raw_payload)
                continue

            # Acknowledge — remove from buffer after successful execution
            redis_client.lrem(BUFFER_NAME, 1, raw_payload)

            # Hand off to recorder
            record = {**signal, "order_id": str(order.id), "status": "executed", "is_paper": PAPER_TRADING}
            redis_client.lpush(RECORD_QUEUE, json.dumps(record))
            logging.info(f"Executed and queued for recording: {strategy_name} | {action} {ticker}")

        except redis.ConnectionError:
            logging.error("Redis connection lost. Retrying in 5s...")
            time.sleep(5)

        except Exception as e:
            logging.critical(f"Execution error: {str(e)}")
            write_dead_letter(raw_payload, str(e))
            if raw_payload:
                redis_client.lrem(BUFFER_NAME, 1, raw_payload)
            time.sleep(1)


if __name__ == "__main__":
    run_execution_engine()
