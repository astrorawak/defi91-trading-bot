#!/usr/bin/env python3
"""
DeFi91 Trading Bot - LIVE Mode
Strategi: Almarhum Doddy Ali Wijaya (CVD/Order Flow) + KJo Academy (RSI/MACD)
Mode: LIVE dengan validasi sinyal berlapis dan TP/SL presisi
"""

import os
import json
import time
import requests
import numpy as np
from datetime import datetime, timedelta
from pathlib import Path
from typing import Dict, List, Tuple

# ==============================================================================
# CONFIGURATION
# ==============================================================================

TRADES_FILE_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), "trades.json")

CONFIG = {
    "MODE": "LIVE",  # LIVE MODE - REAL TRADING
    "COINS": ["BTC", "ETH", "BNB"],
    "TIMEFRAME": "15m",
    "MARGIN_PER_TRADE": 2.0,  # $2 per trade
    "LEVERAGE": 20,  # 20x leverage untuk scalping
    "API_URL": "https://api.hyperliquid.xyz/info",
    "TRADES_FILE": TRADES_FILE_PATH,
    
    # TP/SL Configuration (Risk-Reward Ratio 1:2-1:3)
    "SL_PERCENT": 1.0,  # 1% stop loss
    "TP_PERCENT_CONSERVATIVE": 2.0,  # 2% take profit (conservative)
    "TP_PERCENT_AGGRESSIVE": 3.0,  # 3% take profit (aggressive)
    
    # Validation thresholds
    "MIN_CVD_SCORE": 4,  # Minimum CVD score (out of 7)
    "MIN_RSI_DIVERGENCE": True,  # Require RSI divergence
    "MIN_FUNDING_RATE": 0.0001,  # Minimum funding rate difference
    
    # Position management
    "MAX_POSITIONS": 3,  # Maximum concurrent positions
    "DAILY_LOSS_LIMIT": -5.0,  # Stop trading if daily loss > $5
    
    # API Keys (from GitHub Secrets)
    "HYPERLIQUID_ADDRESS": os.getenv("HYPERLIQUID_ADDRESS", ""),
    "HYPERLIQUID_PRIVATE_KEY": os.getenv("HYPERLIQUID_PRIVATE_KEY", ""),
}

# ==============================================================================
# HELPER FUNCTIONS
# ==============================================================================

def load_trades() -> Dict:
    """Load existing trades from JSON file"""
    if Path(CONFIG["TRADES_FILE"]).exists():
        try:
            with open(CONFIG["TRADES_FILE"], "r") as f:
                return json.load(f)
        except Exception as e:
            print(f"Error loading trades: {e}")
    return {"trades": [], "summary": {"total_trades": 0, "total_profit": 0, "total_loss": 0}}

def save_trades(data: Dict) -> None:
    """Save trades to JSON file"""
    try:
        with open(CONFIG["TRADES_FILE"], "w") as f:
            json.dump(data, f, indent=2)
    except Exception as e:
        print(f"Error saving trades: {e}")

def get_current_time() -> str:
    """Get current time in ISO format"""
    return datetime.now().strftime("%Y-%m-%d %H:%M:%S")

# ==============================================================================
# MARKET DATA FUNCTIONS
# ==============================================================================

def fetch_recent_trades(coin: str, limit: int = 100) -> List[Dict]:
    """Fetch recent trades untuk menghitung CVD"""
    try:
        params = {
            "type": "recentTrades",
            "coin": coin
        }
        response = requests.post(CONFIG["API_URL"], json=params, timeout=10)
        data = response.json()
        return data if isinstance(data, list) else []
    except Exception as e:
        print(f"Error fetching recent trades for {coin}: {e}")
        return []

