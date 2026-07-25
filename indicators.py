"""
Indikator teknikal untuk DeFi91 Trading Bot.

Modul ini menggantikan implementasi lama yang rumusnya keliru:

  - MACD lama memakai SMA (bukan EMA) dan signal line-nya dihitung dengan
    `mean(9 terakhir) - mean(18 terakhir)` yang bukan MACD sama sekali.
  - RSI lama memakai rata-rata sederhana, bukan Wilder smoothing, sehingga
    nilainya beda cukup jauh dengan RSI di TradingView.
  - ADX lama mengembalikan DX mentah (1 periode) tanpa smoothing, jadi
    nilainya sangat berisik dan sering salah melabeli regime pasar.

Semua fungsi di sini murni (pure) dan tidak menyentuh jaringan, supaya bisa
diuji dengan cepat lewat tests/test_indicators.py.
"""

import numpy as np


def ema(values, period):
    """
    Exponential Moving Average.

    Return: list sepanjang `values`. Elemen sebelum periode terpenuhi diisi
    dengan SMA berjalan sebagai seed (praktik standar di library TA).
    """
    values = [float(v) for v in values]
    if not values:
        return []
    if period <= 1:
        return list(values)

    alpha = 2.0 / (period + 1.0)
    out = []
    running = None
    for i, v in enumerate(values):
        if i < period - 1:
            running = float(np.mean(values[: i + 1]))
        elif i == period - 1:
            running = float(np.mean(values[:period]))
        else:
            running = alpha * v + (1 - alpha) * running
        out.append(running)
    return out


def rma(values, period):
    """
    Wilder's smoothing (a.k.a. RMA / SMMA). Dipakai oleh RSI, ATR, dan ADX.
    """
    values = [float(v) for v in values]
    if not values or period <= 0:
        return []
    if len(values) < period:
        return [float(np.mean(values))] * len(values)

    out = [None] * len(values)
    seed = float(np.mean(values[:period]))
    out[period - 1] = seed
    prev = seed
    for i in range(period, len(values)):
        prev = (prev * (period - 1) + values[i]) / period
        out[i] = prev
    # Isi bagian awal dengan seed supaya panjang list konsisten.
    for i in range(period - 1):
        out[i] = seed
    return out


def calculate_rsi(prices, period=14):
    """
    RSI dengan Wilder smoothing (sama dengan default TradingView).

    Return float 0-100. Kalau data kurang, kembalikan 50.0 (netral).
    """
    prices = [float(p) for p in prices]
    if len(prices) < period + 1:
        return 50.0

    deltas = np.diff(prices)
    gains = np.where(deltas > 0, deltas, 0.0)
    losses = np.where(deltas < 0, -deltas, 0.0)

    avg_gain = rma(list(gains), period)[-1]
    avg_loss = rma(list(losses), period)[-1]

    if avg_loss == 0:
        return 100.0 if avg_gain > 0 else 50.0

    rs = avg_gain / avg_loss
    return 100.0 - (100.0 / (1.0 + rs))


def calculate_macd(prices, fast=12, slow=26, signal=9):
    """
    MACD standar: EMA(fast) - EMA(slow), signal = EMA(signal) dari MACD line.

    Return: (macd_line, signal_line, histogram). Semua 0 kalau data kurang.
    """
    prices = [float(p) for p in prices]
    if len(prices) < slow:
        return 0.0, 0.0, 0.0

    ema_fast = ema(prices, fast)
    ema_slow = ema(prices, slow)
    macd_series = [f - s for f, s in zip(ema_fast, ema_slow)]

    # Signal line dihitung dari bagian MACD yang sudah valid saja.
    valid = macd_series[slow - 1:]
    if len(valid) < 2:
        return macd_series[-1], macd_series[-1], 0.0

    signal_series = ema(valid, signal)
    macd_line = macd_series[-1]
    signal_line = signal_series[-1]
    return macd_line, signal_line, macd_line - signal_line


