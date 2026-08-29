"""
DeFi91 Trading Bot - V3 (Hermes Strategic Revision)
Strategi: CVD/Order Flow (Almarhum Doddy Ali Wijaya) + Momentum (KJo Academy)
Exchange: Hyperliquid Perpetual Futures

Perbaikan utama dari Manus v2 (sesuai Proposal Strategis yang disetujui):
1.  CVD SEJATI  : cumulative volume delta + divergence delta-vs-harga (bukan rasio 200-trade).
2.  MACD SEJATI : EMA12-EMA26 + signal=EMA9(macd), bukan SMA tak-berkait.
3.  RSI Wilder  : Wilder smoothing, bukan simple-mean.
4.  Leverage redam: 5x (bukan 20x), maks 3 posisi paralel.
5.  SL/TP ATR   : 1.5x ATR stop / 2.5x ATR target (menyesuaikan volatilitas, bukan % fixed).
6.  Filter tren : hanya entry di regime TRENGING (ADX>=25), standby di CHOPSAW.
7.  Watchlist DNA almarhum: HANYA BTC, ETH, BNB. Microcap DIHAPUS.
8.  Timeframe   : analisis 1H (arah 4H) untuk konfirmasi tren, bukan 15m.
9.  KILL-SWITCH : rugi harian >= 4% equity -> stop trading sampai keesokan hari.

Mode: LIVE dengan TP/SL. Bot dijalankan oleh GitHub Actions (cron).
Gerbang keamanan: hanya jalankan & eksekusi SETELAH (a) strategi disetujui & (b) saldo diisi Pak Karman.
"""
import json
import time
import os
import numpy as np
import requests
from datetime import datetime, timezone, timedelta
from eth_account import Account
from hyperliquid.info import Info
from hyperliquid.exchange import Exchange
from hyperliquid.utils import constants
from market_regime_filter import detect_market_regime, calculate_atr, calculate_adx
from telegram_signals import send_trade_signal, send_close_signal

# ============================================================
# KONFIGURASI V3 (KONSERVATIF - MODAL KECIL)
# ============================================================
PRIVATE_KEY = os.getenv("HYPERLIQUID_PRIVATE_KEY", "")
MAIN_WALLET = "0x03562722fE32Ff3BaFE214be3F1828A9157eC23D"

# === SELF-EVALUATION OVERRIDE (dari defi91_eval.py) ===
# Hermes membaca rekomendasi otomatis: koin non-core yang rugi terus ditangguhkan.
_EVAL_OVERRIDE = os.path.expanduser("~/.defi91_watch_override.json")
try:
    _OV = json.load(open(_EVAL_OVERRIDE)) if os.path.exists(_EVAL_OVERRIDE) else {}
    _REMOVE = set(_OV.get("remove", []))
except Exception:
    _REMOVE = set()

# === WATCHLIST: 10 koin likuid (majors) — diperluas atas permintaan Pak Karman ===
# Tetap likuid & mapan (bukan microcap): hasil evaluasi otomatis (defi91_eval.py)
# menangguhkan koin yang rugi terus via _REMOVE. Core BTC/ETH/BNB tak pernah off.
WATCHLIST = [c for c in ["BTC", "ETH", "BNB", "SOL", "XRP", "DOGE", "ADA", "LINK", "AVAX", "LTC"]
             if c not in _REMOVE]
if _REMOVE:
    print(f"🔎 Self-eval: koin ditangguhkan hingga evaluasi membaik -> {sorted(_REMOVE)}")

# === RISK / SIZING (aman untuk $50-100) ===
MARGIN_PER_TRADE = 2.00      # $2 margin per trade (<=4% akun $50)
TARGET_LEVERAGE  = 5         # 5x leverage (bukan 20x - SL tidak mudah likuidasi)
MAX_OPEN_POSITIONS = 3       # maks 3 posisi paralel (agak agresif, tetap dibatasi)
MAX_COIN_MARGIN_PCT = 0.15   # maks margin per koin = 15% ekuitas akun (cegah akumulasi satu simbol menguras akun)

# === BIAYA (FEE) LANDASAN — riil dari API Hyperliquid wallet ini ===
# userCrossRate=0.00045 (taker), userAddRate=0.00015 (maker).
# Bot: entry IOC taker + exit TP/SL isMarket (taker) = 2 sisi taker per putaran.
FEE_TAKER = 0.00045          # 0.045% per sisi taker (dari userFees API)
FEE_MAKER = 0.00015          # 0.015% per sisi maker
ROUNDTRIP_FEE_PCT = (FEE_TAKER * 2) * 100   # 0.09%
FEE_BUFFER_X = 3.0           # target TP harus >= 3x biaya putaran agar untung bersih riil
MIN_TP_PCT_AFTER_FEE = ROUNDTRIP_FEE_PCT * FEE_BUFFER_X  # doorstap: TP >= 0.27%

# === EXIT BERBASIS VOLATILITAS (ATR) - bukan % fixed ===
SL_ATR_MULT = 1.5            # SL = 1.5x ATR (harga)
TP_ATR_MULT = 2.5            # TP = 2.5x ATR  -> potensial R:R ~ 1:1.67
TRAILING_ATR_MULT = 1.0      # trail start setelah profit >= 1.0x ATR

# === ENTRY GATE ===
ENTRY_THRESHOLD = int(os.getenv("HYPERLIQUID_ENTRY_THRESHOLD", "5"))  # skor; bisa dioverride via env utk tuning/pratinjau
ADX_MIN_TREND = 25           # hanya entry bila ADX >= 25 (regime TRENDING + arah)
HIGH_ADX_MIN   = 70          # bila ADX >= ini, tren kuat -> ikut arah tren (bukan lawan overbought)
HIGH_ADX_BIAS  = 4           # bobot tambahan ke skor searah tren kuat (ivar "ikut momentum")
ANALYSIS_TF = "1h"           # timeframe analisis (arah konfirmasi)
DIRECTION_TF = "4h"          # timeframe arah tren

# === KILL SWITCH (circuit breaker harian) ===
DAILY_LOSS_LIMIT_PCT = 4.0   # rugi hari ini >= 4% equity -> stop trading sampai besok
STATE_FILE = os.path.join(os.path.dirname(__file__), "v3_daily_state.json")

# Mode AMAN: bila 1, bot hanya menghitung & mencetak sinyal, TIDAK eksekusi order.
DRY_RUN = os.getenv("HYPERLIQUID_DRY_RUN", "0") == "1"