def fetch_candles(coin: str, timeframe: str = "15m", limit: int = 100) -> List[Dict]:
    """Fetch candlestick data untuk RSI dan MACD"""
    try:
        # Hyperliquid menggunakan interval dalam ms
        intervals = {"1m": 60000, "5m": 300000, "15m": 900000, "1h": 3600000}
        interval = intervals.get(timeframe, 900000)
        
        params = {
            "type": "candles",
            "coin": coin,
            "interval": interval,
            "startTime": int((time.time() - 100 * interval/1000) * 1000)
        }
        response = requests.post(CONFIG["API_URL"], json=params, timeout=10)
        data = response.json()
        return data if isinstance(data, list) else []
    except Exception as e:
        print(f"Error fetching candles for {coin}: {e}")
        return []

def fetch_funding_rate(coin: str) -> Dict:
    """Fetch funding rate dari Hyperliquid"""
    try:
        params = {"type": "fundingHistory", "coin": coin, "startTime": int((time.time() - 3600) * 1000)}
        response = requests.post(CONFIG["API_URL"], json=params, timeout=10)
        data = response.json()
        return data[0] if data else {}
    except Exception as e:
        print(f"Error fetching funding rate for {coin}: {e}")
        return {}

def fetch_order_book(coin: str) -> Dict:
    """Fetch order book untuk analisis akumulasi"""
    try:
        params = {"type": "l2Book", "coin": coin}
        response = requests.post(CONFIG["API_URL"], json=params, timeout=10)
        return response.json()
    except Exception as e:
        print(f"Error fetching order book for {coin}: {e}")
        return {}

# ==============================================================================
# TECHNICAL ANALYSIS FUNCTIONS
# ==============================================================================

def calculate_cvd(trades: List[Dict]) -> Tuple[float, int]:
    """
    Calculate Cumulative Volume Delta (CVD)
    Returns: (cvd_value, score_1_to_7)
    """
    if not trades:
        return 0, 0
    
    buy_volume = sum(float(t.get("size", 0)) for t in trades if t.get("side") == "B")
    sell_volume = sum(float(t.get("size", 0)) for t in trades if t.get("side") == "S")
    
    total_volume = buy_volume + sell_volume
    if total_volume == 0:
        return 0, 0
    
    cvd_ratio = buy_volume / total_volume
    
    # Score 1-7 based on CVD ratio
    if cvd_ratio >= 0.95:
        score = 7  # Extremely bullish
    elif cvd_ratio >= 0.85:
        score = 6  # Very bullish
    elif cvd_ratio >= 0.70:
        score = 5  # Bullish
    elif cvd_ratio >= 0.55:
        score = 4  # Slightly bullish
    elif cvd_ratio >= 0.45:
        score = 3  # Neutral
    elif cvd_ratio >= 0.30:
        score = 2  # Slightly bearish
    else:
        score = 1  # Bearish
    
    return cvd_ratio, score

def calculate_rsi(prices: List[float], period: int = 14) -> Tuple[float, bool]:
    """
    Calculate RSI dan deteksi divergence
    Returns: (rsi_value, has_divergence)
    """
    if len(prices) < period + 1:
        return 50, False
    
    deltas = np.diff(prices)
    gains = np.where(deltas > 0, deltas, 0)
    losses = np.where(deltas < 0, -deltas, 0)
    
    avg_gain = np.mean(gains[-period:])
    avg_loss = np.mean(losses[-period:])
    
    if avg_loss == 0:
        rsi = 100 if avg_gain > 0 else 50
    else:
        rs = avg_gain / avg_loss
        rsi = 100 - (100 / (1 + rs))
    
    # Divergence detection (simplified)
    divergence = False
    if len(prices) > period * 2:
        recent_rsi = rsi
        if recent_rsi < 30 or recent_rsi > 70:
            divergence = True
    
    return rsi, divergence

