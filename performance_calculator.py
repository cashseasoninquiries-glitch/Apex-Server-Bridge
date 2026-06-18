"""
Apex Performance Calculator — Phase 2.1
Listens on apex_perf_queue (strategy_id pushed by recorder after every trade close).
Pulls all closed trades for that strategy and recalculates metrics from scratch.
Upserts into performance table. Triggers lifecycle engine check.

Metrics calculated:
  - win_rate, winning/losing trade counts
  - avg_win, avg_loss, profit_factor
  - total_pnl, expectancy
  - max_drawdown (peak-to-trough on cumulative PnL curve)
  - sharpe_ratio, sortino_ratio (annualized, per-trade % returns)
  - avg_slippage
"""

import os
import redis
import json
import time
import logging
import psycopg2
import math
import statistics

logging.basicConfig(level=logging.INFO, format='%(asctime)s [%(levelname)s] PERF_CALC: %(message)s')

REDIS_PASSWORD = os.getenv('REDIS_PASSWORD')
redis_client = redis.Redis(
    host=os.getenv('REDIS_HOST', 'apex_redis_queue'),
    port=6379,
    db=0,
    password=REDIS_PASSWORD
)
PERF_QUEUE = "apex_perf_queue"
LIFECYCLE_QUEUE = "apex_lifecycle_queue"
NOTIFY_QUEUE = "apex_notify_queue"


def get_db_conn():
    return psycopg2.connect(
        host=os.getenv('POSTGRES_HOST', 'apex_postgres_vault'),
        dbname=os.getenv('POSTGRES_DB', 'apex_vault'),
        user=os.getenv('POSTGRES_USER', 'apex_admin'),
        password=os.getenv('POSTGRES_PASSWORD')
    )


def write_dead_letter(payload, error):
    try:
        with get_db_conn() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    "INSERT INTO dead_letters (source, raw_payload, error_message) VALUES (%s, %s, %s)",
                    ('performance_calculator', json.dumps({'strategy_id': str(payload)}), str(error))
                )
    except Exception as e:
        logging.error(f"Dead letter write failed: {e}")


def calculate_sharpe(pnl_pcts, risk_free=0.0):
    """
    Annualized Sharpe ratio from per-trade % returns.
    Assumes ~252 trading days. Returns 0 if insufficient data.
    """
    if len(pnl_pcts) < 2:
        return 0.0
    mean_r = statistics.mean(pnl_pcts)
    std_r = statistics.stdev(pnl_pcts)
    if std_r == 0:
        return 0.0
    return round((mean_r - risk_free) / std_r * math.sqrt(252), 4)


def calculate_sortino(pnl_pcts, risk_free=0.0):
    """
    Sortino ratio — like Sharpe but only penalizes downside volatility.
    Returns 10.0 (effectively infinite) if there are no losing trades.
    """
    if len(pnl_pcts) < 2:
        return 0.0
    mean_r = statistics.mean(pnl_pcts)
    downside = [r for r in pnl_pcts if r < risk_free]
    if not downside:
        return 10.0
    downside_std = statistics.stdev(downside) if len(downside) > 1 else abs(downside[0])
    if downside_std == 0:
        return 0.0
    return round((mean_r - risk_free) / downside_std * math.sqrt(252), 4)


def calculate_max_drawdown(cumulative_pnl):
    """
    Maximum peak-to-trough decline as a fraction of peak.
    E.g. 0.15 = 15% drawdown.
    """
    if not cumulative_pnl:
        return 0.0
    peak = cumulative_pnl[0]
    max_dd = 0.0
    for val in cumulative_pnl:
        if val > peak:
            peak = val
        if peak != 0:
            dd = (peak - val) / abs(peak)
            if dd > max_dd:
                max_dd = dd
    return round(max_dd, 6)


