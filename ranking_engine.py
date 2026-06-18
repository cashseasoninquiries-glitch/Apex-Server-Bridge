"""
Apex Ranking Engine — Phase 2.5
Runs every hour. Scores all active (non-grey) strategies by composite score
and writes rankings to both Postgres (rank_score column) and Redis (for dashboard).

Composite score weights:
  35% Sharpe ratio
  25% Win rate
  20% Drawdown (lower = better, inverted)
  15% Confidence stars (data maturity)
   5% Regime fit bonus/penalty

The regime fit component reads the current market regime from Redis
(written by regime_detector). If regime is stale/unavailable, this component
is excluded from scoring.
"""

import os
import redis
import json
import time
import logging
import psycopg2
from datetime import datetime, timezone

logging.basicConfig(level=logging.INFO, format='%(asctime)s [%(levelname)s] RANKING: %(message)s')

REDIS_PASSWORD = os.getenv('REDIS_PASSWORD')
redis_client = redis.Redis(
    host=os.getenv('REDIS_HOST', 'apex_redis_queue'),
    port=6379,
    db=0,
    password=REDIS_PASSWORD
)

RANKING_KEY = "apex:strategy_rankings"
RANK_INTERVAL = 3600  # Every hour


def get_db_conn():
    return psycopg2.connect(
        host=os.getenv('POSTGRES_HOST', 'apex_postgres_vault'),
        dbname=os.getenv('POSTGRES_DB', 'apex_vault'),
        user=os.getenv('POSTGRES_USER', 'apex_admin'),
        password=os.getenv('POSTGRES_PASSWORD')
    )


def normalize(value, min_val, max_val):
    """Normalize a value to 0–1 range. Returns 0.5 if all values are equal."""
    if max_val == min_val:
        return 0.5
    return max(0.0, min(1.0, (value - min_val) / (max_val - min_val)))


def get_current_regime():
    """Fetch current market regime from Redis. Returns None if stale/missing."""
    try:
        raw = redis_client.get("apex:market_regime")
        if raw:
            return json.loads(raw).get("regime")
    except Exception:
        pass
    return None


def run_ranking():
    try:
        with get_db_conn() as conn:
            with conn.cursor() as cur:
                cur.execute("""
                    SELECT
                        s.id, s.name, s.lifecycle_state, s.confidence_stars,
                        p.sharpe_ratio, p.win_rate, p.max_drawdown,
                        p.total_trades, p.total_pnl, p.expectancy
                    FROM strategies s
                    LEFT JOIN performance p ON p.strategy_id = s.id
                    WHERE s.lifecycle_state != 'grey'
                    ORDER BY s.created_at
                """)
                rows = cur.fetchall()

                if not rows:
                    logging.info("No active strategies to rank")
                    return

                regime = get_current_regime()

                # Extract ranges for normalization
                sharpes = [float(r[4] or 0) for r in rows]
                win_rates = [float(r[5] or 0) for r in rows]
                drawdowns = [float(r[6] or 0) for r in rows]

                min_s, max_s = min(sharpes), max(sharpes)
                min_w, max_w = min(win_rates), max(win_rates)
                min_d, max_d = min(drawdowns), max(drawdowns)

                ranked = []
                for row in rows:
                    sid, name, state, stars, sharpe, wr, dd, trades, pnl, expectancy = row

                    sharpe = float(sharpe or 0)
                    wr = float(wr or 0)
                    dd = float(dd or 0)
                    stars = int(stars or 0)
                    trades = int(trades or 0)
                    pnl = float(pnl or 0)

                    sharpe_score = normalize(sharpe, min_s, max_s)
                    wr_score = normalize(wr, min_w, max_w)
                    dd_score = 1 - normalize(dd, min_d, max_d)   # Invert — lower drawdown = better
                    confidence_score = stars / 3.0                 # 0, 0.33, 0.67, 1.0

                    # Regime fit: Green strategies get a bonus in trending markets,
                    # penalty in volatile markets
                    regime_bonus = 0.0
                    if regime:
                        if state == 'green' and 'trending' in regime:
                            regime_bonus = 0.1
                        elif state == 'green' and regime == 'volatile':
                            regime_bonus = -0.05
                        elif state == 'red' and regime == 'volatile':
                            regime_bonus = -0.1

                    composite = (
                        sharpe_score      * 0.35 +
                        wr_score          * 0.25 +
                        dd_score          * 0.20 +
                        confidence_score  * 0.15 +
                        regime_bonus      * 0.05
                    )

                    ranked.append({
                        'strategy_id': str(sid),
                        'name': name,
                        'state': state,
                        'stars': stars,
                        'sharpe': sharpe,
                        'win_rate': wr,
                        'max_drawdown': dd,
                        'total_trades': trades,
                        'total_pnl': pnl,
                        'composite_score': round(composite, 4),
                        'regime': regime or "unknown"
                    })

                ranked.sort(key=lambda x: x['composite_score'], reverse=True)

                for i, r in enumerate(ranked):
                    r['rank'] = i + 1
                    cur.execute(
                        "UPDATE strategies SET rank_score = %s WHERE id = %s",
                        (r['composite_score'], r['strategy_id'])
                    )

                # Store full rankings in Redis for dashboard consumption
                redis_client.set(RANKING_KEY, json.dumps({
                    "rankings": ranked,
                    "regime": regime or "unknown",
                    "total_strategies": len(ranked),
                    "updated_at": datetime.now(timezone.utc).isoformat()
                }), ex=7200)  # 2hr TTL

                top = ranked[0]['name'] if ranked else "none"
                logging.info(
                    f"Rankings updated: {len(ranked)} strategies | "
                    f"#1: {top} | Regime: {regime or 'unknown'}"
                )

    except Exception as e:
        logging.error(f"Ranking error: {e}")


def run_ranking_engine():
    logging.info("Apex Ranking Engine: ONLINE. Ranking every hour...")

    # Run immediately on startup, then on interval
    run_ranking()

    while True:
        time.sleep(RANK_INTERVAL)
        run_ranking()


if __name__ == "__main__":
    run_ranking_engine()
