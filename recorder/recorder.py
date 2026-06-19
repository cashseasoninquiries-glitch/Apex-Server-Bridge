"""
Apex Recorder
Listens on apex_record_queue. For every executed trade signal:
  - Upserts the strategy into the strategies table (creates if new)
  - Logs the event
  - Opens or closes a trade record
  - Updates confidence badge
  - Triggers performance calculator on trade close
  - Routes errors to dead_letters
"""

import os
import redis
import json
import time
import logging
import psycopg2

logging.basicConfig(level=logging.INFO, format='%(asctime)s [%(levelname)s] RECORDER: %(message)s')

REDIS_PASSWORD = os.getenv('REDIS_PASSWORD')
redis_client = redis.Redis(
    host=os.getenv('REDIS_HOST', 'apex_redis_queue'),
    port=6379,
    db=0,
    password=REDIS_PASSWORD
)
RECORD_QUEUE = "apex_record_queue"
PERF_QUEUE = "apex_perf_queue"


def get_db_conn():
    return psycopg2.connect(
        host=os.getenv('POSTGRES_HOST', 'apex_postgres_vault'),
        dbname=os.getenv('POSTGRES_DB', 'apex_vault'),
        user=os.getenv('POSTGRES_USER', 'apex_admin'),
        password=os.getenv('POSTGRES_PASSWORD')
    )


def write_dead_letter(raw_payload, error, source="recorder"):
    try:
        with get_db_conn() as conn:
            with conn.cursor() as cur:
                payload_str = (
                    json.dumps(raw_payload)
                    if isinstance(raw_payload, (dict, list))
                    else str(raw_payload)
                )
                cur.execute(
                    "INSERT INTO dead_letters (source, raw_payload, error_message) VALUES (%s, %s, %s)",
                    (source, payload_str, str(error))
                )
    except Exception as e:
        logging.error(f"Dead letter write failed: {e}")


def upsert_strategy(cur, strategy_name):
    """Get or create a strategy record. Returns strategy_id UUID string."""
    cur.execute("SELECT id FROM strategies WHERE name = %s", (strategy_name,))
    row = cur.fetchone()
    if row:
        return str(row[0])

    # Auto-register — strategy will start in yellow, no params yet
    cur.execute(
        """INSERT INTO strategies (name, lifecycle_state, confidence_stars)
           VALUES (%s, 'yellow', 0) RETURNING id""",
        (strategy_name,)
    )
    new_id = str(cur.fetchone()[0])
    logging.info(f"Auto-registered new strategy: '{strategy_name}' | {new_id}")
    return new_id


def insert_event(cur, strategy_id, signal):
    """Log every signal as an event. Returns event_id UUID string."""
    # Never log the passphrase field
    safe_payload = {k: v for k, v in signal.items() if k != 'passphrase'}

    # order_id and fill_price have no dedicated columns on `events` — they're
    # preserved inside raw_payload (and order_id is also written to
    # trades.alpaca_order_id when a trade is opened).
    cur.execute("""
        INSERT INTO events
            (strategy_id, ticker, action, signal_price, quantity, source, market_regime, raw_payload)
        VALUES (%s, %s, %s, %s, %s, %s, %s, %s)
        RETURNING id
    """, (
        strategy_id,
        signal.get('ticker'),
        signal.get('action'),
        signal.get('signal_price'),
        signal.get('qty', 1),
        signal.get('source', 'execution_engine'),
        signal.get('regime'),
        json.dumps(safe_payload)
    ))
    return str(cur.fetchone()[0])


def open_trade(cur, strategy_id, signal, event_id):
    """Create an open trade record for LONG signals."""
    cur.execute("""
        INSERT INTO trades
            (strategy_id, ticker, direction, entry_event_id, entry_price, quantity,
             status, entry_at, alpaca_order_id, entry_regime, is_paper)
        VALUES (%s, %s, 'LONG', %s, %s, %s, 'open', NOW(), %s, %s, %s)
    """, (
        strategy_id,
        signal.get('ticker'),
        event_id,
        signal.get('fill_price') or signal.get('signal_price'),
        signal.get('qty', 1),
        signal.get('order_id'),
        signal.get('regime'),
        signal.get('is_paper', True)
    ))
    logging.info(f"Trade opened: {signal.get('ticker')} for {strategy_id}")


