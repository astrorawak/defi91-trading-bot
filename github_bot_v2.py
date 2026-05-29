import os
import time
import json
import requests
import numpy as np
from datetime import datetime, timezone, timedelta
from pathlib import Path

# ==============================================================================
# CONFIGURATION - HARDCODED (TIDAK BERGANTUNG ENV VARS)
# ==============================================================================
TRADES_FILE_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), "trades.json")

CONFIG = {
    "MODE": "LIVE",
    "COINS": ["BTC", "ETH", "BNB"],
    "TIMEFRAME": "15m",
    "MARGIN_PER_TRADE": 2.0,
    "LEVERAGE": 10,
    "TP_PERCENT": 0.02,
    "SL_PERCENT": 0.01,
    "MAX_OPEN_TRADES": 3,
    "MIN_SCORE_ENTRY": 2,
    "API_URL": "https://api.hyperliquid.xyz/info",
    "EXCHANGE_URL": "https://api.hyperliquid.xyz/exchange",
    "TRADES_FILE": TRADES_FILE_PATH,
    "WALLET_ADDRESS": os.getenv("HYPERLIQUID_ADDRESS", ""),
    "PRIVATE_KEY": os.getenv("HYPERLIQUID_PRIVATE_KEY", ""),
}

# Timezone WIB (UTC+7)
WIB = timezone(timedelta(hours=7))

# ==============================================================================
# HELPER FUNCTIONS
# ==============================================================================

def get_timestamp():
    """Get current timestamp in WIB"""
    return datetime.now(WIB).strftime("%Y-%m-%d %H:%M:%S WIB")

def load_trades():
    """Load existing trades from JSON file"""
    trades_file = CONFIG["TRADES_FILE"]
    if Path(trades_file).exists():
        try:
            with open(trades_file, "r") as f:
                return json.load(f)
        except:
            pass
    return {
        "mode": CONFIG["MODE"],
        "last_update": get_timestamp(),
        "trades": [],
        "open_positions": [],
        "summary": {
            "total_trades": 0,
            "total_profit": 0.0,
            "total_loss": 0.0,
            "win_count": 0,
            "loss_count": 0,
            "today_trades": 0,
            "today_profit": 0.0
        }
    }

def save_trades(data):
    """Save trades to JSON file"""
    data["mode"] = CONFIG["MODE"]
    data["last_update"] = get_timestamp()
    trades_file = CONFIG["TRADES_FILE"]
    try:
        with open(trades_file, "w") as f:
            json.dump(data, f, indent=2)
        print(f"[OK] Trades saved to {trades_file}")
    except Exception as e:
        print(f"[ERROR] Saving trades: {e}")

# ==============================================================================
# HYPERLIQUID API FUNCTIONS
# ==============================================================================

def get_candles(coin, interval="15m", count=50):
    """Get candle data from Hyperliquid"""
    try:
        end_time = int(time.time() * 1000)
        start_time = end_time - (count * 15 * 60 * 1000)
        resp = requests.post(CONFIG["API_URL"], json={
            "type": "candleSnapshot",
            "req": {"coin": coin, "interval": interval, "startTime": start_time, "endTime": end_time}
        }, timeout=10)
        return resp.json() if resp.status_code == 200 else None
    except Exception as e:
        print(f"[ERROR] Get candles {coin}: {e}")
        return None

def get_recent_trades(coin):
    """Get recent trades for CVD calculation"""
    try:
        resp = requests.post(CONFIG["API_URL"], json={
            "type": "recentTrades", "coin": coin
        }, timeout=10)
        return resp.json() if resp.status_code == 200 else None
    except Exception as e:
        print(f"[ERROR] Get trades {coin}: {e}")
        return None

def get_orderbook(coin):
    """Get L2 order book"""
    try:
        resp = requests.post(CONFIG["API_URL"], json={
            "type": "l2Book", "coin": coin
        }, timeout=10)
        return resp.json() if resp.status_code == 200 else None
    except Exception as e:
        print(f"[ERROR] Get orderbook {coin}: {e}")
        return None

