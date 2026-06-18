"""
Apex Discord Notifier — Phase 2.6
Listens on apex_notify_queue. For each notification, formats and sends
a rich embed to your Discord webhook.

To enable: add DISCORD_WEBHOOK_URL to your .env file.
Without it, notifications are logged locally but not sent.

Notification types:
  promoted_green  — strategy reached Green status
  demoted_red     — strategy flagged Red
  culled_grey     — strategy auto-culled
  perf_update     — performance metrics refreshed (optional, can be noisy)
  dead_letter     — a signal failed to process
  error           — system error
"""

import os
import redis
import json
import time
import logging
import requests
from datetime import datetime, timezone

logging.basicConfig(level=logging.INFO, format='%(asctime)s [%(levelname)s] DISCORD: %(message)s')

REDIS_PASSWORD = os.getenv('REDIS_PASSWORD')
redis_client = redis.Redis(
    host=os.getenv('REDIS_HOST', 'apex_redis_queue'),
    port=6379,
    db=0,
    password=REDIS_PASSWORD
)

NOTIFY_QUEUE = "apex_notify_queue"
DISCORD_WEBHOOK_URL = os.getenv("DISCORD_WEBHOOK_URL", "")

# Suppress noisy perf_update pings — only send lifecycle changes + errors
SUPPRESS_TYPES = {"perf_update"}

# Discord embed colors (decimal)
COLORS = {
    "promoted_green": 0x2ECC71,
    "demoted_red":    0xE74C3C,
    "culled_grey":    0x95A5A6,
    "perf_update":    0x3498DB,
    "dead_letter":    0xFF6B35,
    "error":          0xFF0000,
}

EMOJIS = {
    "promoted_green": "🟢",
    "demoted_red":    "🔴",
    "culled_grey":    "⚫",
    "perf_update":    "📊",
    "dead_letter":    "⚠️",
    "error":          "🚨",
}


def build_embed(n: dict) -> dict:
    ntype = n.get("type", "unknown")
    sid = n.get("strategy_id", "unknown")
    emoji = EMOJIS.get(ntype, "ℹ️")
    color = COLORS.get(ntype, 0x7F8C8D)
    ts = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")

    if ntype == "promoted_green":
        title = f"{emoji} Strategy Promoted — Green"
        desc = (
            f"**{sid}**\n"
            f"Sharpe: `{float(n.get('sharpe', 0)):.3f}` | "
            f"Win Rate: `{float(n.get('win_rate', 0)):.1%}` | "
            f"Drawdown: `{float(n.get('max_drawdown', 0)):.1%}` | "
            f"Trades: `{n.get('total_trades', '?')}`"
        )

    elif ntype == "demoted_red":
        title = f"{emoji} Strategy Flagged — Red"
        desc = (
            f"**{sid}**\n"
            f"Sharpe: `{float(n.get('sharpe', 0)):.3f}` | "
            f"Win Rate: `{float(n.get('win_rate', 0)):.1%}` | "
            f"Drawdown: `{float(n.get('max_drawdown', 0)):.1%}`"
        )

    elif ntype == "culled_grey":
        title = f"{emoji} Strategy Auto-Culled — Grey"
        desc = (
            f"**{sid}** has been retired after repeated underperformance.\n"
            f"Trade data preserved for ML training."
        )

    elif ntype == "perf_update":
        m = n.get("metrics", {})
        title = f"{emoji} Performance Updated"
        desc = (
            f"**{sid}**\n"
            f"Trades: `{m.get('total_trades', 0)}` | "
            f"Win Rate: `{float(m.get('win_rate', 0)):.1%}` | "
            f"Sharpe: `{m.get('sharpe_ratio', 0):.3f}` | "
            f"PnL: `${float(m.get('total_pnl', 0)):.2f}`"
        )

    elif ntype == "dead_letter":
        title = f"{emoji} Dead Letter"
        desc = (
            f"Source: `{n.get('source', 'unknown')}`\n"
            f"Error: {str(n.get('error', 'unknown'))[:300]}"
        )

    else:
        title = f"{emoji} Apex Notification"
        desc = f"```{json.dumps(n, indent=2)[:800]}```"

    return {
        "embeds": [{
            "title": title,
            "description": desc,
            "color": color,
            "footer": {"text": f"Apex Engine  •  {ts}"}
        }]
    }


def send_to_discord(notification: dict):
    if not DISCORD_WEBHOOK_URL:
        logging.debug("DISCORD_WEBHOOK_URL not set — notification skipped")
        return

    ntype = notification.get("type", "")
    if ntype in SUPPRESS_TYPES:
        logging.debug(f"Suppressing noisy notification type: {ntype}")
        return

    try:
        payload = build_embed(notification)
        resp = requests.post(DISCORD_WEBHOOK_URL, json=payload, timeout=10)
        if resp.status_code == 204:
            logging.info(f"Discord: sent [{ntype}] for {notification.get('strategy_id', '?')}")
        else:
            logging.warning(f"Discord returned {resp.status_code}: {resp.text[:200]}")
    except Exception as e:
        logging.error(f"Discord send error: {e}")


def run_discord_notifier():
    logging.info("Apex Discord Notifier: ONLINE. Listening on apex_notify_queue...")

    if not DISCORD_WEBHOOK_URL:
        logging.warning(
            "DISCORD_WEBHOOK_URL not set in .env — "
            "notifications will be logged but not sent to Discord"
        )

    while True:
        raw = None
        try:
            result = redis_client.brpop(NOTIFY_QUEUE, timeout=0)
            if not result:
                continue

            _, raw = result
            notification = json.loads(raw.decode('utf-8'))
            send_to_discord(notification)

        except redis.ConnectionError:
            logging.error("Redis connection lost. Retrying in 5s...")
            time.sleep(5)
        except Exception as e:
            logging.error(f"Discord notifier error: {e}")
            time.sleep(1)


if __name__ == "__main__":
    run_discord_notifier()
