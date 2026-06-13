import os
import redis
import json
import time
import logging
from datetime import datetime, timezone
from alpaca.data.historical import StockHistoricalDataClient
from alpaca.data.requests import StockBarsRequest
from alpaca.data.timeframe import TimeFrame

logging.basicConfig(level=logging.INFO, format='%(asctime)s [%(levelname)s] STRATEGY: %(message)s')

# --- REDIS CONNECTION ---
redis_client = redis.Redis(host='apex_redis_queue', port=6379, db=0, password=os.getenv('REDIS_PASSWORD'))
SIGNAL_QUEUE = "apex_signal_queue"

# --- ALPACA DATA CLIENT ---
ALPACA_API_KEY = os.getenv("ALPACA_API_KEY")
ALPACA_SECRET_KEY = os.getenv("ALPACA_SECRET_KEY")
data_client = StockHistoricalDataClient(ALPACA_API_KEY, ALPACA_SECRET_KEY)

# --- STRATEGY CONFIG (override via .env) ---
STRATEGY_ID = os.getenv("STRATEGY_MVP_ID", "strategy_mvp_sma")
TICKER = os.getenv("STRATEGY_MVP_TICKER", "AAPL")
FAST_PERIOD = int(os.getenv("STRATEGY_MVP_FAST_PERIOD", "9"))
SLOW_PERIOD = int(os.getenv("STRATEGY_MVP_SLOW_PERIOD", "21"))
POLL_INTERVAL = int(os.getenv("STRATEGY_MVP_POLL_SECONDS", "300"))  # 5 minutes default

# --- INTERNAL STATE ---
# Tracks the last signal sent to avoid spamming the same signal every poll
last_signal_sent = None


def get_bars(ticker, limit):
    """Fetch the most recent N 5-minute bars for a ticker."""
    from alpaca.data.requests import StockBarsRequest
    from alpaca.data.timeframe import TimeFrame
    import pandas as pd

    request = StockBarsRequest(
        symbol_or_symbols=ticker,
        timeframe=TimeFrame.Minute,
        limit=limit + 10  # buffer for potential gaps
    )
    bars = data_client.get_stock_bars(request)
    df = bars.df

    if df.empty:
        return None

    # If multi-symbol index, filter to our ticker
    if isinstance(df.index, pd.MultiIndex):
        df = df.loc[ticker]

    # Return just close prices as a list, most recent last
    return list(df['close'].values)


def sma(prices, period):
    """Calculate simple moving average for the last N prices."""
    if len(prices) < period:
        return None
    return sum(prices[-period:]) / period


def push_signal(ticker, action):
    """Push a formatted signal onto the Redis queue."""
    signal = {
        "ticker": ticker,
        "action": action,
        "strategy_id": STRATEGY_ID,
        "timestamp": datetime.now(timezone.utc).isoformat()
    }
    redis_client.lpush(SIGNAL_QUEUE, json.dumps(signal))
    logging.info(f"Signal pushed: {action} {ticker} → {SIGNAL_QUEUE}")


def is_market_hours():
    """Basic check: US market hours Mon-Fri 9:30am-4:00pm ET.
    Using UTC: 14:30-21:00 UTC (ignores DST — safe for paper trading)."""
    now = datetime.now(timezone.utc)
    # Monday=0 ... Friday=4
    if now.weekday() >= 5:
        return False
    market_open = now.replace(hour=14, minute=30, second=0, microsecond=0)
    market_close = now.replace(hour=21, minute=0, second=0, microsecond=0)
    return market_open <= now <= market_close


def run_strategy():
    global last_signal_sent

    logging.info(f"Apex Strategy MVP: ONLINE")
    logging.info(f"Ticker: {TICKER} | SMA Fast: {FAST_PERIOD} | SMA Slow: {SLOW_PERIOD} | Poll: {POLL_INTERVAL}s")

    while True:
        try:
            if not is_market_hours():
                logging.info("Market closed. Sleeping 60s...")
                time.sleep(60)
                continue

            # Fetch enough bars for both SMAs
            bars_needed = SLOW_PERIOD + 5
            prices = get_bars(TICKER, bars_needed)

            if prices is None or len(prices) < bars_needed:
                logging.warning(f"Not enough bar data yet ({len(prices) if prices else 0} bars). Retrying...")
                time.sleep(POLL_INTERVAL)
                continue

            fast = sma(prices, FAST_PERIOD)
            slow = sma(prices, SLOW_PERIOD)

            logging.info(f"{TICKER} | Fast SMA({FAST_PERIOD}): {fast:.4f} | Slow SMA({SLOW_PERIOD}): {slow:.4f}")

            # Determine signal direction
            if fast > slow:
                current_signal = "LONG"
            elif fast < slow:
                current_signal = "SELL"
            else:
                current_signal = None  # Dead cross / equal, no signal

            # Only push if signal has CHANGED (crossover event)
            if current_signal and current_signal != last_signal_sent:
                logging.info(f"CROSSOVER DETECTED: {last_signal_sent} → {current_signal}")
                push_signal(TICKER, current_signal)
                last_signal_sent = current_signal
            else:
                logging.info(f"No crossover. Signal unchanged: {last_signal_sent}")

        except redis.ConnectionError:
            logging.error("Redis connection lost. Retrying in 10s...")
            time.sleep(10)
            continue
        except Exception as e:
            logging.error(f"Strategy error: {str(e)}")
            time.sleep(POLL_INTERVAL)
            continue

        time.sleep(POLL_INTERVAL)


if __name__ == "__main__":
    run_strategy()