# Max leverage per koin (dari API Hyperliquid, dibatasi 5x di atas)
MAX_LEVERAGE_MAP = {"BTC": 40, "ETH": 25, "BNB": 10, "SOL": 20, "XRP": 10,
                    "DOGE": 10, "ADA": 10, "LINK": 15, "AVAX": 10, "LTC": 10}
SZ_DECIMALS = {"BTC": 5, "ETH": 4, "BNB": 3, "SOL": 3, "XRP": 1,
               "DOGE": 0, "ADA": 1, "LINK": 3, "AVAX": 2, "LTC": 2}

# ============================================================
# HELPER FUNCTIONS
# ============================================================
def get_wib_time():
    return datetime.now(timezone(timedelta(hours=7)))

def round_size(coin, size):
    return round(size, SZ_DECIMALS.get(coin, 4))

def format_price(price):
    if price >= 10000: return round(price, 0)
    elif price >= 1000: return round(price, 1)
    elif price >= 100:  return round(price, 1)
    elif price >= 10:   return round(price, 2)
    elif price >= 1:    return round(price, 3)
    elif price >= 0.1:  return round(price, 4)
    else:               return round(price, 5)

def ema(values, period):
    """Exponential Moving Average (sejati)."""
    if len(values) < period:
        return None
    alpha = 2.0 / (period + 1)
    e = float(values[0])
    for v in values:
        e = alpha * v + (1 - alpha) * e
    return e

def ema_series(values, period):
    if len(values) < period:
        return []
    alpha = 2.0 / (period + 1)
    out = []
    e = float(values[0])
    for v in values:
        e = alpha * v + (1 - alpha) * e
        out.append(e)
    return out

# ------------- RSI (Wilder smoothing - FIX) -------------
def calculate_rsi(prices, period=14):
    if len(prices) < period + 1:
        return 50.0
    deltas = np.diff(prices)
    gains = np.where(deltas > 0, deltas, 0.0)
    losses = np.where(deltas < 0, -deltas, 0.0)
    # Wilder smoothing: rata-rata perdana lalu EMA-likeness
    avg_gain = float(np.mean(gains[:period]))
    avg_loss = float(np.mean(losses[:period]))
    for i in range(period, len(gains)):
        avg_gain = (avg_gain * (period - 1) + gains[i]) / period
        avg_loss = (avg_loss * (period - 1) + losses[i]) / period
    if avg_loss == 0:
        return 100.0
    rs = avg_gain / avg_loss
    return 100 - (100 / (1 + rs))

# ------------- MACD sejati (FIX: EMA, signal dari macd) -------------
def calculate_macd(prices, fast=12, slow=26, signal=9):
    if len(prices) < slow + signal:
        return 0.0, 0.0
    ema_fast = ema_series(prices, fast)
    ema_slow = ema_series(prices, slow)
    start = len(prices) - slow
    macd_line = np.array(ema_fast[start:]) - np.array(ema_slow[start:])
    macd_list = macd_line.tolist()
    signal_line = ema(macd_list, signal)
    return macd_line[-1], signal_line

def get_candles(coin, interval="1h", lookback=120):
    """Return (closes, highs, lows, volumes)."""
    url = "https://api.hyperliquid.xyz/info"
    interval_ms = {"1m": 60000, "5m": 300000, "15m": 900000, "1h": 3600000, "4h": 14400000}
    ms = interval_ms.get(interval, 3600000)
    end_time = int(time.time() * 1000)
    start_time = end_time - (lookback * ms)
    payload = {"type": "candleSnapshot", "req": {"coin": coin, "interval": interval,
                                                  "startTime": start_time, "endTime": end_time}}
    try:
        resp = requests.post(url, json=payload, timeout=10)
        data = resp.json()
        closes = [float(c["c"]) for c in data]
        highs = [float(c["h"]) for c in data]
        lows = [float(c["l"]) for c in data]
        volumes = [float(c["v"]) for c in data]
        return closes, highs, lows, volumes
    except Exception:
        return [], [], [], []

def get_recent_trades(coin, limit=1000):
    url = "https://api.hyperliquid.xyz/info"
    payload = {"type": "recentTrades", "coin": coin}
    try:
        resp = requests.post(url, json=payload, timeout=10)
        trades = resp.json()
        return trades[-limit:] if len(trades) > limit else trades
    except Exception:
        return []

