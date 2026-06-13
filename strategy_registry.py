import os
import json
import hashlib
import logging
import psycopg2
from datetime import datetime, timezone

logging.basicConfig(level=logging.INFO, format='%(asctime)s [%(levelname)s] REGISTRY: %(message)s')

DB_DSN = "dbname={} user={} password={} host=apex_postgres_vault".format(
    os.getenv("POSTGRES_DB", "apex_vault"),
    os.getenv("POSTGRES_USER", "apex_admin"),
    os.getenv("POSTGRES_PASSWORD")
)

def get_conn():
    return psycopg2.connect(DB_DSN)

def build_fingerprint(params: dict) -> str:
    """Generate a SHA-256 hash from core strategy parameters."""
    fingerprint_fields = {
        "ticker": params.get("ticker"),
        "timeframe": params.get("timeframe"),
        "strategy_type": params.get("strategy_type"),
        "indicator_type": params.get("indicator_type"),
        "entry_condition": params.get("entry_condition"),
        "exit_condition": params.get("exit_condition"),
        "fast_period": params.get("fast_period"),
        "slow_period": params.get("slow_period"),
        "direction": params.get("direction"),
    }
    # Sort keys for consistency, serialize, hash
    canonical = json.dumps(fingerprint_fields, sort_keys=True)
    return hashlib.sha256(canonical.encode()).hexdigest()

def register_strategy(name: str, strategy_type: str, timeframe: str,
                      asset_class: str, params: dict, is_paper: bool = True,
                      notes: str = None) -> dict:
    """
    Register a new strategy. Returns result dict with status and strategy id.
    Rejects duplicates based on param_hash.
    """
    param_hash = build_fingerprint(params)

    with get_conn() as conn:
        with conn.cursor() as cur:
            # Check for duplicate fingerprint
            cur.execute("SELECT id, name FROM strategies WHERE param_hash = %s", (param_hash,))
            existing = cur.fetchone()
            if existing:
                logging.warning(f"Duplicate strategy detected. Matches existing: '{existing[1]}' (id: {existing[0]})")
                return {
                    "status": "rejected",
                    "reason": "duplicate",
                    "matches": str(existing[0]),
                    "matches_name": existing[1]
                }

            # Register new strategy
            cur.execute("""
                INSERT INTO strategies
                    (name, strategy_type, parameters, timeframe, asset_class,
                     is_paper, notes, param_hash, lifecycle_state, confidence_stars)
                VALUES (%s, %s, %s, %s, %s, %s, %s, %s, 'yellow', 0)
                RETURNING id
            """, (
                name, strategy_type, json.dumps(params),
                timeframe, asset_class, is_paper, notes, param_hash
            ))
            new_id = cur.fetchone()[0]
        conn.commit()

    logging.info(f"Strategy registered: '{name}' | ID: {new_id} | Hash: {param_hash[:12]}...")
    return {"status": "registered", "id": str(new_id), "param_hash": param_hash}

def get_strategy(strategy_id: str = None, name: str = None) -> dict:
    """Fetch a strategy by ID or name."""
    with get_conn() as conn:
        with conn.cursor() as cur:
            if strategy_id:
                cur.execute("SELECT * FROM strategies WHERE id = %s", (strategy_id,))
            elif name:
                cur.execute("SELECT * FROM strategies WHERE name = %s", (name,))
            else:
                return None
            row = cur.fetchone()
            if not row:
                return None
            cols = [desc[0] for desc in cur.description]
            return dict(zip(cols, row))

def update_lifecycle(strategy_id: str, new_state: str, failure_reason: str = None):
    """
    Update a strategy's lifecycle state.
    Valid states: yellow, green, red, grey
    """
    valid_states = ("yellow", "green", "red", "grey")
    if new_state not in valid_states:
        raise ValueError(f"Invalid lifecycle state: {new_state}. Must be one of {valid_states}")

    archived_at = datetime.now(timezone.utc) if new_state == "grey" else None

    with get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute("""
                UPDATE strategies
                SET lifecycle_state = %s,
                    failure_reason = %s,
                    archived_at = %s
                WHERE id = %s
            """, (new_state, failure_reason, archived_at, strategy_id))
        conn.commit()

    logging.info(f"Strategy {strategy_id} lifecycle → {new_state.upper()}")

def update_confidence(strategy_id: str, trade_count: int):
    """Award confidence stars based on trade count."""
    if trade_count >= 250:
        stars = 3
    elif trade_count >= 100:
        stars = 2
    elif trade_count >= 30:
        stars = 1
    else:
        stars = 0

    with get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute(
                "UPDATE strategies SET confidence_stars = %s WHERE id = %s",
                (stars, strategy_id)
            )
        conn.commit()

    logging.info(f"Strategy {strategy_id} confidence → {'★' * stars if stars else 'unrated'}")

def list_strategies(lifecycle_state: str = None) -> list:
    """List all strategies, optionally filtered by lifecycle state."""
    with get_conn() as conn:
        with conn.cursor() as cur:
            if lifecycle_state:
                cur.execute(
                    "SELECT * FROM strategies WHERE lifecycle_state = %s ORDER BY created_at DESC",
                    (lifecycle_state,)
                )
            else:
                cur.execute("SELECT * FROM strategies ORDER BY created_at DESC")
            cols = [desc[0] for desc in cur.description]
            return [dict(zip(cols, row)) for row in cur.fetchall()]

if __name__ == "__main__":
    # Quick self-test — register strategy_mvp if not already present
    result = register_strategy(
        name="strategy_mvp_sma",
        strategy_type="crossover",
        timeframe="5min",
        asset_class="equity",
        params={
            "ticker": "AAPL",
            "timeframe": "5min",
            "strategy_type": "crossover",
            "indicator_type": "SMA",
            "entry_condition": "fast_crosses_above_slow",
            "exit_condition": "fast_crosses_below_slow",
            "fast_period": 9,
            "slow_period": 21,
            "direction": "long_short"
        },
        is_paper=True,
        notes="MVP proof-of-concept strategy"
    )
    print(result)