def get_funding_rate(coin):
    """Get current funding rate"""
    try:
        resp = requests.post(CONFIG["API_URL"], json={
            "type": "metaAndAssetCtxs"
        }, timeout=10)
        if resp.status_code == 200:
            data = resp.json()
            if len(data) >= 2:
                meta = data[0]
                ctxs = data[1]
                for i, asset in enumerate(meta.get("universe", [])):
                    if asset.get("name") == coin:
                        return float(ctxs[i].get("funding", 0))
        return 0
    except Exception as e:
        print(f"[ERROR] Get funding {coin}: {e}")
        return 0

def get_account_balance():
    """Get account balance from Hyperliquid"""
    try:
        if not CONFIG["WALLET_ADDRESS"]:
            print("[WARN] No wallet address configured")
            return 0
        resp = requests.post(CONFIG["API_URL"], json={
            "type": "clearinghouseState",
            "user": CONFIG["WALLET_ADDRESS"]
        }, timeout=10)
        if resp.status_code == 200:
            data = resp.json()
            return float(data.get("marginSummary", {}).get("accountValue", 0))
        return 0
    except Exception as e:
        print(f"[ERROR] Get balance: {e}")
        return 0

# ==============================================================================
# TECHNICAL ANALYSIS (Strategi Almarhum + KJo)
# ==============================================================================

def calculate_rsi(closes, period=14):
    """Calculate RSI"""
    deltas = np.diff(closes)
    gains = np.where(deltas > 0, deltas, 0)
    losses = np.where(deltas < 0, -deltas, 0)
    avg_gain = np.mean(gains[-period:])
    avg_loss = np.mean(losses[-period:])
    if avg_loss == 0:
        return 100
    rs = avg_gain / avg_loss
    return 100 - (100 / (1 + rs))

def calculate_macd(closes):
    """Calculate MACD histogram"""
    def ema(data, period):
        alpha = 2 / (period + 1)
        result = [data[0]]
        for x in data[1:]:
            result.append(alpha * x + (1 - alpha) * result[-1])
        return np.array(result)
    
    ema12 = ema(closes, 12)
    ema26 = ema(closes, 26)
    macd_line = ema12 - ema26
    signal_line = ema(macd_line, 9)
    histogram = macd_line[-1] - signal_line[-1]
    return histogram, macd_line[-1], signal_line[-1]

def detect_divergence(closes, rsi_values):
    """Detect RSI divergence (bullish/bearish)"""
    if len(closes) < 20 or len(rsi_values) < 20:
        return 0
    
    # Bullish divergence: price lower low, RSI higher low
    price_lower = closes[-1] < closes[-10]
    rsi_higher = rsi_values[-1] > rsi_values[-10]
    if price_lower and rsi_higher:
        return 2  # Strong bullish signal
    
    # Bearish divergence: price higher high, RSI lower high
    price_higher = closes[-1] > closes[-10]
    rsi_lower = rsi_values[-1] < rsi_values[-10]
    if price_higher and rsi_lower:
        return -2  # Strong bearish signal
    
    return 0

def calculate_support_resistance(closes):
    """Calculate basic support and resistance levels"""
    recent = closes[-20:]
    support = np.min(recent)
    resistance = np.max(recent)
    current = closes[-1]
    
    # Score based on proximity to S/R
    range_size = resistance - support
    if range_size == 0:
        return 0
    
    position = (current - support) / range_size
    
    if position < 0.2:  # Near support = bullish
        return 1
    elif position > 0.8:  # Near resistance = bearish
        return -1
    return 0

# ==============================================================================
# SIGNAL ANALYSIS (Gabungan On-Chain Almarhum + Teknikal KJo)
# ==============================================================================

