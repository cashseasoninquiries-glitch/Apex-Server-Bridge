from flask import Flask, request, jsonify
from datetime import datetime

# Initialize the Apex Engine Catcher's Mitt
app = Flask(__name__)

# This is the "Ear" of the engine. It listens for incoming POST signals at the /webhook URL.
@app.route('/webhook', methods=['POST'])
def catch_signal():
    try:
        # 1. Catch the incoming data (assuming it's formatted as JSON)
        signal_data = request.json
        timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        
        # 2. Extract the trading instructions
        ticker = signal_data.get('ticker', 'UNKNOWN')
        action = signal_data.get('action', 'UNKNOWN')
        
        # 3. Log the catch to your local terminal
        print(f"\n[{timestamp}] ⚡ SIGNAL RECEIVED!")
        print(f"Action: {action.upper()} | Ticker: {ticker}")
        print("--------------------------------------------------")
        
        # 4. Tell the sender (e.g., TradingView or your custom front-end) that we received it
        return jsonify({"status": "success", "message": "Signal caught by Apex Engine"}), 200

    except Exception as e:
        print(f"--- [ROUTER ERROR] Failed to parse signal: {e} ---")
        return jsonify({"status": "error", "message": "Bad signal format"}), 400

if __name__ == '__main__':
    print("==================================================")
    print(" APEX SERVER BRIDGE: ROUTER ONLINE ")
    print(" Listening for signals on port 5000...")
    print("==================================================")
    
    # Run the server locally on port 5000
    app.run(host='0.0.0.0', port=5000)