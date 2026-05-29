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

# Trading Parameters (sesuai strategi almarhum)
WATCHLIST = ["BTC", "ETH", "BNB"]  # Coin yang almarhum kuasai
MARGIN_PER_TRADE = 2.0  # $2 per trade (marking)
LEVERAGE = 10  # 10x leverage
TP_PERCENT = 0.02  # 2% Take Profit
SL_PERCENT = 0.01  # 1% Stop Loss
ENTRY_THRESHOLD = 2  # Minimum score untuk entry

# Size decimals per coin (dari Hyperliquid metadata)
SZ_DECIMALS = {"BTC": 5, "ETH": 4, "BNB": 3}

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
    
    # Calculate TP/SL prices
    if is_buy:  # LONG
        tp_price = int(current_price * (1 + TP_PERCENT))
        sl_price = int(current_price * (1 - SL_PERCENT))
        limit_px = int(current_price + 100)  # Slippage allowance for buy
    else:  # SHORT
        tp_price = int(current_price * (1 - TP_PERCENT))
        sl_price = int(current_price * (1 + SL_PERCENT))
        limit_px = int(current_price - 100)  # Slippage allowance for sell
    
    print(f"\n  EXECUTING {direction} {coin}")
    print(f"  Size: {size} | Margin: ${MARGIN_PER_TRADE} | Leverage: {LEVERAGE}x")
    print(f"  Entry ~${current_price:.2f} | TP: ${tp_price} | SL: ${sl_price}")
    
    # Set leverage first
    try:
        exchange.update_leverage(LEVERAGE, coin)
    except:
        pass
    
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
        result = exchange.bulk_orders(orders)
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
    
    # Analyze each coin
    trades_executed = []
    
    for coin in WATCHLIST:
        if coin in open_coins:
            print(f"\n--- {coin}: SKIP (already has open position) ---")
            continue
        
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
    
    # Add new trades
    for trade in new_trades:
        trade_entry = {
            "id": len(data.get("trades", [])) + 1,
            "timestamp": get_wib_time().strftime("%Y-%m-%d %H:%M:%S"),
            "coin": trade["coin"],
            "direction": trade["direction"],
            "entry_price": trade["entry_price"],
            "tp_price": trade["tp_price"],
            "sl_price": trade["sl_price"],
            "size": trade["size"],
            "margin": MARGIN_PER_TRADE,
            "leverage": LEVERAGE,
            "tp_set": trade["tp_set"],
            "sl_set": trade["sl_set"],
            "status": "OPEN",
        }
        data.setdefault("trades", []).append(trade_entry)
    
    # Save
    with open(trades_file, "w") as f:
        json.dump(data, f, indent=2)
    
    print(f"\n  trades.json updated ({len(new_trades)} new trades)")

# ============================================================
# ENTRY POINT
# ============================================================
if __name__ == "__main__":
    run_bot()