def close_trade(cur, strategy_id, signal, event_id):
    """
    Close the most recent open trade for this strategy+ticker.
    Calculates PnL, PnL%, and slippage (signal price vs actual fill price).
    Returns strategy_id if successful, None otherwise.
    """
    cur.execute("""
        SELECT id, entry_price, quantity
        FROM trades
        WHERE strategy_id = %s AND ticker = %s AND status = 'open'
        ORDER BY entry_at DESC
        LIMIT 1
    """, (strategy_id, signal.get('ticker')))

    trade = cur.fetchone()
    if not trade:
        logging.warning(
            f"No open trade to close: {strategy_id} on {signal.get('ticker')}"
        )
        return None

    trade_id, entry_price, qty = trade
    exit_price = float(signal.get('fill_price') or signal.get('signal_price') or 0)
    entry_price = float(entry_price)
    qty = float(qty)

    pnl = (exit_price - entry_price) * qty
    pnl_pct = ((exit_price - entry_price) / entry_price * 100) if entry_price else 0

    # Slippage = distance between where signal said to exit vs where Alpaca actually filled
    # (no dedicated column on `trades` for this — logged only, also retained in events.raw_payload)
    signal_price = float(signal.get('signal_price') or exit_price)
    slippage = abs(exit_price - signal_price)

    cur.execute("""
        UPDATE trades SET
            exit_event_id = %s,
            exit_price = %s,
            pnl = %s,
            pnl_pct = %s,
            status = 'closed',
            exit_at = NOW(),
            exit_regime = %s,
            duration_mins = EXTRACT(EPOCH FROM (NOW() - entry_at)) / 60
        WHERE id = %s
    """, (event_id, exit_price, pnl, pnl_pct, signal.get('regime'), trade_id))

    logging.info(
        f"Trade closed: {signal.get('ticker')} | "
        f"PnL: ${pnl:.2f} ({pnl_pct:.2f}%) | Slippage: ${slippage:.4f}"
    )
    return strategy_id


def update_confidence_badge(cur, strategy_id):
    """Recalculate and update confidence stars after every trade."""
    cur.execute(
        "SELECT COUNT(*) FROM trades WHERE strategy_id = %s",
        (strategy_id,)
    )
    count = cur.fetchone()[0]

    if count >= 250:
        stars = 3
    elif count >= 100:
        stars = 2
    elif count >= 30:
        stars = 1
    else:
        stars = 0

    cur.execute(
        "UPDATE strategies SET confidence_stars = %s WHERE id = %s",
        (stars, strategy_id)
    )


def run_recorder():
    logging.info("Apex Recorder: ONLINE. Listening on apex_record_queue...")

    while True:
        raw_payload = None
        try:
            result = redis_client.brpop(RECORD_QUEUE, timeout=0)
            if not result:
                continue

            _, raw_payload = result
            signal = json.loads(raw_payload.decode('utf-8'))

            strategy_name = signal.get('strategy_id', signal.get('strategy_name', 'unknown'))
            action = signal.get('action', '').upper()

            with get_db_conn() as conn:
                with conn.cursor() as cur:
                    strategy_id = upsert_strategy(cur, strategy_name)
                    event_id = insert_event(cur, strategy_id, signal)

                    if action == 'LONG':
                        open_trade(cur, strategy_id, signal, event_id)

                    elif action in ('SELL', 'SHORT'):
                        closed_id = close_trade(cur, strategy_id, signal, event_id)
                        if closed_id:
                            # Trigger performance calculator
                            redis_client.lpush(PERF_QUEUE, closed_id)

                    update_confidence_badge(cur, strategy_id)

            logging.info(f"Recorded: {action} {signal.get('ticker')} | {strategy_name}")

        except redis.ConnectionError:
            logging.error("Redis connection lost. Retrying in 5s...")
            time.sleep(5)

        except Exception as e:
            logging.error(f"Recorder error: {e}")
            write_dead_letter(raw_payload, str(e))
            time.sleep(1)


if __name__ == "__main__":
    run_recorder()
