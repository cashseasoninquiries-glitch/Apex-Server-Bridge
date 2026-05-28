import os
import redis
import psycopg2
import json
import time
import logging

logging.basicConfig(level=logging.INFO, format='%(asctime)s [%(levelname)s] %(message)s')

# INTERNAL DOCKER NETWORK COORDINATES
redis_client = redis.Redis(host='apex_redis_queue', port=6379, db=0)

# AUTOMATIC CORE RESOLUTION
DB_USER = os.getenv("POSTGRES_USER", "apex_admin")
DB_PASS = os.getenv("POSTGRES_PASSWORD", "apex_secure_password")
DB_NAME = os.getenv("POSTGRES_DB", "apex_vault")

DB_DSN = f"dbname={DB_NAME} user={DB_USER} password={DB_PASS} host=apex_postgres_vault"

QUEUE_NAME = "apex_signal_queue"
BUFFER_NAME = "apex_processing_buffer"

def process_trade_pipeline():
    logging.info("Apex High-Velocity Execution Worker: ONLINE.")
    
    while True:
        try:
            # 1. ATOMIC DUAL-BUFFER TRANSFER
            raw_payload = redis_client.brpoplpush(src=QUEUE_NAME, dst=BUFFER_NAME, timeout=0)
            
            if not raw_payload:
                continue
                
            logging.info(f"Signal Locked into Processing Buffer. Payload received.")
            signal_data = json.loads(raw_payload.decode('utf-8'))
            
            # Extract routing variables
            strategy_id = signal_data.get("strategy_id")
            symbol = signal_data.get("ticker")
            signal_value = 1 if signal_data.get("action") == "LONG" else -1
            
            # 2. EXECUTE TRANSACTION AND RECORD TO THE VAULT
            with psycopg2.connect(DB_DSN) as conn:
                with conn.cursor() as cur:
                    # EXPLICIT TIMESTAMP INJECTION ADDED HERE
                    query = """
                    INSERT INTO strategy_signals (timestamp, strategy_id, symbol, signal_value, metadata)
                    VALUES (NOW(), %s, %s, %s, %s)
                    ON CONFLICT (timestamp, strategy_id, symbol) DO NOTHING;
                    """
                    cur.execute(query, (strategy_id, symbol, signal_value, json.dumps(signal_data)))
                conn.commit()
            
            # 3. ACKNOWLEDGMENT LAYER
            redis_client.lrem(name=BUFFER_NAME, count=1, value=raw_payload)
            logging.info(f"Transaction Complete. Buffer cleared for Strategy: {strategy_id} | Symbol: {symbol}")
            
        except redis.ConnectionError:
            logging.error("Asymmetric network partition detected on Redis layer. Backing off 5s...")
            time.sleep(5)
        except psycopg2.OperationalError as db_err:
            logging.error(f"PostgreSQL Vault boundary lost: {str(db_err)}. Re-establishing connection context...")
            time.sleep(5)
        except Exception as e:
            logging.critical(f"Unexpected operational anomaly inside engine execution loop: {str(e)}")
            time.sleep(1)

if __name__ == "__main__":
    process_trade_pipeline()