def run_calculation(strategy_id):
    """Core calculation — pull all closed trades and compute metrics."""
    try:
        with get_db_conn() as conn:
            with conn.cursor() as cur:
                cur.execute("""
                    SELECT pnl, pnl_pct, slippage
                    FROM trades
                    WHERE strategy_id = %s AND status = 'closed'
                    ORDER BY closed_at ASC
                """, (strategy_id,))
                trades = cur.fetchall()

                if not trades:
                    logging.info(f"No closed trades yet for {strategy_id}")
                    return None

                pnls = [float(t[0] or 0) for t in trades]
                pnl_pcts = [float(t[1] or 0) for t in trades]
                slippages = [float(t[2] or 0) for t in trades]

                total_trades = len(trades)
                winning_trades = sum(1 for p in pnls if p > 0)
                losing_trades = total_trades - winning_trades

                win_rate = winning_trades / total_trades
                loss_rate = 1 - win_rate

                wins = [p for p in pnls if p > 0]
                losses = [p for p in pnls if p <= 0]

                avg_win = statistics.mean(wins) if wins else 0.0
                avg_loss = statistics.mean(losses) if losses else 0.0

                sum_wins = sum(wins)
                sum_losses = abs(sum(losses))
                profit_factor = sum_wins / sum_losses if sum_losses > 0 else 10.0

                total_pnl = sum(pnls)
                expectancy = (win_rate * avg_win) + (loss_rate * avg_loss)

                # Running cumulative PnL for drawdown calculation
                cumulative = []
                running = 0
                for p in pnls:
                    running += p
                    cumulative.append(running)

                max_drawdown = calculate_max_drawdown(cumulative)
                sharpe = calculate_sharpe(pnl_pcts)
                sortino = calculate_sortino(pnl_pcts)
                avg_slippage = statistics.mean(slippages) if slippages else 0.0

                metrics = {
                    'total_trades': total_trades,
                    'winning_trades': winning_trades,
                    'losing_trades': losing_trades,
                    'win_rate': round(win_rate, 4),
                    'avg_win': round(avg_win, 8),
                    'avg_loss': round(avg_loss, 8),
                    'profit_factor': round(profit_factor, 4),
                    'total_pnl': round(total_pnl, 8),
                    'max_drawdown': max_drawdown,
                    'sharpe_ratio': sharpe,
                    'sortino_ratio': sortino,
                    'expectancy': round(expectancy, 8),
                    'avg_slippage': round(avg_slippage, 8)
                }

                # Upsert into performance table
                cur.execute("""
                    INSERT INTO performance (
                        strategy_id, total_trades, winning_trades, losing_trades,
                        win_rate, avg_win, avg_loss, profit_factor, total_pnl,
                        max_drawdown, sharpe_ratio, sortino_ratio, expectancy,
                        avg_slippage, last_calculated_at
                    ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, NOW())
                    ON CONFLICT (strategy_id) DO UPDATE SET
                        total_trades       = EXCLUDED.total_trades,
                        winning_trades     = EXCLUDED.winning_trades,
                        losing_trades      = EXCLUDED.losing_trades,
                        win_rate           = EXCLUDED.win_rate,
                        avg_win            = EXCLUDED.avg_win,
                        avg_loss           = EXCLUDED.avg_loss,
                        profit_factor      = EXCLUDED.profit_factor,
                        total_pnl          = EXCLUDED.total_pnl,
                        max_drawdown       = EXCLUDED.max_drawdown,
                        sharpe_ratio       = EXCLUDED.sharpe_ratio,
                        sortino_ratio      = EXCLUDED.sortino_ratio,
                        expectancy         = EXCLUDED.expectancy,
                        avg_slippage       = EXCLUDED.avg_slippage,
                        last_calculated_at = NOW()
                """, (
                    strategy_id,
                    total_trades, winning_trades, losing_trades,
                    win_rate, avg_win, avg_loss, profit_factor, total_pnl,
                    max_drawdown, sharpe, sortino, expectancy, avg_slippage
                ))

                logging.info(
                    f"Performance updated: {strategy_id} | "
                    f"Sharpe: {sharpe} | WR: {win_rate:.1%} | "
                    f"Trades: {total_trades} | PnL: ${total_pnl:.2f}"
                )
                return metrics

    except Exception as e:
        logging.error(f"Calculation error for {strategy_id}: {e}")
        write_dead_letter(strategy_id, str(e))
        return None


def run_performance_calculator():
    logging.info("Apex Performance Calculator: ONLINE. Listening on apex_perf_queue...")

    while True:
        raw = None
        try:
            result = redis_client.brpop(PERF_QUEUE, timeout=0)
            if not result:
                continue

            _, raw = result
            strategy_id = raw.decode('utf-8').strip()
            logging.info(f"Calculating for: {strategy_id}")

            metrics = run_calculation(strategy_id)

            if metrics:
                # Hand off to lifecycle engine
                redis_client.lpush(LIFECYCLE_QUEUE, strategy_id)

                # Performance summary to Discord
                redis_client.lpush(NOTIFY_QUEUE, json.dumps({
                    "type": "perf_update",
                    "strategy_id": strategy_id,
                    "metrics": metrics
                }))

        except redis.ConnectionError:
            logging.error("Redis connection lost. Retrying in 5s...")
            time.sleep(5)
        except Exception as e:
            logging.error(f"Performance calculator error: {e}")
            write_dead_letter(raw, str(e))
            time.sleep(1)


if __name__ == "__main__":
    run_performance_calculator()
