import os
import redis
import json
import time
import logging
import psycopg2
from datetime import datetime, timezone

logging.basicConfig(level=logging.INFO, format='%(asctime)s [%(levelname)s] RECORDER: %(message)s')

# --- REDIS ---
REDIS_PASSWORD = os.getenv("REDIS_PASSWORD")
redis_client = redis.Redis(host='apex_redis_queue', port=6379, db=0, password=REDIS_PASSWORD)
RECORD_QUEUE = "apex_record_queue"

# --- POSTGRES ---
DB_DSN = "dbname={} user={} password={} host=apex_postgres_vault".format(
    os.getenv("POSTGRES_DB", "apex_vault"),
    os.getenv("POSTGRES_USER", "apex_admin"),
    os.getenv("POSTGRES_PASSWORD")
)

def get_conn():
    return psycopg2.connect(DB_DSN)

def upsert_strategy(cur, strategy_id):
    cur.execute("""
        INSERT INTO strategies (name, type, lifecycle_state, confidence_stars)
        VALUES (%s, 'automated', 'yellow', 0)
        ON CONFLICT (name) DO NOTHING
        RETURNING id
    """, (strategy_id,))
    row = cur.fetchone()
    if row:
        return row[0]
    cur.execute("SELECT id FROM strategies WHERE name = %s", (strategy_id,))
    return cur.fetchone()[0]

def insert_event(cur, strategy_uuid, record):
    cur.execute("""
        INSERT INTO events (strategy_id, ticker, action, order_id, raw_payload, created_at)
        VALUES (%s, %s, %s, %s, %s, %s)
        RETURNING id
    """, (
        strategy_uuid,
        record.get("ticker"),
        record.get("action", "").upper(),
        record.get("order_id"),
        json.dumps(record),
        datetime.now(timezone.utc)
    ))
    return cur.fetchone()[0]

def find_open_trade(cur, strategy_uuid, ticker):
    cur.execute("""
        SELECT id, entry_event_id, entry_price
        FROM trades
        WHERE strategy_id = %s AND ticker = %s AND status = 'open'
        ORDER BY created_at DESC
        LIMIT 1
    """, (strategy_uuid, ticker))
    return cur.fetchone()

def open_trade(cur, strategy_uuid, ticker, event_id, record):
    price = float(record.get("price") or record.get("qty") or 0)
    cur.execute("""
        INSERT INTO trades (strategy_id, ticker, entry_event_id, entry_price, qty, status, created_at)
        VALUES (%s, %s, %s, %s, %s, 'open', %s)
    """, (
        strategy_uuid, ticker, event_id, price,
        int(record.get("qty") or record.get("quantity") or 1),
        datetime.now(timezone.utc)
    ))

def close_trade(cur, trade_id, entry_price, exit_event_id, record):
    exit_price = float(record.get("price") or 0)
    qty = float(record.get("qty") or record.get("quantity") or 1)
    pnl = (exit_price - entry_price) * qty if exit_price and entry_price else None
    cur.execute("""
        UPDATE trades
        SET exit_event_id = %s, exit_price = %s, pnl = %s, status = 'closed', closed_at = %s
        WHERE id = %s
    """, (exit_event_id, exit_price, pnl, datetime.now(timezone.utc), trade_id))

def write_dead_letter(raw, error):
    try:
        with get_conn() as conn:
            with conn.cursor() as cur:
                cur.execute("""
                    INSERT INTO dead_letters (raw_payload, error, created_at)
                    VALUES (%s, %s, %s)
                """, (raw, str(error), datetime.now(timezone.utc)))
            conn.commit()
    except Exception as e:
        logging.error(f"Dead letter write failed: {e}")

def process(raw):
    record = json.loads(raw.decode('utf-8'))
    strategy_id = record.get("strategy_id", "unknown")
    ticker = record.get("ticker")
    action = record.get("action", "").upper()

    with get_conn() as conn:
        with conn.cursor() as cur:
            strategy_uuid = upsert_strategy(cur, strategy_id)
            event_id = insert_event(cur, strategy_uuid, record)

            if action == "LONG":
                open_trade(cur, strategy_uuid, ticker, event_id, record)
                logging.info(f"Trade opened: {strategy_id} | {ticker}")
            elif action in ("SELL", "SHORT"):
                open_t = find_open_trade(cur, strategy_uuid, ticker)
                if open_t:
                    close_trade(cur, open_t[0], open_t[2], event_id, record)
                    logging.info(f"Trade closed: {strategy_id} | {ticker} | PnL recorded")
                else:
                    logging.warning(f"No open trade found to close: {strategy_id} | {ticker}")
        conn.commit()

def run():
    logging.info("Apex Recorder: ONLINE. Listening on apex_record_queue...")
    while True:
        try:
            result = redis_client.brpop(RECORD_QUEUE, timeout=5)
            if result is None:
                continue
            _, raw = result
            try:
                process(raw)
            except Exception as e:
                logging.error(f"Processing error: {e}")
                write_dead_letter(raw, e)
        except redis.ConnectionError:
            logging.error("Redis connection lost. Retrying in 5s...")
            time.sleep(5)
        except Exception as e:
            logging.critical(f"Unexpected error: {e}")
            time.sleep(1)

if __name__ == "__main__":
    run()
