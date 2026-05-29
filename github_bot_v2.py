import os
import time
import json
import requests
import numpy as np
from datetime import datetime
from pathlib import Path

# ==============================================================================
# CONFIGURATION
# ==============================================================================
# Tentukan lokasi file
TRADES_FILE_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), "trades.json")

CONFIG = {
    "MODE": os.getenv("TRADING_MODE", "PAPER"),
    "COINS": ["BTC", "ETH", "BNB"],
    "TIMEFRAME": "15m",
    "MARGIN_PER_TRADE": float(os.getenv("MARGIN_PER_TRADE", "2.0")),
    "LEVERAGE": int(os.getenv("LEVERAGE", "10")),
    "API_URL": "https://api.hyperliquid.xyz/info",
    "TRADES_FILE": TRADES_FILE_PATH,
}

# ==============================================================================
# HELPER FUNCTIONS
# ==============================================================================

def load_trades():
    """Load existing trades from JSON file"""
    trades_file = CONFIG["TRADES_FILE"]
    if Path(trades_file).exists():
        try:
            with open(trades_file, "r") as f:
                return json.load(f)
        except:
            pass
    return {"trades": [], "summary": {"total_trades": 0, "total_profit": 0, "total_loss": 0}}

def save_trades(data):
    """Save trades to JSON file"""
    trades_file = CONFIG["TRADES_FILE"]
    try:
        with open(trades_file, "w") as f:
            json.dump(data, f, indent=2)
    except Exception as e:
        print(f"Error saving trades: {e}")

def log_trade(coin, signal, entry_price, tp, sl, margin):
    """Log a trade to the JSON file"""
    trades_data = load_trades()
    trade = {
        "timestamp": datetime.now().isoformat(),
        "coin": coin,
        "signal": signal,
        "entry_price": entry_price,
        "tp": tp,
        "sl": sl,
        "margin": margin,
        "status": "OPEN"
    }
    trades_data["trades"].append(trade)
    trades_data["summary"]["total_trades"] += 1
    save_trades(trades_data)
    return trade

# ==============================================================================
# STRATEGY LOGIC
# ==============================================================================

def get_data(coin, interval="15m"):
    try:
        end_time = int(time.time() * 1000)
        start_time = end_time - (50 * 15 * 60 * 1000)
        resp = requests.post(CONFIG["API_URL"], json={
            "type": "candleSnapshot",
            "req": {"coin": coin, "interval": interval, "startTime": start_time, "endTime": end_time}
        })
        candles = resp.json()
        resp_trades = requests.post(CONFIG["API_URL"], json={"type": "recentTrades", "coin": coin})
        trades = resp_trades.json()
        return candles, trades
    except Exception as e:
        print(f"Error fetching data for {coin}: {e}")
        return None, None

def calculate_indicators(candles):
    closes = np.array([float(c['c']) for c in candles])
    deltas = np.diff(closes)
    gains = np.where(deltas > 0, deltas, 0)
    losses = np.where(deltas < 0, -deltas, 0)
    avg_gain = np.mean(gains[-14:])
    avg_loss = np.mean(losses[-14:])
    rsi = 100 - (100 / (1 + (avg_gain / avg_loss))) if avg_loss != 0 else 100
    
    def ema(data, p):
        alpha = 2 / (p + 1)
        res = [data[0]]
        for x in data[1:]:
            res.append(alpha * x + (1 - alpha) * res[-1])
        return np.array(res)
    
    ema12 = ema(closes, 12)
    ema26 = ema(closes, 26)
    macd = ema12 - ema26
    signal = ema(macd, 9)
    hist = macd[-1] - signal[-1]
    return rsi, hist, closes[-1]

def analyze_signal(coin):
    candles, trades = get_data(coin, CONFIG["TIMEFRAME"])
    if not candles: return "WNS", 0, 0
    
    buys = sum(float(t['sz']) for t in trades if t['side'] == 'B')
    sells = sum(float(t['sz']) for t in trades if t['side'] == 'S')
    cvd_score = 2 if buys > sells * 1.5 else -2 if sells > buys * 1.5 else 0
    
    rsi, macd_hist, current_price = calculate_indicators(candles)
    tech_score = 0
    if rsi < 35: tech_score += 1
    if rsi > 65: tech_score -= 1
    if macd_hist > 0: tech_score += 1
    if macd_hist < 0: tech_score -= 1
    
    total_score = cvd_score + tech_score
    if total_score >= 2: return "LONG", total_score, current_price
    if total_score <= -2: return "SHORT", total_score, current_price
    return "WNS", total_score, current_price

# ==============================================================================
# MAIN EXECUTION
# ==============================================================================

def main():
    print(f"[{datetime.now()}] GitHub Action DeFi91 Bot Run (Mode: {CONFIG['MODE']})")
    print("-" * 70)
    
    for coin in CONFIG["COINS"]:
        signal, score, current_price = analyze_signal(coin)
        print(f"{coin}: {signal} (Score: {score}, Price: ${current_price:.2f})")
        
        if signal != "WNS":
            tp = current_price * (1 + 0.015) if signal == "LONG" else current_price * (1 - 0.015)
            sl = current_price * (1 - 0.01) if signal == "LONG" else current_price * (1 + 0.01)
            
            trade = log_trade(coin, signal, current_price, tp, sl, CONFIG["MARGIN_PER_TRADE"])
            print(f"   >>> Trade logged: {signal} {coin} @ ${current_price:.2f}")
            print(f"       TP: ${tp:.2f} | SL: ${sl:.2f}")
    
    print("-" * 70)
    print("Bot execution completed. Trades saved to trades.json")

if __name__ == "__main__":
    print(f"Trades file location: {CONFIG['TRADES_FILE']}")
    main()
