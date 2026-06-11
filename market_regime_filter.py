"""
Market Regime Filter untuk DeFi91 Trading Bot
Mendeteksi kondisi pasar: TRENDING, NEUTRAL, atau CHOPSAW
Menggunakan: ATR (volatilitas), ADX (kekuatan tren), Bollinger Band Width
"""

import numpy as np
import requests
import time

INFO_URL = 'https://api.hyperliquid.xyz/info'

def get_candles(coin, interval="15m", lookback=100):
    """Get candle data from Hyperliquid"""
    end_time = int(time.time() * 1000)
    interval_ms = {"1m": 60000, "5m": 300000, "15m": 900000, "1h": 3600000}
    ms = interval_ms.get(interval, 900000)
    start_time = end_time - (lookback * ms)
    
    payload = {
        "type": "candleSnapshot",
        "req": {
            "coin": coin,
            "interval": interval,
            "startTime": start_time,
            "endTime": end_time
        }
    }
    
    try:
        resp = requests.post(INFO_URL, json=payload, timeout=10)
        data = resp.json()
        if not data:
            return [], [], [], []
        
        closes = [float(c["c"]) for c in data]
        highs = [float(c["h"]) for c in data]
        lows = [float(c["l"]) for c in data]
        volumes = [float(c["v"]) for c in data]
        return closes, highs, lows, volumes
    except:
        return [], [], [], []

def calculate_atr(highs, lows, closes, period=14):
    """
    Calculate Average True Range (ATR)
    Mengukur volatilitas pasar
    """
    if len(closes) < period + 1:
        return 0
    
    tr_values = []
    for i in range(1, len(closes)):
        tr = max(
            highs[i] - lows[i],
            abs(highs[i] - closes[i-1]),
            abs(lows[i] - closes[i-1])
        )
        tr_values.append(tr)
    
    atr = np.mean(tr_values[-period:])
    atr_percent = (atr / closes[-1]) * 100 if closes[-1] > 0 else 0
    return atr_percent

def calculate_adx(highs, lows, closes, period=14):
    """
    Calculate Average Directional Index (ADX)
    Mengukur kekuatan tren (0-100)
    > 25: Tren kuat
    20-25: Tren sedang
    < 20: Tren lemah / sideways
    """
    if len(closes) < period * 2:
        return 50  # Default neutral
    
    # Hitung DM+ dan DM-
    plus_dm = []
    minus_dm = []
    
    for i in range(1, len(closes)):
        up_move = highs[i] - highs[i-1]
        down_move = lows[i-1] - lows[i]
        
        if up_move > down_move and up_move > 0:
            plus_dm.append(up_move)
            minus_dm.append(0)
        elif down_move > up_move and down_move > 0:
            plus_dm.append(0)
            minus_dm.append(down_move)
        else:
            plus_dm.append(0)
            minus_dm.append(0)
    
    # Hitung True Range
    tr_values = []
    for i in range(1, len(closes)):
        tr = max(
            highs[i] - lows[i],
            abs(highs[i] - closes[i-1]),
            abs(lows[i] - closes[i-1])
        )
        tr_values.append(tr)
    
    # Hitung DI+ dan DI-
    sum_plus_dm = sum(plus_dm[-period:])
    sum_minus_dm = sum(minus_dm[-period:])
    sum_tr = sum(tr_values[-period:])
    
    if sum_tr == 0:
        return 50
    
    di_plus = (sum_plus_dm / sum_tr) * 100
    di_minus = (sum_minus_dm / sum_tr) * 100
    
    # Hitung DX
    di_sum = di_plus + di_minus
    if di_sum == 0:
        return 50
    
    dx = abs(di_plus - di_minus) / di_sum * 100
    
    # ADX adalah rata-rata DX (simplified)
    adx = dx
    return adx

def calculate_bollinger_band_width(closes, period=20, std_dev=2):
    """
    Calculate Bollinger Band Width
    Mengukur volatilitas dan konsolidasi
    Bandwidth sempit = pasar konsolidasi ketat (chopsaw)
    Bandwidth lebar = pasar volatile (trending)
    """
    if len(closes) < period:
        return 0
    
    sma = np.mean(closes[-period:])
    std = np.std(closes[-period:])
    
    upper_band = sma + (std_dev * std)
    lower_band = sma - (std_dev * std)
    
    bandwidth = ((upper_band - lower_band) / sma) * 100 if sma > 0 else 0
    return bandwidth

