"""
Apex Strategy Registry
Handles registration, fingerprinting, lifecycle management, and confidence scoring.
SHA-256 fingerprinting catches exact duplicate strategies at registration time.
"""

import os
import json
import hashlib
import psycopg2
import logging

logging.basicConfig(level=logging.INFO, format='%(asctime)s [%(levelname)s] REGISTRY: %(message)s')

# Fields that define a strategy's identity (excluded: name, qty, passphrase, timestamps)
FINGERPRINT_FIELDS = [
    'ticker', 'timeframe', 'strategy_type', 'indicator_type',
    'entry_condition', 'exit_condition', 'fast_period', 'slow_period', 'direction'
]


def get_db_conn():
    return psycopg2.connect(
        host=os.getenv('POSTGRES_HOST', 'apex_postgres_vault'),
        dbname=os.getenv('POSTGRES_DB', 'apex_vault'),
        user=os.getenv('POSTGRES_USER', 'apex_admin'),
        password=os.getenv('POSTGRES_PASSWORD')
    )


def build_fingerprint(params: dict) -> str:
    """
    SHA-256 hash of the strategy's core parameters.
    Canonical JSON ensures consistent ordering regardless of input order.
    """
    fingerprint_fields = {k: params.get(k) for k in FINGERPRINT_FIELDS}
    canonical = json.dumps(fingerprint_fields, sort_keys=True)
    return hashlib.sha256(canonical.encode()).hexdigest()


def register_strategy(name, strategy_type, timeframe, asset_class, params,
                      is_paper=True, notes=None):
    """
    Register a new strategy. Rejects exact duplicates by param_hash.
    Returns a dict with status: 'registered' | 'rejected' | 'error'
    """
    param_hash = build_fingerprint(params)

    try:
        with get_db_conn() as conn:
            with conn.cursor() as cur:
                # Check for exact parameter duplicate
                cur.execute(
                    "SELECT name FROM strategies WHERE param_hash = %s",
                    (param_hash,)
                )
                existing = cur.fetchone()
                if existing:
                    logging.warning(
                        f"Duplicate rejected — same params as '{existing[0]}' | hash: {param_hash[:8]}..."
                    )
                    return {
                        "status": "rejected",
                        "reason": "exact_duplicate",
                        "matching_strategy": existing[0],
                        "param_hash": param_hash
                    }

                cur.execute("""
                    INSERT INTO strategies
                        (name, strategy_type, timeframe, asset_class, parameters,
                         is_paper, notes, param_hash, lifecycle_state, confidence_stars)
                    VALUES (%s, %s, %s, %s, %s, %s, %s, %s, 'yellow', 0)
                    RETURNING id
                """, (name, strategy_type, timeframe, asset_class,
                      json.dumps(params), is_paper, notes, param_hash))

                strategy_id = str(cur.fetchone()[0])
                logging.info(f"Registered: '{name}' | ID: {strategy_id} | Hash: {param_hash[:8]}...")
                return {
                    "status": "registered",
                    "strategy_id": strategy_id,
                    "param_hash": param_hash
                }

    except Exception as e:
        logging.error(f"Registration error: {e}")
        return {"status": "error", "error": str(e)}


def update_lifecycle(strategy_id, new_state, failure_reason=None):
    """
    Manually set a strategy's lifecycle state.
    Valid states: yellow, green, red, grey
    Grey sets archived_at timestamp (data preserved forever for ML training).
    """
    valid_states = ['yellow', 'green', 'red', 'grey']
    if new_state not in valid_states:
        return {"status": "error", "error": f"Invalid state '{new_state}'. Must be: {valid_states}"}

    try:
        with get_db_conn() as conn:
            with conn.cursor() as cur:
                if new_state == 'grey':
                    cur.execute("""
                        UPDATE strategies
                        SET lifecycle_state = %s, archived_at = NOW()
                        WHERE id = %s
                    """, (new_state, strategy_id))
                else:
                    cur.execute("""
                        UPDATE strategies SET lifecycle_state = %s WHERE id = %s
                    """, (new_state, strategy_id))

                logging.info(f"Lifecycle update: {strategy_id} → {new_state}")
                return {"status": "updated", "new_state": new_state}

    except Exception as e:
        logging.error(f"Lifecycle update error: {e}")
        return {"status": "error", "error": str(e)}


def update_confidence(strategy_id, trade_count):
    """
    Set confidence stars based on trade count.
    ★ = 30 trades, ★★ = 100 trades, ★★★ = 250 trades
    """
    if trade_count >= 250:
        stars = 3
    elif trade_count >= 100:
        stars = 2
    elif trade_count >= 30:
        stars = 1
    else:
        stars = 0

    try:
        with get_db_conn() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    "UPDATE strategies SET confidence_stars = %s WHERE id = %s",
                    (stars, strategy_id)
                )
                return {"status": "updated", "confidence_stars": stars}
    except Exception as e:
        logging.error(f"Confidence update error: {e}")
        return {"status": "error", "error": str(e)}


if __name__ == "__main__":
    # Smoke test — register the same strategy twice to confirm duplicate detection
    params = {
        "ticker": "AAPL",
        "timeframe": "5m",
        "strategy_type": "crossover",
        "indicator_type": "SMA",
        "entry_condition": "fast_above_slow",
        "exit_condition": "fast_below_slow",
        "fast_period": 9,
        "slow_period": 21,
        "direction": "LONG"
    }

    print("Attempt 1:")
    print(register_strategy("SMA_9_21_AAPL", "crossover", "5m", "equity", params))

    print("\nAttempt 2 (same params, different name — should be rejected):")
    print(register_strategy("SMA_9_21_AAPL_V2", "crossover", "5m", "equity", params))
