"""
Apex Regime Detector — Phase 2.2
Runs on a 15-minute interval. Fetches recent SPY daily bars from Alpaca,
calculates ADX, trend direction, and volatility, then labels the current
market regime.

Regime labels:
  trending_up    — ADX ≥ 25, price above 20-day SMA
  trending_down  — ADX ≥ 25, price below 20-day SMA
  choppy         — ADX < 25, low directional conviction
  volatile       — Recent True Range is elevated vs 30-day average

Results written to:
  - Redis key  apex:market_regime  (TTL 1hr, for fast dashboard/ranking access)
  - Postgres   market_regimes table (full history for ML training)
"""

import os
import redis
import json
import time
import logging
import psycopg2
from datetime import datetime, timedelta, timezone

logging.basicConfig(level=logging.INFO, format='%(asctime)s [%(levelname)s] REGIME: %(message)s')

REDIS_PASSWORD = os.getenv('REDIS_PASSWORD')
redis_client = redis.Redis(
    host=os.getenv('REDIS_HOST', 'apex_redis_queue'),
    port=6379,
    db=0,
    password=REDIS_PASSWORD
)

REGIME_KEY = "apex:market_regime"
DETECT_INTERVAL = 900   # 15 minutes

ALPACA_API_KEY = os.getenv("ALPACA_API_KEY")
ALPACA_SECRET_KEY = os.getenv("ALPACA_SECRET_KEY")


def get_db_conn():
    return psycopg2.connect(
        host=os.getenv('POSTGRES_HOST', 'apex_postgres_vault'),
        dbname=os.getenv('POSTGRES_DB', 'apex_vault'),
        user=os.getenv('POSTGRES_USER', 'apex_admin'),
        password=os.getenv('POSTGRES_PASSWORD')
    )


def smooth_rma(data, period):
    """Wilder's smoothed moving average (used in ADX calculation)."""
    if len(data) < period:
        return []
    result = [sum(data[:period])]
    for val in data[period:]:
        result.append(result[-1] - (result[-1] / period) + val)
    return result


def calculate_adx(highs, lows, closes, period=14):
    """
    ADX (Average Directional Index) — measures trend strength, not direction.
    > 25: trending   |   < 20: choppy/ranging
    """
    if len(closes) < period + 1:
        return 0.0

    tr_list, plus_dm, minus_dm = [], [], []

    for i in range(1, len(closes)):
        tr = max(
            highs[i] - lows[i],
            abs(highs[i] - closes[i - 1]),
            abs(lows[i] - closes[i - 1])
        )
        tr_list.append(tr)

        up_move = highs[i] - highs[i - 1]
        down_move = lows[i - 1] - lows[i]

        plus_dm.append(up_move if up_move > down_move and up_move > 0 else 0)
        minus_dm.append(down_move if down_move > up_move and down_move > 0 else 0)

    atr = smooth_rma(tr_list, period)
    s_plus = smooth_rma(plus_dm, period)
    s_minus = smooth_rma(minus_dm, period)

    dx_list = []
    for i in range(len(atr)):
        if atr[i] == 0:
            continue
        plus_di = 100 * s_plus[i] / atr[i]
        minus_di = 100 * s_minus[i] / atr[i]
        di_sum = plus_di + minus_di
        if di_sum == 0:
            continue
        dx_list.append(100 * abs(plus_di - minus_di) / di_sum)

    if len(dx_list) < period:
        return 0.0

    return round(sum(dx_list[-period:]) / period, 2)


def detect_regime():
    try:
        from alpaca.data.historical import StockHistoricalDataClient
        from alpaca.data.requests import StockBarsRequest
        from alpaca.data.timeframe import TimeFrame

        client = StockHistoricalDataClient(ALPACA_API_KEY, ALPACA_SECRET_KEY)

        request = StockBarsRequest(
            symbol_or_symbols=["SPY"],
            timeframe=TimeFrame.Day,
            start=datetime.now(timezone.utc) - timedelta(days=50),
            end=datetime.now(timezone.utc)
        )
        bars = client.get_stock_bars(request)
        spy_bars = bars["SPY"]

        if len(spy_bars) < 20:
            logging.warning("Not enough SPY bars for regime detection")
            return None

        highs = [float(b.high) for b in spy_bars]
        lows = [float(b.low) for b in spy_bars]
        closes = [float(b.close) for b in spy_bars]

        adx = calculate_adx(highs, lows, closes, period=14)

        # Trend: price vs 20-day SMA
        sma20 = sum(closes[-20:]) / 20
        current_price = closes[-1]
        trend = "up" if current_price > sma20 else "down"

        # Volatility: recent 10-day average range vs prior 20-day average range
        recent_ranges = [highs[i] - lows[i] for i in range(-10, 0)]
        prior_ranges = [highs[i] - lows[i] for i in range(-30, -10)]
        current_vol = sum(recent_ranges) / len(recent_ranges)
        avg_vol = sum(prior_ranges) / len(prior_ranges) if prior_ranges else current_vol
        vol_ratio = current_vol / avg_vol if avg_vol > 0 else 1.0
        vol_label = "high" if vol_ratio > 1.3 else ("low" if vol_ratio < 0.7 else "normal")

        # Classify regime
        if vol_label == "high":
            regime = "volatile"
        elif adx >= 25:
            regime = f"trending_{trend}"
        else:
            regime = "choppy"

        regime_data = {
            "regime": regime,
            "adx": adx,
            "trend_direction": trend,
            "vol_label": vol_label,
            "vol_ratio": round(vol_ratio, 3),
            "sma20": round(sma20, 2),
            "current_price": round(current_price, 2),
            "detected_at": datetime.now(timezone.utc).isoformat()
        }

        # Fast access via Redis (expires in 1 hour)
        redis_client.set(REGIME_KEY, json.dumps(regime_data), ex=3600)

        # Persistent history in Postgres
        with get_db_conn() as conn:
            with conn.cursor() as cur:
                cur.execute("""
                    INSERT INTO market_regimes
                        (regime_label, adx_value, trend_direction, volatility_label)
                    VALUES (%s, %s, %s, %s)
                """, (regime, adx, trend, vol_label))

        logging.info(
            f"Regime: {regime} | ADX: {adx} | Trend: {trend} | "
            f"Vol: {vol_label} ({vol_ratio:.2f}x) | SPY: ${current_price:.2f}"
        )
        return regime_data

    except Exception as e:
        logging.error(f"Regime detection error: {e}")
        return None


def run_regime_detector():
    logging.info("Apex Regime Detector: ONLINE. Detecting every 15 minutes...")

    while True:
        detect_regime()
        time.sleep(DETECT_INTERVAL)


if __name__ == "__main__":
    run_regime_detector()
