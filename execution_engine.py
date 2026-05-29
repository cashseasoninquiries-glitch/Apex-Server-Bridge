import os
import redis
import json
import time
import logging
from alpaca.trading.client import TradingClient
from alpaca.trading.requests import MarketOrderRequest
from alpaca.trading.enums import OrderSide, TimeInForce

logging.basicConfig(level=logging.INFO, format='%(asctime)s [%(levelname)s] EXECUTION: %(message)s')

# --- REDIS CONNECTION ---
redis_client = redis.Redis(host='apex_redis_queue', port=6379, db=0)
QUEUE_NAME = "apex_signal_queue"
BUFFER_NAME = "apex_execution_buffer"
RECORD_QUEUE = "apex_record_queue"

# --- ALPACA CONNECTION ---
ALPACA_API_KEY = os.getenv("ALPACA_API_KEY")
ALPACA_SECRET_KEY = os.getenv("ALPACA_SECRET_KEY")
PAPER_TRADING = os.getenv("ALPACA_PAPER_TRADING", "True").lower() == "true"

trading_client = TradingClient(ALPACA_API_KEY, ALPACA_SECRET_KEY, paper=PAPER_TRADING)

# --- DEFAULT ORDER SIZE ---
DEFAULT_QTY = int(os.getenv("DEFAULT_ORDER_QTY", "1"))


def place_order(symbol, side):
    """Places a market order on Alpaca."""
    order_request = MarketOrderRequest(
        symbol=symbol,
        qty=DEFAULT_QTY,
        side=side,
        time_in_force=TimeInForce.DAY
    )
    order = trading_client.submit_order(order_request)
    logging.info(f"Order Placed: {side.value.upper()} {DEFAULT_QTY}x {symbol} | Order ID: {order.id}")
    return order


def run_execution_engine():
    logging.info("Apex Execution Engine: ONLINE. Listening for signals...")
    logging.info(f"Mode: {'PAPER' if PAPER_TRADING else 'LIVE'} | Default Qty: {DEFAULT_QTY}")

    while True:
        try:
            # Atomically move signal from queue to processing buffer
            raw_payload = redis_client.brpoplpush(src=QUEUE_NAME, dst=BUFFER_NAME, timeout=0)
            if not raw_payload:
                continue

            signal = json.loads(raw_payload.decode('utf-8'))
            strategy_id = signal.get("strategy_id", "unknown")
            ticker = signal.get("ticker")
            action = signal.get("action", "").upper()

            logging.info(f"Signal received: {action} {ticker} from {strategy_id}")

            # Route action to correct order side
            if action == "LONG":
                order = place_order(ticker, OrderSide.BUY)
            elif action == "SHORT" or action == "SELL":
                order = place_order(ticker, OrderSide.SELL)
            else:
                logging.warning(f"Unknown action '{action}' — signal ignored.")
                redis_client.lrem(BUFFER_NAME, 1, raw_payload)
                continue

            # Acknowledge — remove from buffer after successful order
            redis_client.lrem(BUFFER_NAME, 1, raw_payload)

            # Push completed trade record to Postgres recorder
            record = {**signal, "order_id": str(order.id), "status": "executed"}
            redis_client.lpush(RECORD_QUEUE, json.dumps(record))
            logging.info(f"Signal processed and buffer cleared: {strategy_id} | {action} {ticker}")

        except redis.ConnectionError:
            logging.error("Redis connection lost. Retrying in 5s...")
            time.sleep(5)

        except Exception as e:
            logging.critical(f"Execution error: {str(e)}")
            # Remove bad signal from buffer so it doesn't block the queue
            if raw_payload:
                redis_client.lrem(BUFFER_NAME, 1, raw_payload)
            time.sleep(1)


if __name__ == "__main__":
    run_execution_engine()