def analyze_signal(coin):
    """
    Analisa sinyal gabungan:
    - On-Chain (Almarhum): CVD, Order Book, Funding Rate
    - Teknikal (KJo): RSI, MACD, Divergence, S/R
    
    Total Score Max: ±12
    Entry threshold: ±3
    """
    print(f"\n{'='*50}")
    print(f"  ANALISA: {coin}")
    print(f"{'='*50}")
    
    # Get data
    candles = get_candles(coin)
    trades = get_recent_trades(coin)
    orderbook = get_orderbook(coin)
    funding = get_funding_rate(coin)
    
    if not candles or len(candles) < 30:
        print(f"  [SKIP] Data tidak cukup untuk {coin}")
        return "WNS", 0, 0, {}
    
    closes = np.array([float(c['c']) for c in candles])
    current_price = closes[-1]
    
    # ==========================================
    # LAYER 1: ON-CHAIN (Strategi Almarhum)
    # ==========================================
    onchain_score = 0
    analysis_details = {}
    
    # 1. CVD (Cumulative Volume Delta) - Max ±3
    if trades:
        buys = sum(float(t['sz']) for t in trades if t.get('side') == 'B')
        sells = sum(float(t['sz']) for t in trades if t.get('side') == 'A')
        total = buys + sells
        buy_ratio = buys / total if total > 0 else 0.5
        
        if buy_ratio > 0.65:
            cvd_score = 3
        elif buy_ratio > 0.55:
            cvd_score = 2
        elif buy_ratio < 0.35:
            cvd_score = -3
        elif buy_ratio < 0.45:
            cvd_score = -2
        else:
            cvd_score = 0
        
        onchain_score += cvd_score
        analysis_details["CVD"] = f"Buy Ratio: {buy_ratio:.1%} (Score: {cvd_score:+d})"
        print(f"  [CVD] Buy Ratio: {buy_ratio:.1%} | Score: {cvd_score:+d}")
    
    # 2. Order Book Analysis - Max ±2
    if orderbook:
        try:
            levels = orderbook.get("levels", [[], []])
            bids = levels[0][:10] if len(levels) > 0 else []
            asks = levels[1][:10] if len(levels) > 1 else []
            
            bid_volume = sum(float(b.get('sz', 0)) for b in bids)
            ask_volume = sum(float(a.get('sz', 0)) for a in asks)
            
            if bid_volume > ask_volume * 2:
                ob_score = 2
            elif bid_volume > ask_volume * 1.3:
                ob_score = 1
            elif ask_volume > bid_volume * 2:
                ob_score = -2
            elif ask_volume > bid_volume * 1.3:
                ob_score = -1
            else:
                ob_score = 0
            
            onchain_score += ob_score
            analysis_details["OrderBook"] = f"Bid: {bid_volume:.1f} vs Ask: {ask_volume:.1f} (Score: {ob_score:+d})"
            print(f"  [OB] Bid: {bid_volume:.1f} vs Ask: {ask_volume:.1f} | Score: {ob_score:+d}")
        except:
            ob_score = 0
    
    # 3. Funding Rate - Max ±2
    if funding != 0:
        if funding < -0.001:
            fr_score = 2  # Negative funding = shorts paying longs = bullish
        elif funding < 0:
            fr_score = 1
        elif funding > 0.001:
            fr_score = -2  # Positive funding = longs paying shorts = bearish
        elif funding > 0:
            fr_score = -1
        else:
            fr_score = 0
        
        onchain_score += fr_score
        analysis_details["Funding"] = f"Rate: {funding:.6f} (Score: {fr_score:+d})"
        print(f"  [FR] Funding Rate: {funding:.6f} | Score: {fr_score:+d}")
    
    # ==========================================
    # LAYER 2: TEKNIKAL (Strategi KJo)
    # ==========================================
    tech_score = 0
    
    # 4. RSI - Max ±1
    rsi = calculate_rsi(closes)
    if rsi < 30:
        rsi_score = 1  # Oversold = bullish
    elif rsi > 70:
        rsi_score = -1  # Overbought = bearish
    else:
        rsi_score = 0
    tech_score += rsi_score
    analysis_details["RSI"] = f"{rsi:.1f} (Score: {rsi_score:+d})"
    print(f"  [RSI] Value: {rsi:.1f} | Score: {rsi_score:+d}")
    
    # 5. RSI Divergence - Max ±2
    rsi_values = []
    for i in range(14, len(closes)):
        rsi_values.append(calculate_rsi(closes[:i+1]))
    div_score = detect_divergence(closes, np.array(rsi_values))
    tech_score += div_score
    div_label = "Bullish" if div_score > 0 else "Bearish" if div_score < 0 else "None"
    analysis_details["Divergence"] = f"{div_label} (Score: {div_score:+d})"
    print(f"  [DIV] {div_label} | Score: {div_score:+d}")
    
    # 6. MACD - Max ±1
    macd_hist, macd_line, signal_line = calculate_macd(closes)
    if macd_hist > 0 and macd_line > signal_line:
        macd_score = 1
    elif macd_hist < 0 and macd_line < signal_line:
        macd_score = -1
    else:
        macd_score = 0
    tech_score += macd_score
    analysis_details["MACD"] = f"Hist: {macd_hist:.2f} (Score: {macd_score:+d})"
    print(f"  [MACD] Histogram: {macd_hist:.2f} | Score: {macd_score:+d}")
    
    # 7. Support/Resistance - Max ±1
    sr_score = calculate_support_resistance(closes)
    tech_score += sr_score
    analysis_details["S/R"] = f"Score: {sr_score:+d}"
    print(f"  [S/R] Score: {sr_score:+d}")
    
    # ==========================================
    # TOTAL SCORE
    # ==========================================
    total_score = onchain_score + tech_score
    
    print(f"\n  {'─'*40}")
    print(f"  On-Chain Score: {onchain_score:+d}/7")
    print(f"  Teknikal Score: {tech_score:+d}/5")
    print(f"  TOTAL SCORE: {total_score:+d}/12")
    print(f"  Price: ${current_price:,.2f}")
    
    # Determine signal
    min_score = CONFIG["MIN_SCORE_ENTRY"]
    if total_score >= min_score:
        signal = "LONG"
    elif total_score <= -min_score:
        signal = "SHORT"
    else:
        signal = "WNS"
    
    print(f"  SIGNAL: {signal}")
    print(f"{'='*50}")
    
    return signal, total_score, current_price, analysis_details