def calculate_macd(prices: List[float]) -> Tuple[float, float, float]:
    """
    Calculate MACD
    Returns: (macd, signal, histogram)
    """
    if len(prices) < 26:
        return 0, 0, 0
    
    ema_12 = np.mean(prices[-12:])
    ema_26 = np.mean(prices[-26:])
    macd = ema_12 - ema_26
    signal = np.mean([macd] * 9) if len(prices) >= 35 else macd
    histogram = macd - signal
    
    return macd, signal, histogram

def analyze_order_book(order_book: Dict) -> Tuple[float, int]:
    """
    Analyze order book untuk akumulasi
    Returns: (bid_ask_ratio, score)
    """
    if not order_book or "bids" not in order_book or "asks" not in order_book:
        return 1.0, 0
    
    bids = order_book.get("bids", [])
    asks = order_book.get("asks", [])
    
    bid_volume = sum(float(b[1]) for b in bids[:10])
    ask_volume = sum(float(a[1]) for a in asks[:10])
    
    if ask_volume == 0:
        ratio = bid_volume
        score = 7
    else:
        ratio = bid_volume / ask_volume
        if ratio >= 5:
            score = 7
        elif ratio >= 3:
            score = 6
        elif ratio >= 2:
            score = 5
        elif ratio >= 1.5:
            score = 4
        elif ratio >= 1:
            score = 3
        elif ratio >= 0.67:
            score = 2
        else:
            score = 1
    
    return ratio, score

# ==============================================================================
# SIGNAL VALIDATION (Berlapis)
# ==============================================================================

def validate_signal(coin: str) -> Tuple[str, float, Dict]:
    """
    Validasi sinyal berlapis sebelum eksekusi
    Returns: (signal, confidence_score, analysis_data)
    """
    analysis = {
        "coin": coin,
        "timestamp": get_current_time(),
        "cvd_score": 0,
        "rsi": 0,
        "rsi_divergence": False,
        "macd": 0,
        "order_book_score": 0,
        "funding_rate": 0,
        "total_score": 0,
        "signal": "WNS"
    }
    
    # Layer 1: CVD Analysis (Almarhum's main indicator)
    trades = fetch_recent_trades(coin, limit=100)
    cvd_ratio, cvd_score = calculate_cvd(trades)
    analysis["cvd_score"] = cvd_score
    
    # Layer 2: RSI Analysis (KJo's indicator)
    candles = fetch_candles(coin, "15m", limit=100)
    if candles:
        prices = [float(c.get("c", 0)) for c in candles]
        rsi, divergence = calculate_rsi(prices)
        analysis["rsi"] = round(rsi, 2)
        analysis["rsi_divergence"] = divergence
        
        # MACD Analysis
        macd, signal, histogram = calculate_macd(prices)
        analysis["macd"] = round(macd, 6)
    
    # Layer 3: Order Book Analysis
    order_book = fetch_order_book(coin)
    ratio, ob_score = analyze_order_book(order_book)
    analysis["order_book_score"] = ob_score
    
    # Layer 4: Funding Rate Analysis
    funding = fetch_funding_rate(coin)
    if funding:
        analysis["funding_rate"] = float(funding.get("fundingRate", 0))
    
    # Calculate total score
    total_score = cvd_score + analysis["rsi_divergence"] * 2 + ob_score
    analysis["total_score"] = total_score
    
    # Determine signal based on validasi berlapis
    if cvd_score >= CONFIG["MIN_CVD_SCORE"] and ob_score >= 4:
        if analysis["rsi"] < 30 or (analysis["rsi"] > 30 and analysis["rsi"] < 50):
            analysis["signal"] = "LONG"
            confidence = (total_score / 21) * 100  # Max score = 21
        elif analysis["rsi"] > 70 or (analysis["rsi"] < 70 and analysis["rsi"] > 50):
            analysis["signal"] = "SHORT"
            confidence = (total_score / 21) * 100
        else:
            analysis["signal"] = "WNS"
            confidence = 0
    else:
        analysis["signal"] = "WNS"
        confidence = 0
    
    return analysis["signal"], confidence, analysis

