import os
import sys
import redis
import json
import logging
from flask import Flask, request, jsonify

logging.basicConfig(level=logging.INFO, format='%(asctime)s [%(levelname)s] GATEWAY: %(message)s')

app = Flask(__name__)

# INTERNAL NETWORK CABLES
redis_client = redis.Redis(host='apex_redis_queue', port=6379, db=0)
QUEUE_NAME = "apex_signal_queue"

# THE PERIMETER SECURITY KEY — fail closed if it's not configured, rather than
# silently falling back to a default value (which is now public knowledge).
TV_SECRET = os.getenv("TRADINGVIEW_SECRET")
if not TV_SECRET:
    logging.critical("TRADINGVIEW_SECRET is not set. Refusing to start without it.")
    sys.exit(1)

@app.route('/webhook', methods=['POST'])
def tradingview_webhook():
    try:
        data = request.get_json()
        if not data:
            logging.warning("Rejected: Empty payload received.")
            return jsonify({"status": "error", "message": "No JSON payload detected"}), 400

        # SECURITY CHECK
        incoming_secret = data.get("passphrase")
        if incoming_secret != TV_SECRET:
            logging.warning("SECURITY BREACH BLOCKED: Invalid passphrase attempt (value withheld from logs).")
            return jsonify({"status": "unauthorized", "message": "Invalid passphrase"}), 401

        # Extract core routing variables
        strategy_id = data.get("strategy_id")
        ticker = data.get("ticker")
        action = data.get("action")

        if not all([strategy_id, ticker, action]):
            logging.error("Rejected: Payload missing critical routing data.")
            return jsonify({"status": "error", "message": "Missing required fields"}), 400

        # Strip the secret before it goes anywhere downstream (queue, DB, logs).
        safe_data = {k: v for k, v in data.items() if k != "passphrase"}

        # Push to the high-speed Redis queue
        redis_client.lpush(QUEUE_NAME, json.dumps(safe_data))
        logging.info(f"Signal Accepted & Queued: {strategy_id} | {action} {ticker}")

        return jsonify({"status": "success", "message": "Signal queued"}), 200

    except Exception as e:
        logging.error(f"Gateway execution error: {str(e)}")
        return jsonify({"status": "error", "message": "Internal gateway failure"}), 500

if __name__ == '__main__':
    app.run(host='0.0.0.0', port=5000)