# ------------- CVD/Delta sejati + divergence (FIX) -------------
def calculate_cvd_signal(coin):
    """
    Delta/akumulasi dihitung dari Accumulation/Distribution (A/D) line pada candle
    1H, bukan dari recentTrades (yang HANYA berisi ~10 trade -> mustahil menangkap
    akumulasi). A/D = kumulasi tekanan beli-jual tiap candle:
        MFM = ((C-L) - (H-C)) / (H-L)   ; A/D = A/D_prev + MFM * volume
    Sinyal = divergensi kemiringan A/D vs pergerakan harga:
      - A/D naik, harga flat/turun  -> akumulasi whale  -> LONG
      - A/D turun, harga flat/naik  -> distribusi        -> SHORT
    Return: score (-3..+3), buy_ratio(0.5 dummy), details.
    """
    closes, highs, lows, volumes = get_candles(coin, ANALYSIS_TF, 60)
    if len(closes) < 30:
        return 0, 0.5, {"error": "insufficient candles"}

    # Bangun A/D line
    ad = 0.0
    ad_series = []
    for i in range(len(closes)):
        h, l, c, v = highs[i], lows[i], closes[i], volumes[i]
        mfm = ((c - l) - (h - c)) / (h - l) if (h - l) > 0 else 0.0
        ad += mfm * v
        ad_series.append(ad)

    # Bandingkan kemiringan A/D vs harga pada jendela terakhir (mis. 12 bar 1H = 12j)
    win = min(12, len(ad_series) // 2)
    ad_now = ad_series[-1] - ad_series[-1 - win]
    ad_prev = ad_series[-1 - win] - ad_series[-1 - 2 * win]
    if abs(ad_prev) < 1e-9:
        ad_prev = 1e-9
    ad_momentum = ad_now - ad_prev  # delta(kemiringan A/D)

    p_now = closes[-1]; p_prev_win = closes[-1 - win]
    price_change = (p_now - p_prev_win) / p_prev_win if p_prev_win else 0.0

    details = {
        "ad_momentum": round(ad_momentum, 2),
        "price_change_win": f"{price_change*100:.2f}%",
        "window": f"{win}h",
        "method": "AD divergence (candle)",
    }

    score = 0
    # LONG: A/D membaik (akumulasi) walau harga belum naik
    if ad_momentum > 0 and price_change <= 0.002:
        score += 3; details["signal"] = "WHALE ACCUMULATION (AD naik, harga flat) -> LONG"
    elif ad_momentum > 0 and price_change < 0.015:
        score += 2; details["signal"] = "AD BULLISH"
    elif ad_momentum > 0:
        score += 1; details["signal"] = "AD LEAN UP"
    # SHORT: A/D memburuk (distribusi) walau harga belum turun
    elif ad_momentum < 0 and price_change >= -0.002:
        score -= 3; details["signal"] = "WHALE DISTRIBUTION (AD turun, harga flat) -> SHORT"
    elif ad_momentum < 0 and price_change > -0.015:
        score -= 2; details["signal"] = "AD BEARISH"
    elif ad_momentum < 0:
        score -= 1; details["signal"] = "AD LEAN DOWN"
    else:
        details["signal"] = "AD NEUTRAL"

    details["score"] = score
    return score, 0.5, details

def calculate_atr_raw(highs, lows, closes, period=14):
    """ATR dalam satuan HARGA ($), bukan persen. Dipakai untuk jarak SL/TP."""
    if len(closes) < period + 1:
        return 0.0
    trs = []
    for i in range(1, len(closes)):
        trs.append(max(highs[i] - lows[i], abs(highs[i] - closes[i - 1]), abs(lows[i] - closes[i - 1])))
    return float(sum(trs[-period:]) / period)

def get_orderbook(coin):
    url = "https://api.hyperliquid.xyz/info"
    payload = {"type": "l2Book", "coin": coin}
    try:
        resp = requests.post(url, json=payload, timeout=10)
        data = resp.json()
        levels = data.get("levels", [[], []])
        bid = sum(float(b.get("sz", 0)) for b in levels[0][:10])
        ask = sum(float(a.get("sz", 0)) for a in levels[1][:10])
        return bid / ask if ask > 0 else 1.0
    except Exception:
        return 1.0

def get_funding_rate(coin):
    url = "https://api.hyperliquid.xyz/info"
    payload = {"type": "metaAndAssetCtxs"}
    try:
        resp = requests.post(url, json=payload, timeout=10)
        data = resp.json()
        for i, a in enumerate(data[0].get("universe", [])):
            if a.get("name") == coin:
                return float(data[1][i].get("funding", 0))
    except Exception:
        pass
    return 0

# ============================================================
# ANALISA ONCHAIN / ORDER FLOW (almarhum)
# ============================================================
def analyze_onchain(coin):
    score = 0
    details = {}

    # 1. CVD sejati + divergence (bobot tertinggi +/-3)
    cvd_score, buy_ratio, cvd_det = calculate_cvd_signal(coin)
    score += cvd_score
    details.update(cvd_det)

    # 2. Order Book ratio (bobot +/-2) - catatan: mudah di-spoof, bobot kecil
    ob = get_orderbook(coin)
    details["orderbook_ratio"] = f"{ob:.2f}"
    if ob > 2.0:
        score += 2; details["ob_signal"] = "BID HEAVY"
    elif ob > 1.3:
        score += 1; details["ob_signal"] = "BID LEAN"
    elif ob < 0.5:
        score -= 2; details["ob_signal"] = "ASK HEAVY"
    elif ob < 0.77:
        score -= 1; details["ob_signal"] = "ASK LEAN"
    else:
        details["ob_signal"] = "BALANCED"

    # 3. Funding (bobot +/-1) - kontrarian utama
    funding = get_funding_rate(coin)
    details["funding_rate"] = f"{funding*100:.4f}%"
    if funding > 0.01:
        score -= 1; details["funding_signal"] = "HIGH LONG (kontrarian SHORT)"
    elif funding < -0.01:
        score += 1; details["funding_signal"] = "HIGH SHORT (kontrarian LONG)"
    else:
        details["funding_signal"] = "NEUTRAL"

    details["onchain_score"] = score
    return score, details

# ============================================================
# ANALISA TEKNIKAL KJO ACADEMY (FIX: 1H, RSI Wilder, MACD EWS)
# ============================================================
def analyze_technical(coin):
    score = 0
    details = {}

    closes, highs, lows, _ = get_candles(coin, ANALYSIS_TF, 120)
    if len(closes) < 30:
        details["technical_error"] = "Insufficient data"
        return 0, details

    # ADX (bobot +/-2, tapi juga jadi GATE tren secara global di main loop)
    adx = calculate_adx(highs, lows, closes, 14)
    details["adx"] = f"{adx:.1f}"

    # 1. RSI Wilder (bobot +/-2)
    rsi = calculate_rsi(closes, 14)
    details["rsi"] = f"{rsi:.1f}"
    if rsi < 30:
        score += 2; details["rsi_signal"] = "OVERSOLD (Buy)"
    elif rsi < 40:
        score += 1; details["rsi_signal"] = "LOW (Lean Buy)"
    elif rsi > 70:
        score -= 2; details["rsi_signal"] = "OVERBOUGHT (Sell)"
    elif rsi > 60:
        score -= 1; details["rsi_signal"] = "HIGH (Lean Sell)"
    else:
        details["rsi_signal"] = "NEUTRAL"

    # 2. MACD sejati EMA12/26/9 (bobot +/-2)
    macd_line, signal_line = calculate_macd(closes)
    hist = macd_line - signal_line
    details["macd"] = f"{macd_line:.2f}"
    details["macd_hist"] = f"{hist:.2f}"
    if macd_line > 0 and hist > 0:
        score += 2; details["macd_signal"] = "BULLISH (+ hist)"
    elif macd_line > 0:
        score += 1; details["macd_signal"] = "BULLISH"
    elif macd_line < 0 and hist < 0:
        score -= 2; details["macd_signal"] = "BEARISH (- hist)"
    elif macd_line < 0:
        score -= 1; details["macd_signal"] = "BEARISH"
    else:
        details["macd_signal"] = "NEUTRAL"

    # 3. Posisi harga dalam rentang (Support/Resistance, bobot +/-1)
    current_price = closes[-1]
    recent_high = max(closes[-30:]); recent_low = min(closes[-30:])
    rng = recent_high - recent_low
    if rng > 0:
        pos = (current_price - recent_low) / rng
        details["price_position"] = f"{pos*100:.0f}%"
        if pos < 0.2:
            score += 1; details["sr_signal"] = "NEAR SUPPORT (Buy)"
        elif pos > 0.8:
            score -= 1; details["sr_signal"] = "NEAR RESISTANCE (Sell)"
        else:
            details["sr_signal"] = "MID RANGE"

    details["technical_score"] = score
    return score, details

def ema_calc(values, period):
    """EMA sederhana (seed = SMA awal)."""
    if not values:
        return []
    k = 2 / (period + 1)
    ema = [values[0]]
    for v in values[1:]:
        ema.append(v * k + ema[-1] * (1 - k))
    return ema

def trend_direction(coin, tf="4h"):
    """Arah tren makro dari perbandingan EMA cepat (20) vs lambat (50).
    Return +1 (uptrend) / -1 (downtrend) / 0 (sideways).
    Dipakai utk bias "ikuti momentum" saat ADX ekstrem."""
    closes, _, _, _ = get_candles(coin, tf, 100)
    if len(closes) < 55:
        return 0
    ema_fast = ema_calc(closes, 20)[-1]
    ema_slow = ema_calc(closes, 50)[-1]
    if ema_fast > ema_slow * 1.002:
        return 1
    if ema_fast < ema_slow * 0.998:
        return -1
    return 0

# ============================================================
# KILL SWITCH (circuit breaker harian)
# ============================================================
def load_daily_state():
    try:
        with open(STATE_FILE) as f:
            return json.load(f)
    except Exception:
        return {}

def save_daily_state(state):
    with open(STATE_FILE, "w") as f:
        json.dump(state, f, indent=2)

def check_kill_switch(info):
    """Jika rugi harian >= DAILY_LOSS_LIMIT_PCT equity -> trading dibekukan sampai besok."""
    today = get_wib_time().strftime("%Y-%m-%d")
    user_state = info.user_state(MAIN_WALLET)
    account_value = float(user_state.get("marginSummary", {}).get("accountValue", 0))
    state = load_daily_state()

    if state.get("date") != today:
        state = {"date": today, "start_equity": account_value, "halted": False}
        save_daily_state(state)

    if state.get("halted", False):
        return True, account_value, "HALTED (daily loss limit dari hari yang sama)"

    start_equity = state.get("start_equity", account_value) or account_value
    if start_equity != 0:
        day_pnl_pct = (account_value - start_equity) / start_equity * 100
        if day_pnl_pct <= -DAILY_LOSS_LIMIT_PCT:
            state["halted"] = True
            save_daily_state(state)
            return True, account_value, f"HALTED: rugi {day_pnl_pct:.1f}% (batas {DAILY_LOSS_LIMIT_PCT}%)"
    return False, account_value, "OK"

# ============================================================
# EKSEKUSI ORDER (5x leverage, SL/TP berbasis ATR)
# ============================================================
def execute_trade(exchange, info, coin, direction, current_price, atr):
    is_buy = (direction == "LONG")

    # Leverage: min(5x, max koin)
    max_coin = MAX_LEVERAGE_MAP.get(coin, 5)
    lev = min(TARGET_LEVERAGE, max_coin)

    # Size berdasar margin $2 x lev (notional kecil, aman)
    position_value = MARGIN_PER_TRADE * lev
    size = round_size(coin, position_value / current_price)

    # SL/TP berbasis ATR (harga), bukan % fixed
    sl_dist = atr * SL_ATR_MULT
    tp_dist = atr * TP_ATR_MULT
    if is_buy:
        tp_price = format_price(current_price + tp_dist)
        sl_price = format_price(current_price - sl_dist)
        limit_px = format_price(current_price * 1.003)
    else:
        tp_price = format_price(current_price - tp_dist)
        sl_price = format_price(current_price + sl_dist)
        limit_px = format_price(current_price * 0.997)

    print(f"\n  EXEC {direction} {coin} | size={size} | lev={lev}x | ATR=${atr:.2f}")
    print(f"  SL~${sl_price} | TP~${tp_price} | R:R={(tp_dist/sl_dist if sl_dist else 0):.2f}")

    try:
        exchange.update_leverage(lev, coin, is_cross=True)
    except Exception as e:
        print(f"  ⚠ leverage: {e}")

    orders = [
        {"coin": coin, "is_buy": is_buy, "sz": size, "limit_px": limit_px,
         "order_type": {"limit": {"tif": "Ioc"}}, "reduce_only": False},
        {"coin": coin, "is_buy": not is_buy, "sz": size, "limit_px": tp_price,
         "order_type": {"trigger": {"triggerPx": tp_price, "isMarket": True, "tpsl": "tp"}}, "reduce_only": True},
        {"coin": coin, "is_buy": not is_buy, "sz": size, "limit_px": sl_price,
         "order_type": {"trigger": {"triggerPx": sl_price, "isMarket": True, "tpsl": "sl"}}, "reduce_only": True},
    ]
    try:
        result = exchange.bulk_orders(orders, grouping="normalTpsl")
        statuses = result.get("response", {}).get("data", {}).get("statuses", [])
        entry_price = current_price; filled = False; tp_set = sl_set = False
        for i, st in enumerate(statuses):
            if "filled" in st:
                filled = True; entry_price = float(st["filled"]["avgPx"])
            elif "resting" in st:
                if i == 1: tp_set = True
                elif i == 2: sl_set = True
            elif "error" in st:
                print(f"  ❌ {st['error']}")
        return {"success": filled, "entry_price": entry_price, "tp_set": tp_set, "sl_set": sl_set,
                "tp_price": tp_price, "sl_price": sl_price, "size": size,
                "direction": direction, "coin": coin, "leverage": lev}
    except Exception as e:
        print(f"  ❌ Execution error: {e}")
        return {"success": False, "error": str(e)}

# ============================================================
# SMART POSITION MANAGEMENT (trailing berbasis ATR)
# ============================================================
SMART_EXIT_THRESHOLD = 7

# ============================================================
# PROTEKSI SL MANDIRI: pastikan tiap posisi terbuka tidak terlantar (tanpa SL)
# ============================================================
def has_protective_sl(info, wallet, coin, long, mid):
    """SL protektif ada bila ada order reduceOnly lawan arah tipe stop / trigger di bawah mark,
    ATAU order reduceOnly lawan arah yg limitPx-nya di sisi protektif (harga < mark utk long,
    > mark utk short). TP (take profit, limitPx > mark utk long) TIDAK dihitung sebagai SL.
    Pakai frontend_open_orders krn open_orders TIDAK mengembalikan orderType/triggerPx."""
    try:
        orders = info.frontend_open_orders(wallet)
    except Exception:
        return False
    for o in orders:
        if o.get("coin") != coin or not o.get("reduceOnly"):
            continue
        side = o.get("side")
        is_sell = (side == "A") or (o.get("isBuy") is False)
        # orderType dari frontendOpenOrders berupa STRING ('Stop Market'/'Take Profit Market')
        # atau dict {'trigger':{...}} — tangani keduanya. Hanya STOP yg dihitung SL (TP bukan).
        ot = o.get("orderType") or ""
        is_stop = ("stop" in str(ot).lower()) or (
            isinstance(ot, dict) and isinstance(ot.get("trigger"), dict))
        if is_stop:
            return True
        lp = o.get("limitPx")
        try:
            lp = float(lp)
        except Exception:
            lp = None
        mid = float(mid)
        if lp is not None:
            if long and is_sell and lp < mid:
                return True
            if (not long) and (not is_sell) and lp > mid:
                return True
    return False

def ensure_protective_sl(exchange, info, wallet, coin, szi, mid):
    """MANDIRI: pastikan posisi {coin} tidak terlantar (tanpa proteksi).
    Sadar kapasitas: bila TP-ladder reduce-only sudah mengikat SELURUH size, SL tak bisa
    ditumpuk — catat status itu (proteksi = smart-exit + kill-switch). Bila ada size tersisa,
    pasang SL reduce-only ATR. Murni protektif; tidak pernah membuka posisi baru."""
    mid = float(mid)
    szi = float(szi)
    long = szi > 0
    pos_sz = abs(szi)
    try:
        orders = info.frontend_open_orders(wallet)
    except Exception:
        orders = []
    committed = 0.0   # size reduce-only sisi berlawanan (TP-ladder + SL) yang dipakai
    has_sl = False
    for o in orders:
        if o.get("coin") != coin or not o.get("reduceOnly"):
            continue
        side = o.get("side"); is_sell = (side == "A") or (o.get("isBuy") is False)
        if is_sell != (not long):  # sisi berlawanan vs posisi
            try:
                committed += float(o.get("sz") or 0)
            except Exception:
                pass
        # frontendOpenOrders mengembalikan orderType STRING ('Stop Market'/'Take Profit Market')
        # atau dict {'trigger':{...}}. Deteksi SL = tipe stop (TP bukan SL).
        ot = o.get("orderType") or ""
        if ("stop" in str(ot).lower() or
                (isinstance(ot, dict) and isinstance(ot.get("trigger"), dict))):
            has_sl = True
    if has_sl:
        return False  # sudah ada SL protektif
    free_alloc = pos_sz - committed
    if free_alloc <= pos_sz * 0.001:
        # TP-ladder sudah penuh: SL tak bisa ditumpuk. Catat (log jurnal), proteksi aktif =
        # smart-exit + kill-switch + evaluator. Bukan error.
        print(f"  ℹ {coin}: seluruh ukuran {pos_sz:.0f} terpasang ke TP-ladder reduce-only; "
              f"tak ada size sisa utk SL -> proteksi=smart-exit+kill-switch (jarak liq vs mid)")
        return False
    try:
        closes, highs, lows, _ = get_candles(coin, ANALYSIS_TF, 120)
        atr = calculate_atr_raw(highs, lows, closes, 14) if len(closes) >= 15 else mid * 0.01
    except Exception:
        atr = mid * 0.01
    sl_dist = max(atr * SL_ATR_MULT, mid * 0.005)
    sl_price = (mid - sl_dist) if long else (mid + sl_dist)
    sl_price = format_price(sl_price)
    sl_order = {"coin": coin, "is_buy": (not long), "sz": free_alloc, "limit_px": sl_price,
                "order_type": {"trigger": {"triggerPx": sl_price, "isMarket": True, "tpsl": "sl"}},
                "reduce_only": True}
    try:
        resp = exchange.bulk_orders([sl_order], grouping="normalTpsl")
    except Exception as e:
        print(f"  ❌ AUTO-SL gagal {coin}: {e}")
        return False
    # FIX: resp adalah dict JSON mentah dari API ({"status":..,"response":{"data":{"statuses":[...]}}}),
    # BUKAN list. Cek lama `all(... for r in resp)` pada dict meng-iterasi KEY string-nya (selalu gagal
    # predikat -> all()=False) lalu fallback `or not isinstance(resp, list)` selalu True utk dict -> ok
    # SELALU True apa pun hasil order (klaim "AUTO-SL dipasang" walau sebenarnya ditolak exchange).
    statuses = []
    if isinstance(resp, dict) and resp.get("status") == "ok":
        statuses = resp.get("response", {}).get("data", {}).get("statuses", [])
    ok = bool(statuses) and all(isinstance(s, dict) and "error" not in s for s in statuses)
    if ok:
        print(f"  🛡 AUTO-SL dipasang {coin} @ {sl_price} (size {free_alloc:.4g}, jarak {abs(sl_price-mid)/mid*100:.1f}%)")
        return True
    print(f"  ⚠ AUTO-SL ditolak {coin}: {resp}")
    return False

# Perisai likuidasi: force-reduce bila posisi sudah terlalu dekat dengan likuidasi
# (buffer X% di atas/bawah harga likuidasi). Murni protektif utk posisi penuh-ladder.
LIQ_SAFETY_PCT = 12.0

def _trail_update_sl(exchange, info, coin, is_long, size, new_sl_price):
    """Geser SL mengikuti profit (trailing ATR). HANYA memperketat (mendekatkan
    ke harga saat ini demi mengunci profit) - tidak pernah melonggarkan risiko.
    Gagal-aman: kalau order SL resting tak ditemukan/tak bisa diparse, tidak
    menyentuh apa pun (SL asli dari execute_trade tetap berlaku)."""
    try:
        orders = info.frontend_open_orders(MAIN_WALLET)
    except Exception as e:
        print(f"  ⚠ trailing {coin}: gagal baca open orders: {e}")
        return
    sl_order = None
    for o in orders:
        if o.get("coin") != coin or not o.get("reduceOnly"):
            continue
        if "stop" in str(o.get("orderType", "")).lower():
            sl_order = o
            break
    if sl_order is None:
        return
    try:
        cur_sl = float(sl_order.get("triggerPx") or sl_order.get("limitPx"))
        oid = sl_order.get("oid")
    except Exception:
        return
    tighter = (new_sl_price > cur_sl) if is_long else (new_sl_price < cur_sl)
    if not tighter:
        return
    try:
        resp = exchange.modify_order(
            oid, coin, is_buy=(not is_long), sz=size, limit_px=new_sl_price,
            order_type={"trigger": {"triggerPx": new_sl_price, "isMarket": True, "tpsl": "sl"}},
            reduce_only=True,
        )
    except Exception as e:
        print(f"  ⚠ trailing {coin}: gagal update SL: {e}")
        return
    # HTTP 200 tak menjamin sukses - API bisa balas {"status":"ok",...} dgn error per-order
    # tersemat di dalamnya tanpa exception. Cek badan respons sebelum klaim berhasil (fail-safe:
    # bila ditolak, SL lama yg masih resting di exchange TETAP berlaku - tidak disentuh).
    rejected = not (isinstance(resp, dict) and resp.get("status") == "ok")
    if rejected:
        print(f"  ⚠ trailing {coin}: SL modify ditolak exchange: {resp}")
        return
    print(f"  📈 Trailing SL {coin}: {cur_sl} -> {new_sl_price}")

def manage_open_positions(exchange, info, all_mids):
    print(f"\n{'='*60}\nSMART POSITION MANAGEMENT\n{'='*60}")

    # HARGA LIVE utk SEMUA koin berposisi — jangan andalkan dict `all_mids` dari
    # main() yang cuma berisi WATCHLIST. Koin baru disuspend defi91_eval.py (_REMOVE)
    # di-exclude dari WATCHLIST, sehingga `all_mids.get(coin, entry)` jatuh ke harga
    # entry BASI (statis) -> jarak-ke-likuidasi & perisai dihitung dari harga yg tak
    # mencerminkan pasar (persis pada koin paling berisiko). Ambil mark live sendiri
    # utk semua aset lewat REST metaAndAssetCtxs (tahan lintas versi SDK).
    live_mids = {}
    try:
        _r2 = requests.post("https://api.hyperliquid.xyz/info",
                            json={"type": "metaAndAssetCtxs"}, timeout=15).json()
        _un = _r2[0].get("universe", []); _cx = _r2[1] if len(_r2) > 1 else []
        for _i, _a in enumerate(_un):
            _px = _a.get("midPx") or (_cx[_i].get("markPx") if _i < len(_cx) else None)
            if _px:
                live_mids[_a.get("name")] = float(_px)
    except Exception as e:
        print(f"  live-mid err: {e}")

    user_state = info.user_state(MAIN_WALLET)
    positions = user_state.get("assetPositions", [])
    for pos in positions:
        p = pos.get("position", {})
        coin = p.get("coin"); szi = float(p.get("szi", 0))
        if szi == 0:
            continue
        u_pnl = float(p.get("unrealizedPnl", 0))
        entry = float(p.get("entryPx", 0))
        mid = live_mids.get(coin) or all_mids.get(coin) or entry
        long = szi > 0
        print(f"  {coin} | szi={szi} | entry={entry:.2f} | uPnL=${u_pnl:.2f}")

        # PERISAI LIKUIDASI (FIX: sebelumnya cuma alert read-only di
        # monitor_positions.py, tidak ada force-close otomatis sama sekali).
        # Ditaruh di sini karena script ini satu-satunya yang sudah punya
        # exchange+private key terpercaya & jalan tiap 10 menit.
        liq_px = p.get("liquidationPx")
        liq_px = float(liq_px) if liq_px else None
        if liq_px and mid:
            dist_pct = abs(mid - liq_px) / mid * 100
            if dist_pct < LIQ_SAFETY_PCT:
                print(f"  🚨 PERISAI LIKUIDASI: {coin} jarak {dist_pct:.1f}% < {LIQ_SAFETY_PCT}% -> HARD CLOSE")
                try:
                    exchange.market_close(coin)
                except Exception as e:
                    print(f"  close err (liq shield): {e}")
                continue

        # hitung ulang sinyal berlawanan -> early close
        onchain, _ = analyze_onchain(coin)
        tech, _ = analyze_technical(coin)
        total = onchain + tech
        against = total >= SMART_EXIT_THRESHOLD if long else total <= -SMART_EXIT_THRESHOLD
        if against:
            print(f"  ⚡ Sinyal kuat berlawanan -> early close {coin}")
            try:
                exchange.market_close(coin)
            except Exception as e:
                print(f"  close err: {e}")
            continue
        # MANDIRI: pastikan posisi terbuka punya SL protektif (jangan sampai terlantar tanpanya)
        ensure_protective_sl(exchange, info, MAIN_WALLET, coin, szi, mid)
        # TRAILING STOP (ATR): SL diam di harga entry selamanya; saat profit >= 1.0x ATR
        # geser SL mengikuti harga mengunci profit (fail-safe: SL asli tetap bila gagal).
        try:
            closes, highs, lows, _ = get_candles(coin, ANALYSIS_TF, 60)
            atr = calculate_atr_raw(highs, lows, closes, 14) if len(closes) >= 15 else 0
            if atr > 0:
                profit_px = (mid - entry) if long else (entry - mid)
                if profit_px >= TRAILING_ATR_MULT * atr:
                    new_sl = format_price(mid - SL_ATR_MULT * atr) if long else format_price(mid + SL_ATR_MULT * atr)
                    _trail_update_sl(exchange, info, coin, long, abs(szi), new_sl)
        except Exception as e:
            print(f"  ⚠ trailing {coin}: {e}")
        # (FIX: dulu ada blok PERISAI LIKUIDASI kedua di sini yang mengulang cek
        # liquidationPx dengan rumus dist_pct berbeda dari blok di atas (pembagi liq
        # utk long vs pembagi mid) - duplikat & berpotensi tidak konsisten ambangnya.
        # Perisai likuidasi sudah ditegakkan tuntas di awal loop ini (baris ~691-701)
        # sebelum sinyal/trailing dihitung, jadi blok kedua dihapus - bukan dikurangi
        # proteksinya, hanya konsolidasi ke satu sumber kebenaran.)

# ============================================================
# MAIN
# ============================================================
def parse_private_key(val):
    """Terima private key hex (0x.. atau tanpa 0x) ATAU desimal 256-bit.
    Kembalikan object Account (hilangkan ambiguitas format)."""
    from eth_account import Account
    s = val.strip()
    hexno0x = s[2:] if s.startswith("0x") else s
    try:
        b = bytes.fromhex(hexno0x)
    except ValueError:
        b = None
    if b is not None and len(b) == 32:
        return Account.from_key(s if s.startswith("0x") else "0x" + hexno0x)
    try:
        d = int(s)
        return Account.from_key(d.to_bytes(32, "big"))
    except Exception:
        raise ValueError("Private key tidak valid: bukan hex 32-byte maupun desimal 256-bit.")


def main():
    print("=" * 60)
    print("DeFi91 Bot V3 (Hermes Strategic Revision)")
    print(f"Time: {get_wib_time().strftime('%Y-%m-%d %H:%M:%S')} WIB")
    print("=" * 60)

    if not PRIVATE_KEY and not DRY_RUN:
        print("❌ HYPERLIQUID_PRIVATE_KEY tidak ada. Abort tanpa eksekusi.")
        return

    info = None
    exchange = None
    # FIX KRITIS: syarat lama `if PRIVATE_KEY:` (tanpa cek DRY_RUN) berarti begitu
    # HYPERLIQUID_PRIVATE_KEY ADA di env, bot SELALU membuat Exchange bertanda-tangan
    # nyata & siap eksekusi order sungguhan - HYPERLIQUID_DRY_RUN=1 TIDAK berpengaruh
    # sama sekali selama key tersedia. Di host produksi (key selalu ada di env cron),
    # ini membuat DRY_RUN sepenuhnya palsu/tidak aman utk "uji pratinjau" (kontradiksi
    # aturan keamanan #2 di CLAUDE.md). Sekarang DRY_RUN jadi saklar utama: bila aktif,
    # SELALU hanya baca publik (Info tanpa Exchange) apa pun status private key.
    if PRIVATE_KEY and not DRY_RUN:
        info = Info(constants.MAINNET_API_URL, skip_ws=True)
        exchange = Exchange(parse_private_key(PRIVATE_KEY), constants.MAINNET_API_URL)
    else:
        info = Info(constants.MAINNET_API_URL, skip_ws=True)  # hanya baca publik
        print("🔬 DRY RUN: hanya menghitung & menampilkan sinyal. TIDAK ada order nyata.")

    # KILL SWITCH (hanya berarti bila ada akun/posisi nyata)
    # PENTING: halted HANYA menghentikan ENTRY BARU (aksi berisiko). Manajemen posisi
    # terbuka (perisai likuidasi, trailing SL, protective SL) TETAP berjalan di bawah -
    # justru pada hari rugi >=4% itulah proteksi terhadap posisi terbuka paling dibutuhkan.
    # (FIX: sebelumnya `return` di sini menghentikan seluruh main(), termasuk
    # manage_open_positions() -> perisai likuidasi mati total selama halted.)
    account_value = 0.0
    halted = False
    if exchange is not None:
        halted, account_value, msg = check_kill_switch(info)
        print(f"Saldo/nilai akun: ${account_value:.2f} | Kill-switch: {msg}")
        if halted:
            print("⛔ DAILY LOSS LIMIT -> entry baru dihentikan hari ini "
                  "(posisi terbuka tetap dikelola & dilindungi di bawah).")
    else:
        print(f"Saldo/nilai akun: (dry-run, tanpa key - {MAIN_WALLET}) | Kill-switch: nonaktif")

    # Current mids (via REST metaAndAssetCtxs - tahan lintas versi SDK)
    mids = {}
    try:
        _r = requests.post("https://api.hyperliquid.xyz/info",
                           json={"type": "metaAndAssetCtxs"}, timeout=15).json()
        _uni = _r[0].get("universe", [])
        _ctx = _r[1] if len(_r) > 1 else []
        for i, a in enumerate(_uni):
            n = a.get("name")
            if n in WATCHLIST:
                px = a.get("midPx") or (_ctx[i].get("markPx") if i < len(_ctx) else None)
                mids[n] = float(px) if px else mids.get(n, 0)
    except Exception as e:
        print("mid err", e)

    # Baca jumlah posisi terbuka + ekuitas akun + margin per-koin (kapasitas alokasi).
    # Desain: scale-in DIBOLEHKAN sampai margin tiap koin mencapai MAX_COIN_MARGIN_PCT
    # (tidak anti-pyramiding penuh) — cap mencegah satu simbol menguras akun, tapi
    # posisi yang sudah terbuka tetap dibiarkan bekerja (TP-ladder / smart-exit).
    open_coins = set()   # simbol dengan posisi aktif (FIX: dulu counter int yg naik per
                          # trade sukses, jadi scale-in ke koin yg sama ikut menaikkan
                          # hitungan -> MAX_OPEN_POSITIONS "batasi SIMBOL" jadi salah hitung)
    acct_value = 0.0
    coin_margin = {}
    free_margin = 0.0   # ekuitas bebas utk posisi baru (acct - totalMarginUsed)
    if info is not None:
        try:
            ust = info.user_state(MAIN_WALLET)
            open_coins = {p.get("position", {}).get("coin") for p in ust.get("assetPositions", [])
                         if float(p.get("position", {}).get("szi", 0)) != 0}
            sm = ust.get("marginSummary", {})
            acct_value = float(sm.get("accountValue", 0) or 0)
            free_margin = acct_value - float(sm.get("totalMarginUsed", 0) or 0)
            for ap in ust.get("assetPositions", []):
                _c = ap.get("position", {}).get("coin")
                if _c:
                    coin_margin[_c] = float(ap.get("position", {}).get("marginUsed", 0) or 0)
        except Exception:
            pass

    # Entry process (dilewati saat kill-switch / akun penuh; posisi tetap dikelola di bawah)
    entry_blocked = halted or (exchange is not None and free_margin < MARGIN_PER_TRADE)
    if halted:
        print("⛔ Kill-switch aktif: lewati seluruh entry baru siklus ini.")
    elif exchange is not None and free_margin < MARGIN_PER_TRADE:
        # Akun ~100% terpakai (mis. BTC memonopoli collateral) -> sisa margin hanya
        # cukup utk micro-slayer (~$0.12) yg profitnya ~nol & "tak masuk akal". JANGAN
        # buka posisi bayangan tak berarti; tunggu ada free margin >= MARGIN_PER_TRADE
        # agar posisi baru punya ukuran & potensi untung yang layak.
        print(f"⏭ Skip entry: margin bebas ${free_margin:.2f} < ${MARGIN_PER_TRADE} "
              f"(akun penuh). Posisi lama tetap dikelola; buka baru saat ada ruang.")
    for coin in ([] if entry_blocked else WATCHLIST):
        if len(open_coins) >= MAX_OPEN_POSITIONS:
            print(f"⚠ Telah mencapai MAX_OPEN_POSITIONS ({MAX_OPEN_POSITIONS}). Skip entry baru.")
            break

        current_price = mids.get(coin)
        if not current_price:
            print(f"  Skip {coin}: tak ada harga")
            continue

        # GERBANG CAP ALOKASI: margin koin ini (+trade baru) tidak boleh melebihi
        # MAX_COIN_MARGIN_PCT dari ekuitas akun -> cegah satu koin menguras akun
        # (hanya menghambat tranche BARU; posisi lama tak dipaksa tutup).
        if exchange is not None and acct_value > 0:
            projected_margin = coin_margin.get(coin, 0.0) + MARGIN_PER_TRADE
            cap = MAX_COIN_MARGIN_PCT * acct_value
            if projected_margin > cap:
                print(f"  ⏭ Skip {coin}: margin proyeksi ${projected_margin:.2f} > cap "
                      f"{MAX_COIN_MARGIN_PCT*100:.0f}% ekuitas (${cap:.2f}).")
                continue

        # Gate tren (ADX dari 1H) - hanya entry saat TRENDING.
        # Dalam dry-run, HYPERLIQUID_DRY_FORCE=1 melewati gate utk pratinjau order.
        force_preview = DRY_RUN and os.getenv("HYPERLIQUID_DRY_FORCE") == "1"
        regime = detect_market_regime(coin, ANALYSIS_TF)
        adx = regime.get("adx", 0); r = regime.get("regime", "UNKNOWN")
        print(f"\n[{coin}] regime={r} ADX={adx:.1f}")
        if (r != "TRENDING" or adx < ADX_MIN_TREND) and not force_preview:
            print(f"  ⏭ Skip {coin}: bukan regime TRENDING (ADX<{ADX_MIN_TREND}). Standby.")
            continue

        onchain, od = analyze_onchain(coin)
        tech, td = analyze_technical(coin)
        total = onchain + tech

        # === BIAS IKUT TREN saat ADX ekstrem (ikuti momentum, bukan lawan overbought) ===
        bias = 0
        if adx >= HIGH_ADX_MIN:
            d = trend_direction(coin, DIRECTION_TF)
            if d != 0:
                bias = d * HIGH_ADX_BIAS
                total += bias
                print(f"  🔥 ADX {adx:.0f} ekstrem & tren {'NAIK' if d>0 else 'TURUN'} "
                      f"-> bias skor {bias:+d} -> total {total:+d}")

        print(f"  onchain={onchain} | tech={tech} | total={total} (threshold {ENTRY_THRESHOLD})")

        if abs(total) < ENTRY_THRESHOLD:
            print(f"  ⏭ {coin}: skor tidak cukup (|{total}| < {ENTRY_THRESHOLD})")
            continue

        direction = "LONG" if total > 0 else "SHORT"

        # ATR 1H untuk risk sizing (dalam satuan harga $)
        closes, highs, lows, _ = get_candles(coin, ANALYSIS_TF, 120)
        atr = calculate_atr_raw(highs, lows, closes, 14) if len(closes) >= 15 else current_price * 0.01

        print(f"  → ENTRY {direction} {coin} @ ~{current_price:.2f}")

        # === GERBANG FEE LANDASAN: jangan trade bila TP tak menutup biaya putaran ===
        tp_pct = (atr * TP_ATR_MULT) / current_price * 100
        fee_cost_pct = ROUNDTRIP_FEE_PCT
        if tp_pct < MIN_TP_PCT_AFTER_FEE:
            print(f"  ⏭ Skip {coin}: TP {tp_pct:.2f}% terlalu kecil vs fee 2-sisi {fee_cost_pct:.2f}% "
                  f"(perlu ≥{MIN_TP_PCT_AFTER_FEE:.2f}%). Tak menguntungkan bersih.")
            continue
        print(f"  ✅ Fee landasan OK: TP {tp_pct:.2f}% > {MIN_TP_PCT_AFTER_FEE:.2f}% "
              f"(fee 2-sisi {fee_cost_pct:.2f}% => sisa bersih {tp_pct-fee_cost_pct:.2f}%)")

        # === BATAS ALOKASI PER KOIN: cegah satu simbol memboroskan seluruh akun ===
        # Cap 15% ekuitas. Hanya menghambat TRANCHER/ENTRY BARU; posisi lama DIBIARKAN
        # bekerja (TP-ladder/smart-management tetap jalan, tidak dipaksa tutup).
        cap_margin = acct_value * MAX_COIN_MARGIN_PCT
        cur_margin = coin_margin.get(coin, 0.0)
        if cap_margin > 0 and (cur_margin + MARGIN_PER_TRADE) > cap_margin:
            print(f"  ⏭ Skip {coin}: margin koin ${cur_margin:.2f} + $2 melewati cap "
                  f"${cap_margin:.2f} ({MAX_COIN_MARGIN_PCT:.0%} ekuitas ${acct_value:.2f}). "
                  f"Posisi lama dibiarkan bekerja; tranche baru dihentikan.")
            continue

        if exchange is None:
            # DRY RUN: hitung & tampilkan order yang SEHARUSNYA dipasang, tanpa eksekusi
            max_coin = MAX_LEVERAGE_MAP.get(coin, 5)
            lv = min(TARGET_LEVERAGE, max_coin)
            sz = round_size(coin, (MARGIN_PER_TRADE * lv) / current_price)
            if direction == "LONG":
                _tp = current_price + atr * TP_ATR_MULT; _sl = current_price - atr * SL_ATR_MULT
            else:
                _tp = current_price - atr * TP_ATR_MULT; _sl = current_price + atr * SL_ATR_MULT
            print(f"  🔬[DRY] {direction} {coin} | size={sz} | lev={lv}x | margin=${MARGIN_PER_TRADE}"
                  f" | notional=${MARGIN_PER_TRADE*lv:.2f}")
            print(f"         SL~${_sl:.2f} ({abs(_sl-current_price)/current_price*100:.2f}%) "
                  f"| TP~${_tp:.2f} ({abs(_tp-current_price)/current_price*100:.2f}%) | R:R={TP_ATR_MULT/SL_ATR_MULT:.2f}")
            continue
        result = execute_trade(exchange, info, coin, direction, current_price, atr)
        if result.get("success"):
            open_coins.add(coin)

    # Smart management setelah memproses (hanya bila ada akun nyata)
    if exchange is not None and info is not None:
        manage_open_positions(exchange, info, mids)

if __name__ == "__main__":
    main()
