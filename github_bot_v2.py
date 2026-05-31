"""
DeFi91 Trading Bot - Final Version
Strategi: Almarhum Doddy Ali Wijaya (CVD/Order Flow) + KJo Academy (RSI/MACD)
Exchange: Hyperliquid Perpetual Futures
Mode: LIVE - Eksekusi Order Nyata dengan TP/SL

Bot ini berjalan di GitHub Actions setiap 15 menit.
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

# ============================================================
# KONFIGURASI
# ============================================================
PRIVATE_KEY = os.getenv("HYPERLIQUID_PRIVATE_KEY", "")
MAIN_WALLET = "0x03562722fE32Ff3BaFE214be3F1828A9157eC23D"

# Trading Parameters (AGRESIF - leverage tinggi, filter ketat, profit besar)
WATCHLIST = [
    "BTC",   # #1 volume - Raja crypto
    "HYPE",  # #2 volume - Native Hyperliquid token
    "ETH",   # #3 volume - King of altcoins
    "SOL",   # #5 volume - Ecosystem terkuat
    "NEAR",  # #6 volume - AI narrative
    "XRP",   # #7 volume - Payment leader
    "WLD",   # #9 volume - AI/Worldcoin
    "SUI",   # #13 volume - Move ecosystem
    "DOGE",  # #19 volume - Meme king
    "BNB",   # Exchange coin - almarhum kuasai
]
MARGIN_PER_TRADE = 2.0  # $2 per trade
LEVERAGE = 20  # 20x leverage (2x lebih agresif)
TP_PERCENT = 0.025  # 2.5% Take Profit (leverage tinggi = target lebih besar)
SL_PERCENT = 0.012  # 1.2% Stop Loss (Risk:Reward = 1:2)
ENTRY_THRESHOLD = 3  # Minimum score 3 untuk entry (lebih ketat = lebih akurat)
MAX_OPEN_POSITIONS = 5  # Maksimal 5 posisi ($2 x 5 = $10 margin, sisa buffer)

# Size decimals per coin (dari Hyperliquid metadata)
SZ_DECIMALS = {
    "BTC": 5, "ETH": 4, "BNB": 3, "SOL": 2, "HYPE": 2,
    "XRP": 0, "NEAR": 1, "DOGE": 0, "SUI": 1, "WLD": 1,
}

# ============================================================
# HELPER FUNCTIONS
# ============================================================
def get_wib_time():
    """Get current time in WIB (UTC+7)"""
    return datetime.now(timezone(timedelta(hours=7)))

def round_size(coin, size):
    """Round size to correct decimals for each coin"""
    decimals = SZ_DECIMALS.get(coin, 4)
    return round(size, decimals)

def format_price(price):
    """Format price to max 5 significant figures for Hyperliquid API"""
    if price >= 10000:
        return round(price, 0)
    elif price >= 1000:
        return round(price, 1)
    elif price >= 100:
        return round(price, 1)
    elif price >= 10:
        return round(price, 2)
    elif price >= 1:
        return round(price, 3)
    elif price >= 0.1:
        return round(price, 4)
    else:
        return round(price, 5)

def calculate_rsi(prices, period=14):
    """Calculate RSI from price array"""
    if len(prices) < period + 1:
        return 50.0
    deltas = np.diff(prices)
    gains = np.where(deltas > 0, deltas, 0)
    losses = np.where(deltas < 0, -deltas, 0)
    avg_gain = np.mean(gains[-period:])
    avg_loss = np.mean(losses[-period:])
    if avg_loss == 0:
        return 100.0
    rs = avg_gain / avg_loss
    return 100 - (100 / (1 + rs))

def calculate_macd(prices):
    """Calculate MACD (12, 26, 9)"""
    if len(prices) < 26:
        return 0, 0
    ema12 = np.mean(prices[-12:])
    ema26 = np.mean(prices[-26:])
    macd_line = ema12 - ema26
    signal = np.mean(prices[-9:]) - np.mean(prices[-18:])
    return macd_line, signal

def get_candles(coin, interval="15m", lookback=50):
    """Get candle data from Hyperliquid"""
    url = "https://api.hyperliquid.xyz/info"
    end_time = int(time.time() * 1000)
    
    # interval mapping
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
        resp = requests.post(url, json=payload, timeout=10)
        data = resp.json()
        closes = [float(c["c"]) for c in data]
        volumes = [float(c["v"]) for c in data]
        return closes, volumes
    except:
        return [], []

def get_recent_trades(coin, limit=200):
    """Get recent trades for CVD calculation"""
    url = "https://api.hyperliquid.xyz/info"
    payload = {"type": "recentTrades", "coin": coin}
    
    try:
        resp = requests.post(url, json=payload, timeout=10)
        trades = resp.json()
        return trades[-limit:] if len(trades) > limit else trades
    except:
        return []

def calculate_cvd(trades):
    """Calculate CVD - Cumulative Volume Delta (indikator raja almarhum)"""
    if not trades:
        return 0, 0.5
    
    buy_volume = 0
    sell_volume = 0
    
    for trade in trades:
        size = float(trade.get("sz", 0))
        side = trade.get("side", "")
        if side == "B":
            buy_volume += size
        else:
            sell_volume += size
    
    total = buy_volume + sell_volume
    if total == 0:
        return 0, 0.5
    
    cvd = buy_volume - sell_volume
    buy_ratio = buy_volume / total
    return cvd, buy_ratio

def get_orderbook(coin):
    """Get L2 order book for bid/ask ratio analysis"""
    url = "https://api.hyperliquid.xyz/info"
    payload = {"type": "l2Book", "coin": coin}
    
    try:
        resp = requests.post(url, json=payload, timeout=10)
        data = resp.json()
        levels = data.get("levels", [[], []])
        
        bid_volume = sum(float(b.get("sz", 0)) for b in levels[0][:10])
        ask_volume = sum(float(a.get("sz", 0)) for a in levels[1][:10])
        
        total = bid_volume + ask_volume
        if total == 0:
            return 1.0
        return bid_volume / ask_volume if ask_volume > 0 else 10.0
    except:
        return 1.0

def get_funding_rate(coin):
    """Get current funding rate"""
    url = "https://api.hyperliquid.xyz/info"
    payload = {"type": "metaAndAssetCtxs"}
    
    try:
        resp = requests.post(url, json=payload, timeout=10)
        data = resp.json()
        assets = data[0].get("universe", [])
        ctxs = data[1]
        
        for i, asset in enumerate(assets):
            if asset.get("name") == coin:
                funding = float(ctxs[i].get("funding", 0))
                return funding
        return 0
    except:
        return 0

# ============================================================
# ANALISA STRATEGI ALMARHUM (ON-CHAIN / ORDER FLOW)
# ============================================================
def analyze_onchain(coin):
    """
    Analisa On-Chain ala almarhum Doddy Ali Wijaya:
    1. CVD (Cumulative Volume Delta) - RAJA indikator
    2. Order Book Ratio (Bid vs Ask)
    3. Funding Rate
    
    Returns: score (-7 to +7), details dict
    """
    score = 0
    details = {}
    
    # 1. CVD Analysis (bobot tertinggi: ±3)
    trades = get_recent_trades(coin)
    cvd, buy_ratio = calculate_cvd(trades)
    details["cvd_buy_ratio"] = f"{buy_ratio*100:.0f}%"
    
    if buy_ratio > 0.65:
        score += 3
        details["cvd_signal"] = "STRONG BUY"
    elif buy_ratio > 0.55:
        score += 2
        details["cvd_signal"] = "BUY"
    elif buy_ratio < 0.35:
        score -= 3
        details["cvd_signal"] = "STRONG SELL"
    elif buy_ratio < 0.45:
        score -= 2
        details["cvd_signal"] = "SELL"
    else:
        details["cvd_signal"] = "NEUTRAL"
    
    # 2. Order Book Analysis (bobot: ±2)
    ob_ratio = get_orderbook(coin)
    details["orderbook_ratio"] = f"{ob_ratio:.2f}"
    
    if ob_ratio > 2.0:
        score += 2
        details["ob_signal"] = "BID HEAVY (Bullish)"
    elif ob_ratio > 1.3:
        score += 1
        details["ob_signal"] = "BID LEAN"
    elif ob_ratio < 0.5:
        score -= 2
        details["ob_signal"] = "ASK HEAVY (Bearish)"
    elif ob_ratio < 0.77:
        score -= 1
        details["ob_signal"] = "ASK LEAN"
    else:
        details["ob_signal"] = "BALANCED"
    
    # 3. Funding Rate Analysis (bobot: ±2)
    funding = get_funding_rate(coin)
    details["funding_rate"] = f"{funding*100:.4f}%"
    
    if funding > 0.01:
        score -= 2  # Terlalu banyak long, kontrarian = short
        details["funding_signal"] = "HIGH LONG (Contrarian SHORT)"
    elif funding > 0.005:
        score -= 1
        details["funding_signal"] = "MODERATE LONG"
    elif funding < -0.01:
        score += 2  # Terlalu banyak short, kontrarian = long
        details["funding_signal"] = "HIGH SHORT (Contrarian LONG)"
    elif funding < -0.005:
        score += 1
        details["funding_signal"] = "MODERATE SHORT"
    else:
        details["funding_signal"] = "NEUTRAL"
    
    details["onchain_score"] = score
    return score, details

# ============================================================
# ANALISA TEKNIKAL KJO ACADEMY
# ============================================================
def analyze_technical(coin):
    """
    Analisa Teknikal ala KJo Academy:
    1. RSI (Overbought/Oversold + Divergence)
    2. MACD (Momentum)
    3. Support/Resistance (Price Action)
    
    Returns: score (-5 to +5), details dict
    """
    score = 0
    details = {}
    
    closes, volumes = get_candles(coin, "15m", 50)
    if len(closes) < 26:
        details["technical_error"] = "Insufficient data"
        return 0, details
    
    # 1. RSI Analysis (bobot: ±2)
    rsi = calculate_rsi(closes)
    details["rsi"] = f"{rsi:.1f}"
    
    if rsi < 30:
        score += 2  # Oversold = Buy signal
        details["rsi_signal"] = "OVERSOLD (Buy)"
    elif rsi < 40:
        score += 1
        details["rsi_signal"] = "LOW (Lean Buy)"
    elif rsi > 70:
        score -= 2  # Overbought = Sell signal
        details["rsi_signal"] = "OVERBOUGHT (Sell)"
    elif rsi > 60:
        score -= 1
        details["rsi_signal"] = "HIGH (Lean Sell)"
    else:
        details["rsi_signal"] = "NEUTRAL"
    
    # 2. MACD Analysis (bobot: ±2)
    macd_line, signal_line = calculate_macd(closes)
    details["macd"] = f"{macd_line:.2f}"
    
    if macd_line > 0 and macd_line > signal_line:
        score += 2
        details["macd_signal"] = "BULLISH CROSS"
    elif macd_line > 0:
        score += 1
        details["macd_signal"] = "BULLISH"
    elif macd_line < 0 and macd_line < signal_line:
        score -= 2
        details["macd_signal"] = "BEARISH CROSS"
    elif macd_line < 0:
        score -= 1
        details["macd_signal"] = "BEARISH"
    else:
        details["macd_signal"] = "NEUTRAL"
    
    # 3. Price Action / S&R (bobot: ±1)
    current_price = closes[-1]
    recent_high = max(closes[-20:])
    recent_low = min(closes[-20:])
    price_range = recent_high - recent_low
    
    if price_range > 0:
        position_in_range = (current_price - recent_low) / price_range
        details["price_position"] = f"{position_in_range*100:.0f}%"
        
        if position_in_range < 0.2:
            score += 1  # Near support = buy
            details["sr_signal"] = "NEAR SUPPORT (Buy)"
        elif position_in_range > 0.8:
            score -= 1  # Near resistance = sell
            details["sr_signal"] = "NEAR RESISTANCE (Sell)"
        else:
            details["sr_signal"] = "MID RANGE"
    
    details["technical_score"] = score
    return score, details

# ============================================================
# EKSEKUSI ORDER
# ============================================================
def execute_trade(exchange, info, coin, direction, current_price):
    """
    Eksekusi order dengan TP/SL menggunakan grouped orders
    direction: "LONG" atau "SHORT"
    """
    is_buy = (direction == "LONG")
    
    # Calculate size
    position_value = MARGIN_PER_TRADE * LEVERAGE
    size = position_value / current_price
    size = round_size(coin, size)
    
    # Calculate TP/SL prices (format_price ensures Hyperliquid compatibility)
    if is_buy:  # LONG
        tp_price = format_price(current_price * (1 + TP_PERCENT))
        sl_price = format_price(current_price * (1 - SL_PERCENT))
        limit_px = format_price(current_price * 1.005)  # 0.5% slippage
    else:  # SHORT
        tp_price = format_price(current_price * (1 - TP_PERCENT))
        sl_price = format_price(current_price * (1 + SL_PERCENT))
        limit_px = format_price(current_price * 0.995)  # 0.5% slippage
    
    print(f"\n  EXECUTING {direction} {coin}")
    print(f"  Size: {size} | Margin: ${MARGIN_PER_TRADE} | Leverage: {LEVERAGE}x")
    print(f"  Entry ~${current_price:.2f} | TP: ${tp_price} | SL: ${sl_price}")
    
    # Set leverage first (cross margin, 20x)
    try:
        exchange.update_leverage(LEVERAGE, coin, is_cross=True)
        print(f"  ✅ Leverage set to {LEVERAGE}x for {coin}")
    except Exception as e:
        print(f"  ⚠️ Could not set leverage: {e}")
    
    # Grouped order: Market + TP + SL
    orders = [
        # Market Order (IOC)
        {
            "coin": coin,
            "is_buy": is_buy,
            "sz": size,
            "limit_px": limit_px,
            "order_type": {"limit": {"tif": "Ioc"}},
            "reduce_only": False,
        },
        # TP Order
        {
            "coin": coin,
            "is_buy": not is_buy,
            "sz": size,
            "limit_px": tp_price,
            "order_type": {"trigger": {"triggerPx": tp_price, "isMarket": True, "tpsl": "tp"}},
            "reduce_only": True,
        },
        # SL Order
        {
            "coin": coin,
            "is_buy": not is_buy,
            "sz": size,
            "limit_px": sl_price,
            "order_type": {"trigger": {"triggerPx": sl_price, "isMarket": True, "tpsl": "sl"}},
            "reduce_only": True,
        },
    ]
    
    try:
        result = exchange.bulk_orders(orders, grouping="normalTpsl")
        statuses = result.get("response", {}).get("data", {}).get("statuses", [])
        
        order_filled = False
        tp_set = False
        sl_set = False
        entry_price = current_price
        
        for i, status in enumerate(statuses):
            if "filled" in status:
                order_filled = True
                entry_price = float(status["filled"]["avgPx"])
                print(f"  ✅ ORDER FILLED @ ${entry_price}")
            elif "resting" in status:
                if i == 1:
                    tp_set = True
                    print(f"  ✅ TP SET (OID: {status['resting']['oid']})")
                elif i == 2:
                    sl_set = True
                    print(f"  ✅ SL SET (OID: {status['resting']['oid']})")
            elif "error" in status:
                print(f"  ❌ Error: {status['error']}")
        
        return {
            "success": order_filled,
            "entry_price": entry_price,
            "tp_set": tp_set,
            "sl_set": sl_set,
            "tp_price": tp_price,
            "sl_price": sl_price,
            "size": size,
            "direction": direction,
            "coin": coin,
        }
    except Exception as e:
        print(f"  ❌ Execution error: {e}")
        return {"success": False, "error": str(e)}

# ============================================================
# SMART EXIT + TRAILING STOP (Opsi B + C)
# ============================================================
SMART_EXIT_THRESHOLD = 4  # Skor berlawanan >= 4 = early close (lebih ketat, hindari false signal)
TRAILING_BREAKEVEN = 0.008  # Profit >= 0.8% → SL geser ke breakeven (leverage tinggi = cepat profit)
TRAILING_LOCK = 0.015  # Profit >= 1.5% → SL geser ke +1%

def manage_open_positions(exchange, info, all_mids):
    """
    Smart Exit + Trailing Stop:
    1. Analisa ulang setiap posisi terbuka
    2. Jika sinyal berbalik kuat (skor >= 3 berlawanan) → early close
    3. Jika profit >= 1% → geser SL ke breakeven
    4. Jika profit >= 1.5% → geser SL ke +1% (profit terkunci)
    """
    print(f"\n{'='*60}")
    print(f"SMART POSITION MANAGEMENT")
    print(f"{'='*60}")
    
    user_state = info.user_state(MAIN_WALLET)
    positions = user_state.get("assetPositions", [])
    
    actions_taken = []
    
    for pos in positions:
        p = pos.get("position", {})
        coin = p.get("coin")
        szi = float(p.get("szi", 0))
        entry_px = float(p.get("entryPx", 0))
        
        if szi == 0 or coin not in WATCHLIST:
            continue
        
        is_long = szi > 0
        direction = "LONG" if is_long else "SHORT"
        current_price = float(all_mids.get(coin, 0))
        
        if current_price == 0 or entry_px == 0:
            continue
        
        # Hitung profit/loss saat ini
        if is_long:
            pnl_percent = (current_price - entry_px) / entry_px
        else:
            pnl_percent = (entry_px - current_price) / entry_px
        
        print(f"\n  [{coin}] {direction} | Entry: ${entry_px:.4f} | Now: ${current_price:.4f} | PnL: {pnl_percent*100:.2f}%")
        
        # ─────────────────────────────────────────────────────────
        # STEP 1: SMART EXIT - Analisa ulang sinyal
        # ─────────────────────────────────────────────────────────
        onchain_score, _ = analyze_onchain(coin)
        tech_score, _ = analyze_technical(coin)
        total_score = onchain_score + tech_score
        
        print(f"    Re-analysis Score: {total_score}/12")
        
        # Cek apakah sinyal berbalik kuat
        should_close = False
        close_reason = ""
        
        if is_long and total_score <= -SMART_EXIT_THRESHOLD:
            # Posisi LONG tapi sinyal sekarang STRONG SHORT
            should_close = True
            close_reason = f"Signal reversed to STRONG SHORT (score: {total_score})"
        elif not is_long and total_score >= SMART_EXIT_THRESHOLD:
            # Posisi SHORT tapi sinyal sekarang STRONG LONG
            should_close = True
            close_reason = f"Signal reversed to STRONG LONG (score: {total_score})"
        
        if should_close:
            print(f"    \u26a1 SMART EXIT: {close_reason}")
            try:
                close_size = abs(szi)
                close_success = False
                exit_price = current_price
                
                # STEP 1: CLOSE POSISI dengan IOC order (reliable, tidak bergantung market_close)
                close_is_buy = not is_long
                if close_is_buy:
                    close_px = format_price(current_price * 1.03)  # 3% slippage for buy
                else:
                    close_px = format_price(current_price * 0.97)  # 3% slippage for sell
                
                close_order = {
                    "coin": coin,
                    "is_buy": close_is_buy,
                    "sz": close_size,
                    "limit_px": close_px,
                    "order_type": {"limit": {"tif": "Ioc"}},
                    "reduce_only": True,
                }
                result = exchange.bulk_orders([close_order])
                if isinstance(result, dict):
                    if result.get("status") == "ok":
                        statuses = result.get("response", {}).get("data", {}).get("statuses", [])
                        if statuses and "filled" in statuses[0]:
                            exit_price = float(statuses[0]["filled"]["avgPx"])
                            close_success = True
                    else:
                        print(f"    API Error: {result.get('response', 'Unknown')}")
                elif isinstance(result, str):
                    print(f"    API returned string: {result[:100]}")
                    close_success = False
                
                if close_success:
                    # STEP 2: Close berhasil → Cancel TP/SL yang tersisa
                    time.sleep(0.5)
                    fe_payload = {"type": "frontendOpenOrders", "user": MAIN_WALLET}
                    fe_resp = requests.post("https://api.hyperliquid.xyz/info", json=fe_payload, timeout=10)
                    fe_orders = fe_resp.json()
                    for order in fe_orders:
                        if order.get("coin") == coin:
                            try:
                                exchange.cancel(coin, order["oid"])
                            except:
                                pass
                    
                    actual_pnl = (exit_price - entry_px) / entry_px if is_long else (entry_px - exit_price) / entry_px
                    print(f"    \u2705 Position CLOSED @ ${exit_price} (Smart Exit) | PnL: {actual_pnl*100:.2f}%")
                    print(f"    \u2705 TP/SL cancelled (position closed)")
                    
                    actions_taken.append({
                        "coin": coin,
                        "action": "SMART_EXIT",
                        "reason": close_reason,
                        "pnl_percent": actual_pnl,
                        "entry": entry_px,
                        "exit": exit_price,
                    })
                else:
                    # Close gagal - TP/SL MASIH TERPASANG (posisi tetap aman)
                    print(f"    \u274c Close failed, TP/SL still active (position protected)")
            except Exception as e:
                print(f"    \u274c Smart Exit error: {e}")
            continue  # Lanjut ke posisi berikutnya
        
        # ─────────────────────────────────────────────────────────
        # STEP 2: TRAILING STOP - Geser SL mengunci profit
        # ─────────────────────────────────────────────────────────
        if pnl_percent >= TRAILING_BREAKEVEN:
            # Tentukan SL baru
            if pnl_percent >= TRAILING_LOCK:
                # Profit >= 1.5% → Lock profit di +1%
                if is_long:
                    new_sl = format_price(entry_px * 1.01)
                else:
                    new_sl = format_price(entry_px * 0.99)
                trail_type = "LOCK +1%"
            else:
                # Profit >= 1% → Geser ke breakeven
                new_sl = format_price(entry_px)
                trail_type = "BREAKEVEN"
            
            # Cek apakah SL saat ini sudah lebih baik dari new_sl
            # Gunakan frontendOpenOrders untuk melihat trigger orders
            fe_payload = {"type": "frontendOpenOrders", "user": MAIN_WALLET}
            fe_resp = requests.post("https://api.hyperliquid.xyz/info", json=fe_payload, timeout=10)
            fe_orders = fe_resp.json()
            current_sl_oid = None
            current_sl_price = None
            
            for order in fe_orders:
                if (order.get("coin") == coin and 
                    order.get("orderType", "") == "Stop Market" and
                    order.get("reduceOnly", False)):
                    current_sl_oid = order["oid"]
                    current_sl_price = float(order.get("triggerPx", 0))
                    break
            
            # Hanya geser SL jika SL baru lebih baik (lebih dekat ke profit)
            should_trail = False
            if current_sl_price is not None:
                if is_long and new_sl > current_sl_price:
                    should_trail = True  # SL naik = lebih baik untuk LONG
                elif not is_long and new_sl < current_sl_price:
                    should_trail = True  # SL turun = lebih baik untuk SHORT
            elif current_sl_oid is None:
                # Tidak ada SL terpasang, pasang baru
                should_trail = True
            
            if should_trail:
                print(f"    📈 TRAILING STOP: {trail_type} | New SL: ${new_sl}")
                try:
                    # Cancel SL lama
                    if current_sl_oid:
                        exchange.cancel(coin, current_sl_oid)
                    
                    # Pasang SL baru (gunakan exchange.order individual, bukan bulk_orders)
                    size = abs(szi)
                    order_type = {"trigger": {"triggerPx": new_sl, "isMarket": True, "tpsl": "sl"}}
                    result = exchange.order(coin, not is_long, size, new_sl, order_type, reduce_only=True)
                    statuses = result.get("response", {}).get("data", {}).get("statuses", [])
                    
                    if statuses and "resting" in statuses[0]:
                        print(f"    ✅ SL updated to ${new_sl} ({trail_type})")
                        actions_taken.append({
                            "coin": coin,
                            "action": "TRAILING_STOP",
                            "reason": trail_type,
                            "old_sl": current_sl_price,
                            "new_sl": new_sl,
                            "pnl_percent": pnl_percent,
                        })
                    else:
                        print(f"    ❌ SL update failed: {statuses}")
                except Exception as e:
                    print(f"    ❌ Trailing Stop error: {e}")
            else:
                print(f"    ✅ SL already optimal (current: ${current_sl_price}, target: ${new_sl})")
        else:
            print(f"    ⏳ Holding (PnL {pnl_percent*100:.2f}% < 1% trailing threshold)")
    
    if not actions_taken:
        print(f"\n  No position adjustments needed.")
    else:
        print(f"\n  Actions taken: {len(actions_taken)}")
        for a in actions_taken:
            print(f"    - {a['coin']}: {a['action']} ({a['reason']})")
    
    return actions_taken

# ============================================================
# MAIN BOT LOGIC
# ============================================================
def run_bot():
    """Main bot execution"""
    print("=" * 60)
    print(f"DeFi91 TRADING BOT - LIVE MODE")
    print(f"Time: {get_wib_time().strftime('%Y-%m-%d %H:%M:%S')} WIB")
    print(f"Strategy: Almarhum Doddy Ali Wijaya + KJo Academy")
    print("=" * 60)
    
    # Initialize
    if not PRIVATE_KEY:
        print("ERROR: HYPERLIQUID_PRIVATE_KEY not set!")
        return
    
    account = Account.from_key(PRIVATE_KEY)
    info = Info(constants.MAINNET_API_URL, skip_ws=True)
    exchange = Exchange(account, constants.MAINNET_API_URL)
    
    # Check account - Unified Account: saldo USDC ada di spotClearinghouseState
    spot_payload = {"type": "spotClearinghouseState", "user": MAIN_WALLET}
    spot_resp = requests.post("https://api.hyperliquid.xyz/info", json=spot_payload, timeout=10)
    spot_data = spot_resp.json()
    usdc_balance = 0.0
    for bal in spot_data.get("balances", []):
        if bal.get("coin") == "USDC":
            usdc_balance = float(bal.get("total", 0))
            break
    
    user_state = info.user_state(MAIN_WALLET)
    margin_used = float(user_state.get("marginSummary", {}).get("totalMarginUsed", 0))
    account_value = usdc_balance
    available = account_value - margin_used
    
    print(f"\nAccount Value (Unified): ${account_value:.2f}")
    print(f"USDC Balance: ${usdc_balance:.2f}")
    print(f"Margin Used: ${margin_used:.2f}")
    print(f"Available: ${available:.2f}")
    
    # Check existing positions
    positions = user_state.get("assetPositions", [])
    open_coins = []
    for pos in positions:
        p = pos.get("position", {})
        coin = p.get("coin")
        szi = float(p.get("szi", 0))
        if szi != 0:
            open_coins.append(coin)
            print(f"  Existing position: {coin} {'SHORT' if szi < 0 else 'LONG'} Size={abs(szi)}")
    
    # Check if enough balance
    if available < MARGIN_PER_TRADE:
        print(f"\n⚠️ Insufficient balance (${available:.2f} < ${MARGIN_PER_TRADE})")
        print("Waiting for positions to close...")
        save_trades_json([], "NO_TRADE", "Insufficient balance")
        return
    
    # Get all mid prices
    all_mids = info.all_mids()
    
    # ═══════════════════════════════════════════════════════════
    # SMART POSITION MANAGEMENT (Analisa ulang + Trailing Stop)
    # Dijalankan SEBELUM mencari entry baru
    # ═══════════════════════════════════════════════════════════
    if open_coins:
        smart_actions = manage_open_positions(exchange, info, all_mids)
        
        # Refresh posisi setelah smart exit (mungkin ada yang ditutup)
        if smart_actions:
            user_state = info.user_state(MAIN_WALLET)
            positions = user_state.get("assetPositions", [])
            open_coins = []
            for pos in positions:
                p = pos.get("position", {})
                coin_name = p.get("coin")
                szi = float(p.get("szi", 0))
                if szi != 0:
                    open_coins.append(coin_name)
            
            # Recalculate available balance
            margin_used = float(user_state.get("marginSummary", {}).get("totalMarginUsed", 0))
            available = account_value - margin_used
            print(f"\n  [Updated] Open positions: {len(open_coins)} | Available: ${available:.2f}")
    
    # ═══════════════════════════════════════════════════════════
    # MENCARI ENTRY BARU
    # ═══════════════════════════════════════════════════════════
    
    # Analyze each coin
    trades_executed = []
    
    for coin in WATCHLIST:
        if coin in open_coins:
            print(f"\n--- {coin}: SKIP (already has open position) ---")
            continue
        
        if len(open_coins) + len(trades_executed) >= MAX_OPEN_POSITIONS:
            print(f"\n--- {coin}: SKIP (max {MAX_OPEN_POSITIONS} positions reached) ---")
            break
        
        if available < MARGIN_PER_TRADE:
            print(f"\n--- {coin}: SKIP (insufficient balance) ---")
            break
        
        print(f"\n{'='*40}")
        print(f"ANALYZING {coin}")
        print(f"{'='*40}")
        
        current_price = float(all_mids.get(coin, 0))
        if current_price == 0:
            print(f"  Cannot get price for {coin}")
            continue
        
        print(f"  Current Price: ${current_price:.2f}")
        
        # On-Chain Analysis (Almarhum)
        onchain_score, onchain_details = analyze_onchain(coin)
        print(f"\n  [ON-CHAIN - Almarhum]")
        print(f"  CVD Buy Ratio: {onchain_details.get('cvd_buy_ratio', 'N/A')}")
        print(f"  CVD Signal: {onchain_details.get('cvd_signal', 'N/A')}")
        print(f"  Order Book: {onchain_details.get('ob_signal', 'N/A')} (Ratio: {onchain_details.get('orderbook_ratio', 'N/A')})")
        print(f"  Funding: {onchain_details.get('funding_signal', 'N/A')} ({onchain_details.get('funding_rate', 'N/A')})")
        print(f"  On-Chain Score: {onchain_score}/7")
        
        # Technical Analysis (KJo)
        tech_score, tech_details = analyze_technical(coin)
        print(f"\n  [TECHNICAL - KJo]")
        print(f"  RSI: {tech_details.get('rsi', 'N/A')} - {tech_details.get('rsi_signal', 'N/A')}")
        print(f"  MACD: {tech_details.get('macd', 'N/A')} - {tech_details.get('macd_signal', 'N/A')}")
        print(f"  S/R: {tech_details.get('sr_signal', 'N/A')} (Position: {tech_details.get('price_position', 'N/A')})")
        print(f"  Technical Score: {tech_score}/5")
        
        # Combined Score
        total_score = onchain_score + tech_score
        print(f"\n  TOTAL SCORE: {total_score}/12")
        
        # Decision
        if total_score >= ENTRY_THRESHOLD:
            direction = "LONG"
            print(f"  DECISION: ✅ LONG (Score {total_score} >= {ENTRY_THRESHOLD})")
        elif total_score <= -ENTRY_THRESHOLD:
            direction = "SHORT"
            print(f"  DECISION: ✅ SHORT (Score {total_score} <= -{ENTRY_THRESHOLD})")
        else:
            print(f"  DECISION: ⏸️ WNS - Wait and See (Score {total_score} between -{ENTRY_THRESHOLD} and +{ENTRY_THRESHOLD})")
            continue
        
        # Execute trade
        trade_result = execute_trade(exchange, info, coin, direction, current_price)
        
        if trade_result.get("success"):
            trade_result["cvd_score"] = str(onchain_score)
            trade_result["rsi"] = tech_details.get("rsi", "N/A")
            trades_executed.append(trade_result)
            available -= MARGIN_PER_TRADE
            print(f"  ✅ TRADE EXECUTED SUCCESSFULLY!")
        else:
            print(f"  ❌ Trade failed: {trade_result.get('error', 'Unknown')}")
    
    # Save results to trades.json
    save_trades_json(trades_executed, "COMPLETED", "Bot run completed")
    
    print(f"\n{'='*60}")
    print(f"BOT RUN COMPLETE")
    print(f"Trades executed: {len(trades_executed)}")
    print(f"{'='*60}")

# ============================================================
# TRADES.JSON MANAGEMENT
# ============================================================
def save_trades_json(new_trades, status, message):
    """Save trade data to trades.json for dashboard"""
    trades_file = "trades.json"
    
    # Load existing data
    try:
        with open(trades_file, "r") as f:
            data = json.load(f)
    except:
        data = {"mode": "LIVE", "trades": [], "last_update": "", "bot_status": "ACTIVE"}
    
    # Update metadata
    data["mode"] = "LIVE"
    data["last_update"] = get_wib_time().strftime("%Y-%m-%d %H:%M:%S")
    data["bot_status"] = "ACTIVE"
    data["account_wallet"] = MAIN_WALLET
    
    # Add new trades (field names match dashboard JS: signal, entry, tp, sl, time, pnl)
    for trade in new_trades:
        trade_entry = {
            "id": len(data.get("trades", [])) + 1,
            "time": get_wib_time().strftime("%Y-%m-%d %H:%M:%S"),
            "coin": trade["coin"],
            "signal": trade["direction"],
            "entry": trade["entry_price"],
            "tp": trade["tp_price"],
            "sl": trade["sl_price"],
            "size": trade["size"],
            "margin": MARGIN_PER_TRADE,
            "leverage": LEVERAGE,
            "tp_set": trade["tp_set"],
            "sl_set": trade["sl_set"],
            "status": "OPEN",
            "pnl": 0.0,
            "cvd_score": trade.get("cvd_score", "N/A"),
            "rsi": trade.get("rsi", "N/A"),
        }
        data.setdefault("trades", []).append(trade_entry)
    
    # Save
    with open(trades_file, "w") as f:
        json.dump(data, f, indent=2)
    
    print(f"\n  trades.json updated ({len(new_trades)} new trades)")

# ============================================================
# PERFORMANCE TRACKING (Mini update setiap run)
# ============================================================
def update_performance_mini():
    """Update equity curve di performance.json setiap bot run"""
    perf_file = "performance.json"
    
    try:
        with open(perf_file, "r") as f:
            data = json.load(f)
    except:
        data = {
            "total_pnl": 0.0, "wins": 0, "losses": 0,
            "total_trades": 0, "today_trades": 0, "today_pnl": 0.0,
            "win_rate": 0, "avg_profit": 0.0, "best_trade": "--",
            "equity_curve": [], "daily_pnl": [], "closed_trades": [],
            "ai_report": None,
        }
    
    # Get current unrealized P&L from positions
    try:
        spot_payload = {"type": "spotClearinghouseState", "user": MAIN_WALLET}
        spot_resp = requests.post("https://api.hyperliquid.xyz/info", json=spot_payload, timeout=10)
        spot_data = spot_resp.json()
        usdc_balance = 0.0
        for bal in spot_data.get("balances", []):
            if bal.get("coin") == "USDC":
                usdc_balance = float(bal.get("total", 0))
                break
        
        info_temp = Info(constants.MAINNET_API_URL, skip_ws=True)
        user_state = info_temp.user_state(MAIN_WALLET)
        positions = user_state.get("assetPositions", [])
        unrealized = sum(float(p.get("position", {}).get("unrealizedPnl", 0)) for p in positions if float(p.get("position", {}).get("szi", 0)) != 0)
        
        # Add equity point (total_pnl + unrealized)
        current_equity = data.get("total_pnl", 0) + unrealized
        equity_point = {
            "time": get_wib_time().strftime("%H:%M"),
            "equity": round(current_equity, 4),
        }
        data.setdefault("equity_curve", []).append(equity_point)
        data["equity_curve"] = data["equity_curve"][-100:]
        
        with open(perf_file, "w") as f:
            json.dump(data, f, indent=2)
        print(f"\n  performance.json equity updated: ${current_equity:.4f}")
    except Exception as e:
        print(f"\n  performance.json update skipped: {e}")

# ============================================================
# ENTRY POINT
# ============================================================
if __name__ == "__main__":
    run_bot()
    update_performance_mini()
