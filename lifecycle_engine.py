"""
Apex Lifecycle Engine — Phase 2.3
Listens on apex_lifecycle_queue (strategy_id pushed by performance_calculator after each update).
Reads the latest performance metrics and applies promotion/demotion rules:

  Yellow → Green:  ≥30 trades AND Sharpe ≥ 0.5 AND win_rate ≥ 45% AND drawdown ≤ threshold
  Green  → Red:    Sharpe < 0.0 OR win_rate < 35% OR drawdown > threshold
  Red    → Green:  Recovery (same criteria as Yellow → Green)
  Red    → Grey:   consecutive_failures ≥ grey_fail_count (auto-culling)
  Grey:            Terminal — never re-evaluated

All thresholds are configurable per-strategy via the strategies.parameters JSONB field.
Default thresholds are used if not specified.
"""

import os
import redis
import json
import time
import logging
import psycopg2

logging.basicConfig(level=logging.INFO, format='%(asctime)s [%(levelname)s] LIFECYCLE: %(message)s')

REDIS_PASSWORD = os.getenv('REDIS_PASSWORD')
redis_client = redis.Redis(
    host=os.getenv('REDIS_HOST', 'apex_redis_queue'),
    port=6379,
    db=0,
    password=REDIS_PASSWORD
)
LIFECYCLE_QUEUE = "apex_lifecycle_queue"
NOTIFY_QUEUE = "apex_notify_queue"

# Default thresholds — override per strategy in strategies.parameters JSONB
DEFAULTS = {
    'green_sharpe': 0.5,
    'green_win_rate': 0.45,
    'red_sharpe': 0.0,
    'red_win_rate': 0.35,
    'max_drawdown_threshold': 0.20,   # 20% max drawdown
    'grey_fail_count': 3              # consecutive Red evaluations before auto-culling
}


def get_db_conn():
    return psycopg2.connect(
        host=os.getenv('POSTGRES_HOST', 'apex_postgres_vault'),
        dbname=os.getenv('POSTGRES_DB', 'apex_vault'),
        user=os.getenv('POSTGRES_USER', 'apex_admin'),
        password=os.getenv('POSTGRES_PASSWORD')
    )


def get_thresholds(params: dict) -> dict:
    """Merge strategy-specific thresholds from JSONB params over defaults."""
    t = dict(DEFAULTS)
    if params:
        for key in DEFAULTS:
            if key in params:
                t[key] = float(params[key])
    return t


def evaluate_lifecycle(strategy_id):
    try:
        with get_db_conn() as conn:
            with conn.cursor() as cur:
                # Load current state and config
                cur.execute("""
                    SELECT lifecycle_state, parameters, consecutive_failures
                    FROM strategies WHERE id = %s
                """, (strategy_id,))
                row = cur.fetchone()
                if not row:
                    logging.warning(f"Strategy not found: {strategy_id}")
                    return

                current_state, params, consecutive_failures = row
                params = params or {}
                consecutive_failures = int(consecutive_failures or 0)
                t = get_thresholds(params)

                # Grey is terminal — never re-evaluated
                if current_state == 'grey':
                    return

                # Load latest performance
                cur.execute("""
                    SELECT total_trades, win_rate, sharpe_ratio, max_drawdown
                    FROM performance WHERE strategy_id = %s
                """, (strategy_id,))
                perf = cur.fetchone()
                if not perf:
                    logging.info(f"No performance data yet for {strategy_id}")
                    return

                total_trades, win_rate, sharpe, max_drawdown = perf
                win_rate = float(win_rate or 0)
                sharpe = float(sharpe or 0)
                max_drawdown = float(max_drawdown or 0)

                new_state = current_state
                notification_type = None

                # ── PROMOTION: Yellow or Red → Green ──────────────────────────────
                if current_state in ('yellow', 'red'):
                    if (total_trades >= 30
                            and sharpe >= t['green_sharpe']
                            and win_rate >= t['green_win_rate']
                            and max_drawdown <= t['max_drawdown_threshold']):
                        new_state = 'green'
                        notification_type = 'promoted_green'
                        consecutive_failures = 0

                # ── DEMOTION: Green → Red ─────────────────────────────────────────
                elif current_state == 'green':
                    if (sharpe < t['red_sharpe']
                            or win_rate < t['red_win_rate']
                            or max_drawdown > t['max_drawdown_threshold']):
                        new_state = 'red'
                        notification_type = 'demoted_red'
                        consecutive_failures += 1

                # ── AUTO-CULLING: Red → Grey ──────────────────────────────────────
                if new_state == 'red' and current_state == 'red':
                    # Didn't recover — count this as another failure
                    consecutive_failures += 1
                    if consecutive_failures >= t['grey_fail_count']:
                        new_state = 'grey'
                        notification_type = 'culled_grey'

                # Apply changes
                if new_state != current_state:
                    if new_state == 'grey':
                        cur.execute("""
                            UPDATE strategies
                            SET lifecycle_state = %s,
                                consecutive_failures = %s,
                                archived_at = NOW()
                            WHERE id = %s
                        """, (new_state, consecutive_failures, strategy_id))
                    else:
                        cur.execute("""
                            UPDATE strategies
                            SET lifecycle_state = %s,
                                consecutive_failures = %s
                            WHERE id = %s
                        """, (new_state, consecutive_failures, strategy_id))

                    logging.info(
                        f"State change: {strategy_id} | {current_state} → {new_state} | "
                        f"Sharpe: {sharpe:.3f} | WR: {win_rate:.1%} | DD: {max_drawdown:.1%}"
                    )

                    # Notify Discord
                    if notification_type:
                        redis_client.lpush(NOTIFY_QUEUE, json.dumps({
                            "type": notification_type,
                            "strategy_id": strategy_id,
                            "from_state": current_state,
                            "to_state": new_state,
                            "sharpe": round(sharpe, 4),
                            "win_rate": round(win_rate, 4),
                            "max_drawdown": round(max_drawdown, 4),
                            "total_trades": total_trades
                        }))
                else:
                    # No state change — still update failure counter
                    cur.execute("""
                        UPDATE strategies SET consecutive_failures = %s WHERE id = %s
                    """, (consecutive_failures, strategy_id))
                    logging.info(
                        f"No change: {strategy_id} stays {current_state} | "
                        f"Sharpe: {sharpe:.3f} | WR: {win_rate:.1%}"
                    )

    except Exception as e:
        logging.error(f"Lifecycle error for {strategy_id}: {e}")


def run_lifecycle_engine():
    logging.info("Apex Lifecycle Engine: ONLINE. Listening on apex_lifecycle_queue...")

    while True:
        raw = None
        try:
            result = redis_client.brpop(LIFECYCLE_QUEUE, timeout=0)
            if not result:
                continue

            _, raw = result
            strategy_id = raw.decode('utf-8').strip()
            evaluate_lifecycle(strategy_id)

        except redis.ConnectionError:
            logging.error("Redis connection lost. Retrying in 5s...")
            time.sleep(5)
        except Exception as e:
            logging.error(f"Lifecycle engine error: {e}")
            time.sleep(1)


if __name__ == "__main__":
    run_lifecycle_engine()