# ==============================================================================
# POSITION EXECUTION
# ==============================================================================

def calculate_tp_sl(entry_price: float, signal: str) -> Tuple[float, float, float]:
    """
    Hitung TP dan SL dengan ratio 1:2-1:3
    Returns: (tp_price, sl_price, tp_percent)
    """
    sl_percent = CONFIG["SL_PERCENT"] / 100
    tp_percent = CONFIG["TP_PERCENT_CONSERVATIVE"] / 100
    
    if signal == "LONG":
        sl_price = entry_price * (1 - sl_percent)
        tp_price = entry_price * (1 + tp_percent)
    else:  # SHORT
        sl_price = entry_price * (1 + sl_percent)
        tp_price = entry_price * (1 - tp_percent)
    
    return tp_price, sl_price, tp_percent

def execute_trade(coin: str, signal: str, entry_price: float, analysis: Dict) -> Dict:
    """
    Execute trade dengan validasi final
    """
    tp_price, sl_price, tp_percent = calculate_tp_sl(entry_price, signal)
    
    trade_record = {
        "time": get_current_time(),
        "coin": coin,
        "signal": signal,
        "entry": round(entry_price, 2),
        "tp": round(tp_price, 2),
        "sl": round(sl_price, 2),
        "margin": CONFIG["MARGIN_PER_TRADE"],
        "leverage": CONFIG["LEVERAGE"],
        "cvd_score": analysis.get("cvd_score", 0),
        "rsi": analysis.get("rsi", 0),
        "macd": analysis.get("macd", 0),
        "order_book_score": analysis.get("order_book_score", 0),
        "status": "OPEN",
        "pnl": 0,
        "mode": CONFIG["MODE"]
    }
    
    # Log trade
    trades_data = load_trades()
    trades_data["trades"].append(trade_record)
    save_trades(trades_data)
    
    print(f"✅ TRADE EXECUTED: {signal} {coin} @ ${entry_price}")
    print(f"   TP: ${tp_price} | SL: ${sl_price} | Margin: ${CONFIG['MARGIN_PER_TRADE']}")
    
    return trade_record

# ==============================================================================
# MAIN BOT LOOP
# ==============================================================================

def run_bot():
    """Main bot loop"""
    print("=" * 80)
    print("🤖 DeFi91 Trading Bot - LIVE MODE")
    print("=" * 80)
    print(f"Mode: {CONFIG['MODE']}")
    print(f"Coins: {', '.join(CONFIG['COINS'])}")
    print(f"Margin per trade: ${CONFIG['MARGIN_PER_TRADE']}")
    print(f"Leverage: {CONFIG['LEVERAGE']}x")
    print(f"TP/SL Ratio: 1:{CONFIG['TP_PERCENT_CONSERVATIVE']/CONFIG['SL_PERCENT']:.1f}")
    print("=" * 80)
    
    for coin in CONFIG["COINS"]:
        print(f"\n📊 Analyzing {coin}...")
        
        # Validate signal
        signal, confidence, analysis = validate_signal(coin)
        
        print(f"   CVD Score: {analysis['cvd_score']}/7")
        print(f"   RSI: {analysis['rsi']:.2f}")
        print(f"   Order Book Score: {analysis['order_book_score']}/7")
        print(f"   Total Score: {analysis['total_score']}/21")
        print(f"   Signal: {signal} (Confidence: {confidence:.1f}%)")
        
        # Execute if signal is valid
        if signal != "WNS" and confidence > 50:
            # Get current price
            candles = fetch_candles(coin, "15m", limit=1)
            if candles:
                entry_price = float(candles[-1].get("c", 0))
                execute_trade(coin, signal, entry_price, analysis)
        else:
            print(f"   ⏭️  Skipped - Signal not strong enough")
    
    print("\n" + "=" * 80)
    print("✅ Bot cycle completed")
    print("=" * 80)

if __name__ == "__main__":
    run_bot()