def calculate_atr(highs, lows, closes, period=14):
    """
    Average True Range absolut (bukan persen).
    """
    highs = [float(h) for h in highs]
    lows = [float(l) for l in lows]
    closes = [float(c) for c in closes]

    n = min(len(highs), len(lows), len(closes))
    if n < period + 1:
        return 0.0

    tr = []
    for i in range(1, n):
        tr.append(
            max(
                highs[i] - lows[i],
                abs(highs[i] - closes[i - 1]),
                abs(lows[i] - closes[i - 1]),
            )
        )
    smoothed = rma(tr, period)
    return float(smoothed[-1]) if smoothed else 0.0


def calculate_atr_percent(highs, lows, closes, period=14):
    """ATR dinyatakan sebagai persen dari harga terakhir."""
    atr = calculate_atr(highs, lows, closes, period)
    last = float(closes[-1]) if closes else 0.0
    return (atr / last * 100.0) if last > 0 else 0.0


def calculate_adx(highs, lows, closes, period=14):
    """
    ADX (Average Directional Index) versi Wilder yang benar:
      1. Hitung +DM / -DM dan True Range
      2. Smoothing ketiganya dengan RMA(period)
      3. +DI / -DI -> DX
      4. ADX = RMA(DX, period)

    Return: (adx, di_plus, di_minus). Kalau data kurang -> (0, 0, 0).
    """
    highs = [float(h) for h in highs]
    lows = [float(l) for l in lows]
    closes = [float(c) for c in closes]

    n = min(len(highs), len(lows), len(closes))
    if n < period * 2 + 1:
        return 0.0, 0.0, 0.0

    plus_dm, minus_dm, tr = [], [], []
    for i in range(1, n):
        up_move = highs[i] - highs[i - 1]
        down_move = lows[i - 1] - lows[i]

        plus_dm.append(up_move if (up_move > down_move and up_move > 0) else 0.0)
        minus_dm.append(down_move if (down_move > up_move and down_move > 0) else 0.0)
        tr.append(
            max(
                highs[i] - lows[i],
                abs(highs[i] - closes[i - 1]),
                abs(lows[i] - closes[i - 1]),
            )
        )

    tr_s = rma(tr, period)
    plus_s = rma(plus_dm, period)
    minus_s = rma(minus_dm, period)

    dx_series = []
    for i in range(period - 1, len(tr_s)):
        if tr_s[i] == 0:
            continue
        di_p = 100.0 * plus_s[i] / tr_s[i]
        di_m = 100.0 * minus_s[i] / tr_s[i]
        denom = di_p + di_m
        if denom == 0:
            continue
        dx_series.append(100.0 * abs(di_p - di_m) / denom)

    if len(dx_series) < period:
        return 0.0, 0.0, 0.0

    adx = float(rma(dx_series, period)[-1])
    di_plus = 100.0 * plus_s[-1] / tr_s[-1] if tr_s[-1] else 0.0
    di_minus = 100.0 * minus_s[-1] / tr_s[-1] if tr_s[-1] else 0.0
    return adx, di_plus, di_minus


def calculate_bollinger_band_width(closes, period=20, std_dev=2):
    """
    Lebar Bollinger Band dalam persen dari SMA.
    Sempit = konsolidasi (chopsaw), lebar = volatil (trending).
    """
    closes = [float(c) for c in closes]
    if len(closes) < period:
        return 0.0

    sma = float(np.mean(closes[-period:]))
    std = float(np.std(closes[-period:]))
    if sma <= 0:
        return 0.0
    return ((sma + std_dev * std) - (sma - std_dev * std)) / sma * 100.0


def swing_levels(highs, lows, lookback=20):
    """
    Support/resistance sederhana dari swing high/low.

    Versi lama memakai `max(closes)` / `min(closes)` yang mengabaikan wick,
    padahal justru wick yang menandai level likuiditas.
    """
    highs = [float(h) for h in highs]
    lows = [float(l) for l in lows]
    if not highs or not lows:
        return 0.0, 0.0
    window = min(lookback, len(highs), len(lows))
    return max(highs[-window:]), min(lows[-window:])
