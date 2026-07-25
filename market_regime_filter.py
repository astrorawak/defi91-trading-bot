"""
Market Regime Filter untuk DeFi91 Trading Bot.

Mendeteksi kondisi pasar: TRENDING, NEUTRAL, atau CHOPSAW menggunakan
ATR (volatilitas), ADX (kekuatan tren), dan Bollinger Band Width.

Perbaikan dari versi lama:
  - ADX sekarang dihitung lewat indicators.calculate_adx() yang memakai
    Wilder smoothing. Versi lama mengembalikan DX satu periode tanpa
    smoothing sama sekali, jadi nilainya melompat-lompat dan regime pasar
    sering salah label.
  - Klasifikasi memakai sistem skor, bukan rantai if/elif dengan celah
    yang menjatuhkan banyak kasus ke "NEUTRAL" tanpa alasan jelas.
  - Kegagalan jaringan tidak lagi tertelan bare `except:`.
"""

import time

import requests

from indicators import (
    calculate_adx,
    calculate_atr_percent,
    calculate_bollinger_band_width,
)

INFO_URL = "https://api.hyperliquid.xyz/info"

# Ambang klasifikasi (bisa disesuaikan lewat pengujian ulang)
ADX_TRENDING = 25.0
ADX_WEAK = 20.0
BB_WIDE = 2.0
BB_NARROW = 1.0


def get_candles(coin, interval="15m", lookback=100):
    """Ambil candle dari Hyperliquid. Return (closes, highs, lows, volumes)."""
    end_time = int(time.time() * 1000)
    interval_ms = {"1m": 60000, "5m": 300000, "15m": 900000, "1h": 3600000}
    ms = interval_ms.get(interval, 900000)

    payload = {
        "type": "candleSnapshot",
        "req": {
            "coin": coin,
            "interval": interval,
            "startTime": end_time - (lookback * ms),
            "endTime": end_time,
        },
    }

    try:
        resp = requests.post(INFO_URL, json=payload, timeout=15)
        resp.raise_for_status()
        data = resp.json()
        if not isinstance(data, list) or not data:
            return [], [], [], []
        return (
            [float(c["c"]) for c in data],
            [float(c["h"]) for c in data],
            [float(c["l"]) for c in data],
            [float(c["v"]) for c in data],
        )
    except (requests.RequestException, ValueError, KeyError) as e:
        print(f"  [REGIME] Gagal ambil candle {coin}: {e}")
        return [], [], [], []


def classify(adx, bb_width):
    """
    Sistem skor sederhana: tiap indikator memberi suara trending atau chopsaw.

    Return (regime, color, details).
    """
    trend_votes = 0
    chop_votes = 0

    if adx >= ADX_TRENDING:
        trend_votes += 1
    elif adx < ADX_WEAK:
        chop_votes += 1

    if bb_width >= BB_WIDE:
        trend_votes += 1
    elif bb_width < BB_NARROW:
        chop_votes += 1

    details = f"ADX={adx:.1f}, BB_Width={bb_width:.2f}%"

    if trend_votes >= 2:
        return "TRENDING", "green", f"{details} (tren kuat)"
    if chop_votes >= 2:
        return "CHOPSAW", "red", f"{details} (konsolidasi ketat)"
    if chop_votes > trend_votes:
        return "CHOPSAW", "red", f"{details} (cenderung sideways)"
    return "NEUTRAL", "yellow", f"{details} (campuran)"


def detect_market_regime(coin, interval="15m"):
    """
    Deteksi kondisi pasar untuk satu coin.

    Return dict dengan kunci: regime, color, atr_percent, adx, di_plus,
    di_minus, bb_width, details.
    """
    closes, highs, lows, _ = get_candles(coin, interval, 100)

    if len(closes) < 40:
        return {
            "regime": "UNKNOWN",
            "color": "gray",
            "atr_percent": 0.0,
            "adx": 0.0,
            "di_plus": 0.0,
            "di_minus": 0.0,
            "bb_width": 0.0,
            "details": "Data tidak cukup",
        }

    atr_pct = calculate_atr_percent(highs, lows, closes, 14)
    adx, di_plus, di_minus = calculate_adx(highs, lows, closes, 14)
    bb_width = calculate_bollinger_band_width(closes, 20, 2)

    regime, color, details = classify(adx, bb_width)

    return {
        "regime": regime,
        "color": color,
        "atr_percent": round(atr_pct, 4),
        "adx": round(adx, 2),
        "di_plus": round(di_plus, 2),
        "di_minus": round(di_minus, 2),
        "bb_width": round(bb_width, 4),
        "details": details,
    }


def detect_market_regime_global(watchlist, interval="15m"):
    """
    Deteksi kondisi pasar global berdasarkan mayoritas coin di watchlist.
    """
    coin_regimes = {}
    trending = neutral = chopsaw = 0

    for coin in watchlist:
        data = detect_market_regime(coin, interval)
        coin_regimes[coin] = data

        if data["regime"] == "TRENDING":
            trending += 1
        elif data["regime"] == "NEUTRAL":
            neutral += 1
        elif data["regime"] == "CHOPSAW":
            chopsaw += 1

        time.sleep(0.1)  # jeda ringan supaya tidak kena rate limit

    total = trending + neutral + chopsaw
    if total == 0:
        global_regime, color = "UNKNOWN", "gray"
    elif trending > total * 0.5:
        global_regime, color = "TRENDING", "green"
    elif chopsaw > total * 0.4:
        global_regime, color = "CHOPSAW", "red"
    else:
        global_regime, color = "NEUTRAL", "yellow"

    return {
        "global_regime": global_regime,
        "color": color,
        "trending_coins": trending,
        "neutral_coins": neutral,
        "chopsaw_coins": chopsaw,
        "coins": coin_regimes,
        "updated_at": time.strftime("%Y-%m-%d %H:%M:%S", time.gmtime()) + " UTC",
    }


if __name__ == "__main__":
    result = detect_market_regime_global(["BTC", "ETH", "SOL", "XRP"])
    print(f"Global Regime: {result['global_regime']} ({result['color']})")
    for coin, data in result["coins"].items():
        print(f"  {coin}: {data['regime']} - {data['details']}")