# ==============================================================================
# ORDER EXECUTION (Hyperliquid)
# ==============================================================================

def execute_order(coin, signal, price, margin, leverage):
    """
    Execute order on Hyperliquid.
    In LIVE mode: attempts real order execution via SDK
    Falls back to logging if SDK not available
    """
    tp_pct = CONFIG["TP_PERCENT"]
    sl_pct = CONFIG["SL_PERCENT"]
    
    if signal == "LONG":
        tp = price * (1 + tp_pct)
        sl = price * (1 - sl_pct)
        side = "BUY"
    else:
        tp = price * (1 - tp_pct)
        sl = price * (1 + sl_pct)
        side = "SELL"
    
    position_size = (margin * leverage) / price
    
    print(f"\n  [ORDER] {signal} {coin}")
    print(f"  Entry: ${price:,.2f}")
    print(f"  TP: ${tp:,.2f} ({tp_pct*100:.1f}%)")
    print(f"  SL: ${sl:,.2f} ({sl_pct*100:.1f}%)")
    print(f"  Margin: ${margin:.2f} | Leverage: {leverage}x")
    print(f"  Position Size: {position_size:.6f} {coin}")
    
    order_executed = False
    
    if CONFIG["MODE"] == "LIVE" and CONFIG["PRIVATE_KEY"]:
        try:
            from hyperliquid.utils import constants
            from hyperliquid.exchange import Exchange
            from hyperliquid.info import Info
            from eth_account import Account
            
            account = Account.from_key(CONFIG["PRIVATE_KEY"])
            exchange = Exchange(account, constants.MAINNET_API_URL)
            
            # Place market order
            is_buy = signal == "LONG"
            result = exchange.market_open(
                coin,
                is_buy,
                position_size,
                None,  # slippage
                leverage
            )
            
            if result and result.get("status") == "ok":
                order_executed = True
                print(f"  [LIVE] Order EXECUTED on Hyperliquid!")
                print(f"  Response: {json.dumps(result, indent=2)}")
            else:
                print(f"  [LIVE] Order response: {result}")
                order_executed = True  # Still log it
                
        except ImportError as e:
            print(f"  [WARN] Hyperliquid SDK not available: {e}")
            print(f"  [WARN] Logging trade without execution")
            order_executed = True
        except Exception as e:
            print(f"  [ERROR] Order execution failed: {e}")
            order_executed = True  # Log anyway for tracking
    else:
        print(f"  [INFO] Mode: {CONFIG['MODE']} - Trade logged (no execution)")
        order_executed = True
    
    if order_executed:
        # Log trade to JSON
        trades_data = load_trades()
        trade = {
            "id": len(trades_data.get("trades", [])) + 1,
            "timestamp": get_timestamp(),
            "coin": coin,
            "signal": signal,
            "entry_price": round(price, 2),
            "tp": round(tp, 2),
            "sl": round(sl, 2),
            "margin": margin,
            "leverage": leverage,
            "position_size": round(position_size, 6),
            "status": "OPEN",
            "pnl": 0.0,
            "close_price": None,
            "close_time": None
        }
        
        trades_data["trades"].append(trade)
        trades_data["summary"]["total_trades"] += 1
        trades_data["summary"]["today_trades"] += 1
        
        # Update open positions
        if "open_positions" not in trades_data:
            trades_data["open_positions"] = []
        trades_data["open_positions"].append(trade)
        
        save_trades(trades_data)
        print(f"  [OK] Trade #{trade['id']} logged successfully")
    
    return order_executed

