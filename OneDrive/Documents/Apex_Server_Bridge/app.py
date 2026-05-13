from flask import Flask, request, jsonify
from flask_sqlalchemy import SQLAlchemy
import requests
import os

app = Flask(__name__)

# ==========================================
# 1. API KEYS
# ==========================================
# Make sure to paste your actual Alpaca Paper keys here
ALPACA_API_KEY = "YOUR_PAPER_KEY"
ALPACA_SECRET_KEY = "YOUR_PAPER_SECRET"
ALPACA_ENDPOINT = "https://paper-api.alpaca.markets/v2/orders"

# ==========================================
# 2. DATABASE CONNECTION (THE VAULT)
# ==========================================
app.config['SQLALCHEMY_DATABASE_URI'] = os.environ.get('DATABASE_URL')
app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False
db = SQLAlchemy(app)

# ==========================================
# 3. THE TITANIUM SCHEMA
# ==========================================
class Strategy(db.Model):
    __tablename__ = 'strategy_library'
    id = db.Column(db.Integer, primary_key=True)
    strategy_name = db.Column(db.String(100), unique=True, nullable=False)
    ticker = db.Column(db.String(20), nullable=False)
    is_active = db.Column(db.Boolean, default=True)

# ==========================================
# 4. THE ROUTER (THE INGRESS)
# ==========================================
@app.route('/webhook', methods=['POST'])
def webhook():
    try:
        data = request.get_json(silent=True)
        if not data:
            return jsonify({"error": "Empty payload"}), 400

        strat_name = data.get('strategy_name')
        action = data.get('action')
        qty = data.get('qty', 1)

        # --- THE SIEVE ---
        # Ask the Brain: Does this strategy exist and is it active?
        active_strat = Strategy.query.filter_by(strategy_name=strat_name, is_active=True).first()
        
        if not active_strat:
            print(f"BLOCKED: Strategy '{strat_name}' is paused or does not exist.")
            return jsonify({"status": "ignored", "reason": "Strategy inactive"}), 200

        # --- THE HANDS ---
        order_details = {
            "symbol": active_strat.ticker.upper(),
            "qty": str(qty),
            "side": action.lower(),
            "type": "market",
            "time_in_force": "gtc"
        }

        headers = {
            "APCA-API-KEY-ID": ALPACA_API_KEY,
            "APCA-API-SECRET-KEY": ALPACA_SECRET_KEY,
            "Content-Type": "application/json"
        }

        response = requests.post(ALPACA_ENDPOINT, json=order_details, headers=headers)
        
        if response.status_code == 200:
            return jsonify({"status": "success", "order": response.json()}), 200
        else:
            return jsonify({"status": "alpaca_error", "details": response.text}), response.status_code

    except Exception as e:
        return jsonify({"error": str(e)}), 500