def detect_market_regime(coin, interval="15m"):
    """
    Deteksi kondisi pasar untuk sebuah koin
    Return: {
        "regime": "TRENDING" | "NEUTRAL" | "CHOPSAW",
        "color": "green" | "yellow" | "red",
        "atr_percent": float,
        "adx": float,
        "bb_width": float,
        "details": str
    }
    """
    closes, highs, lows, volumes = get_candles(coin, interval, 100)
    
    if len(closes) < 30:
        return {
            "regime": "UNKNOWN",
            "color": "gray",
            "atr_percent": 0,
            "adx": 0,
            "bb_width": 0,
            "details": "Insufficient data"
        }
    
    atr_pct = calculate_atr(highs, lows, closes, 14)
    adx = calculate_adx(highs, lows, closes, 14)
    bb_width = calculate_bollinger_band_width(closes, 20, 2)
    
    # Logika deteksi regime
    # TRENDING: ADX > 25 dan BB_WIDTH > 2
    # NEUTRAL: ADX 20-25 atau BB_WIDTH 1-2
    # CHOPSAW: ADX < 20 dan BB_WIDTH < 1
    
    if adx > 25 and bb_width > 2:
        regime = "TRENDING"
        color = "green"
        details = f"ADX={adx:.1f} (kuat), BB_Width={bb_width:.2f}% (lebar)"
    elif adx >= 20 and adx <= 25 and bb_width >= 1 and bb_width <= 2:
        regime = "NEUTRAL"
        color = "yellow"
        details = f"ADX={adx:.1f} (sedang), BB_Width={bb_width:.2f}% (sedang)"
    elif adx < 20 or bb_width < 1:
        regime = "CHOPSAW"
        color = "red"
        details = f"ADX={adx:.1f} (lemah), BB_Width={bb_width:.2f}% (sempit)"
    else:
        regime = "NEUTRAL"
        color = "yellow"
        details = f"ADX={adx:.1f}, BB_Width={bb_width:.2f}%"
    
    return {
        "regime": regime,
        "color": color,
        "atr_percent": atr_pct,
        "adx": adx,
        "bb_width": bb_width,
        "details": details
    }

def detect_market_regime_global(watchlist, interval="15m"):
    """
    Deteksi kondisi pasar global (rata-rata dari semua koin di watchlist)
    Return: {
        "global_regime": "TRENDING" | "NEUTRAL" | "CHOPSAW",
        "color": "green" | "yellow" | "red",
        "coins": {coin: regime_data}
    }
    """
    coin_regimes = {}
    trending_count = 0
    neutral_count = 0
    chopsaw_count = 0
    
    for coin in watchlist:
        regime_data = detect_market_regime(coin, interval)
        coin_regimes[coin] = regime_data
        
        if regime_data["regime"] == "TRENDING":
            trending_count += 1
        elif regime_data["regime"] == "NEUTRAL":
            neutral_count += 1
        elif regime_data["regime"] == "CHOPSAW":
            chopsaw_count += 1
        
        time.sleep(0.1)  # Rate limiting
    
    # Tentukan global regime berdasarkan mayoritas
    total = trending_count + neutral_count + chopsaw_count
    if total == 0:
        global_regime = "UNKNOWN"
        color = "gray"
    elif trending_count > total * 0.5:
        global_regime = "TRENDING"
        color = "green"
    elif chopsaw_count > total * 0.4:
        global_regime = "CHOPSAW"
        color = "red"
    else:
        global_regime = "NEUTRAL"
        color = "yellow"
    
    return {
        "global_regime": global_regime,
        "color": color,
        "trending_coins": trending_count,
        "neutral_coins": neutral_count,
        "chopsaw_coins": chopsaw_count,
        "coins": coin_regimes
    }

if __name__ == "__main__":
    # Test
    watchlist = ["BTC", "ETH", "SOL", "XRP"]
    result = detect_market_regime_global(watchlist)
    print(f"Global Regime: {result['global_regime']} ({result['color']})")
    for coin, data in result['coins'].items():
        print(f"  {coin}: {data['regime']} - {data['details']}")