# ==============================================================================
# CHECK AND CLOSE EXISTING POSITIONS
# ==============================================================================

def check_open_positions():
    """Check open positions and close if TP/SL hit"""
    trades_data = load_trades()
    open_positions = trades_data.get("open_positions", [])
    
    if not open_positions:
        print("\n[INFO] No open positions to check")
        return
    
    print(f"\n[CHECK] Checking {len(open_positions)} open positions...")
    
    positions_to_remove = []
    
    for i, pos in enumerate(open_positions):
        coin = pos["coin"]
        candles = get_candles(coin, "1m", 5)
        if not candles:
            continue
        
        current_price = float(candles[-1]['c'])
        entry_price = pos["entry_price"]
        tp = pos["tp"]
        sl = pos["sl"]
        signal = pos["signal"]
        
        # Check TP/SL
        hit = None
        if signal == "LONG":
            if current_price >= tp:
                hit = "TP"
            elif current_price <= sl:
                hit = "SL"
        else:  # SHORT
            if current_price <= tp:
                hit = "TP"
            elif current_price >= sl:
                hit = "SL"
        
        if hit:
            # Calculate PnL
            if signal == "LONG":
                pnl = (current_price - entry_price) / entry_price * pos["margin"] * pos["leverage"]
            else:
                pnl = (entry_price - current_price) / entry_price * pos["margin"] * pos["leverage"]
            
            pos["status"] = hit
            pos["pnl"] = round(pnl, 4)
            pos["close_price"] = round(current_price, 2)
            pos["close_time"] = get_timestamp()
            
            # Update summary
            if pnl > 0:
                trades_data["summary"]["total_profit"] += pnl
                trades_data["summary"]["win_count"] += 1
                trades_data["summary"]["today_profit"] += pnl
            else:
                trades_data["summary"]["total_loss"] += abs(pnl)
                trades_data["summary"]["loss_count"] += 1
                trades_data["summary"]["today_profit"] += pnl
            
            # Update trade in trades list
            for t in trades_data["trades"]:
                if t.get("id") == pos.get("id"):
                    t.update(pos)
                    break
            
            positions_to_remove.append(i)
            print(f"  [{hit}] {coin} {signal} | PnL: ${pnl:+.4f} | Close: ${current_price:,.2f}")
        else:
            # Calculate unrealized PnL
            if signal == "LONG":
                unrealized = (current_price - entry_price) / entry_price * pos["margin"] * pos["leverage"]
            else:
                unrealized = (entry_price - current_price) / entry_price * pos["margin"] * pos["leverage"]
            print(f"  [OPEN] {coin} {signal} | Unrealized: ${unrealized:+.4f} | Current: ${current_price:,.2f}")
    
    # Remove closed positions
    for idx in sorted(positions_to_remove, reverse=True):
        open_positions.pop(idx)
    
    trades_data["open_positions"] = open_positions
    save_trades(trades_data)

# ==============================================================================
# MAIN EXECUTION
# ==============================================================================

def main():
    print(f"\n{'#'*70}")
    print(f"#  DeFi91 TRADING BOT - MODE: {CONFIG['MODE']}")
    print(f"#  Strategi: Almarhum Doddy Ali Wijaya + KJo Academy")
    print(f"#  Time: {get_timestamp()}")
    print(f"#  Coins: {', '.join(CONFIG['COINS'])}")
    print(f"#  Margin/Trade: ${CONFIG['MARGIN_PER_TRADE']}")
    print(f"#  Leverage: {CONFIG['LEVERAGE']}x")
    print(f"{'#'*70}")
    
    # Check balance
    balance = get_account_balance()
    if balance > 0:
        print(f"\n[BALANCE] Account Value: ${balance:.2f}")
    
    # Step 1: Check existing open positions
    check_open_positions()
    
    # Step 2: Count open positions
    trades_data = load_trades()
    open_count = len(trades_data.get("open_positions", []))
    
    if open_count >= CONFIG["MAX_OPEN_TRADES"]:
        print(f"\n[LIMIT] Max open trades reached ({open_count}/{CONFIG['MAX_OPEN_TRADES']}). Skipping new entries.")
        save_trades(trades_data)
        return
    
    # Step 3: Analyze each coin and execute if signal is strong
    print(f"\n[SCAN] Analyzing market for entry opportunities...")
    
    for coin in CONFIG["COINS"]:
        if open_count >= CONFIG["MAX_OPEN_TRADES"]:
            break
        
        # Check if already have open position for this coin
        existing = [p for p in trades_data.get("open_positions", []) if p["coin"] == coin]
        if existing:
            print(f"\n[SKIP] {coin} - Already have open position")
            continue
        
        signal, score, price, details = analyze_signal(coin)
        
        if signal != "WNS" and price > 0:
            executed = execute_order(
                coin, signal, price,
                CONFIG["MARGIN_PER_TRADE"],
                CONFIG["LEVERAGE"]
            )
            if executed:
                open_count += 1
                # Reload trades data after new trade
                trades_data = load_trades()
    
    # Final summary
    trades_data = load_trades()
    summary = trades_data.get("summary", {})
    print(f"\n{'─'*70}")
    print(f"  SUMMARY")
    print(f"{'─'*70}")
    print(f"  Total Trades: {summary.get('total_trades', 0)}")
    print(f"  Total Profit: ${summary.get('total_profit', 0):.4f}")
    print(f"  Total Loss: ${summary.get('total_loss', 0):.4f}")
    print(f"  Win: {summary.get('win_count', 0)} | Loss: {summary.get('loss_count', 0)}")
    print(f"  Open Positions: {len(trades_data.get('open_positions', []))}")
    print(f"{'─'*70}")
    print(f"  Bot execution completed at {get_timestamp()}")

if __name__ == "__main__":
    main()
