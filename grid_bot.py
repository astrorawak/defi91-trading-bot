import json
import time
import os
import requests
from datetime import datetime, timezone
from eth_account import Account
from hyperliquid.info import Info
from hyperliquid.exchange import Exchange
from hyperliquid.utils import constants

# --- CONFIGURATION ---
# Koin kandidat grid (akan di-filter otomatis berdasarkan budget)
GRID_CANDIDATES = [] # BOT OFF
# OLD_GRID_CANDIDATES = ["ETH", "XRP", "SOL", "SUI", "BNB", "VVV"]  # Hanya koin proven profitable
MAX_GRID_PAIRS = 3  # Maksimal 3 koin aktif grid sekaligus
GRID_LEVELS = 3  # 3 buy + 3 sell = 6 orders per koin
GRID_LEVERAGE = 5
GRID_TOTAL_BUDGET = 20.0  # Budget untuk grid bot (sisakan buffer)
GRID_RANGE_MULTIPLIER = 1.5  # ATR multiplier untuk range
MIN_ACCOUNT_BALANCE = 15.0  # Safety buffer - diturunkan untuk recovery mode

# Telegram
TELEGRAM_BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN", "")
TELEGRAM_CHAT_ID = os.getenv("TELEGRAM_CHAT_ID", "")

def send_grid_telegram(msg):
    """Send grid bot notification to Telegram"""
    if not TELEGRAM_BOT_TOKEN or not TELEGRAM_CHAT_ID:
        return
    try:
        url = f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/sendMessage"
        payload = {"chat_id": TELEGRAM_CHAT_ID, "text": msg, "parse_mode": "HTML", "disable_web_page_preview": True}
        requests.post(url, json=payload, timeout=10)
    except:
        pass

# --- INITIALIZATION ---
PRIVATE_KEY = os.getenv("HYPERLIQUID_PRIVATE_KEY", "")
if not PRIVATE_KEY:
    print("ERROR: HYPERLIQUID_PRIVATE_KEY not set!")
    exit(1)

account = Account.from_key(PRIVATE_KEY)
# Use hardcoded main wallet address (same as scalping bot)
MAIN_WALLET = "0x03562722fE32Ff3BaFE214be3F1828A9157eC23D"
print(f"Using wallet: {MAIN_WALLET}")

info = Info(constants.MAINNET_API_URL, skip_ws=True)
exchange = Exchange(account, constants.MAINNET_API_URL)

def get_market_regime():
    try:
        if os.path.exists("market_regime.json"):
            with open("market_regime.json", "r") as f:
                data = json.load(f)
                return data.get("global_regime", "UNKNOWN")
    except Exception as e:
        print(f"Error reading market regime: {e}")
    return "UNKNOWN"

def get_account_balance():
    """Get USDC balance from Unified Account (spotClearinghouseState)"""
    try:
        spot_payload = {"type": "spotClearinghouseState", "user": MAIN_WALLET}
        spot_resp = requests.post("https://api.hyperliquid.xyz/info", json=spot_payload, timeout=10)
        spot_data = spot_resp.json()
        for bal in spot_data.get("balances", []):
            if bal.get("coin") == "USDC":
                return float(bal.get("total", 0))
    except Exception as e:
        print(f"Error getting balance: {e}")
    return 0.0

def load_grid_data():
    if os.path.exists("grid_trades.json"):
        try:
            with open("grid_trades.json", "r") as f:
                return json.load(f)
        except Exception as e:
            print(f"Error loading grid data: {e}")
    return {
        "grid_config": {"last_updated": "", "pairs": {}},
        "active_orders": [],
        "completed_trades": [],
        "summary": {
            "total_profit_usd": 0.0,
            "total_trades_completed": 0,
            "total_grids_executed": 0,
            "start_date": datetime.now(timezone.utc).strftime("%Y-%m-%d")
        }
    }

def save_grid_data(data):
    try:
        with open("grid_trades.json", "w") as f:
            json.dump(data, f, indent=2)
    except Exception as e:
        print(f"Error saving grid data: {e}")

def get_candles(coin, interval="1h", lookback=24):
    try:
        end_time = int(time.time() * 1000)
        start_time = end_time - (lookback * 60 * 60 * 1000)
        payload = {
            "type": "candleSnapshot",
            "req": {
                "coin": coin,
                "interval": interval,
                "startTime": start_time,
                "endTime": end_time
            }
        }
        response = requests.post("https://api.hyperliquid.xyz/info", json=payload, timeout=10)
        if response.status_code == 200:
            return response.json()
    except Exception as e:
        print(f"Error fetching candles for {coin}: {e}")
    return []

def calculate_atr(candles):
    if not candles or len(candles) < 2:
        return 0
    tr_list = []
    for i in range(1, len(candles)):
        high = float(candles[i]["h"])
        low = float(candles[i]["l"])
        prev_close = float(candles[i-1]["c"])
        tr = max(high - low, abs(high - prev_close), abs(low - prev_close))
        tr_list.append(tr)
    return sum(tr_list) / len(tr_list)

def get_meta():
    try:
        meta = info.meta()
        return meta.get("universe", [])
    except Exception as e:
        print(f"Error getting meta: {e}")
        return []

def calculate_min_order_value(coin, price, meta_info):
    """Calculate minimum order value based on szDecimals and price"""
    sz_decimals = meta_info.get("szDecimals", 0)
    # Minimum size is 1 unit at the smallest decimal
    min_size = 10 ** (-sz_decimals) if sz_decimals > 0 else 1
    min_value = min_size * price / GRID_LEVERAGE
    return min_value, min_size, sz_decimals

def select_best_pairs(all_mids, meta_dict):
    """Select pairs that can actually be traded with our budget"""
    budget_per_pair = GRID_TOTAL_BUDGET / MAX_GRID_PAIRS
    budget_per_level = budget_per_pair / (GRID_LEVELS * 2)  # buy + sell levels
    
    eligible_pairs = []
    
    for coin in GRID_CANDIDATES:
        if coin not in all_mids or coin not in meta_dict:
            continue
            
        price = float(all_mids[coin])
        meta_info = meta_dict[coin]
        min_value, min_size, sz_decimals = calculate_min_order_value(coin, price, meta_info)
        
        # Calculate actual size we can afford per level
        size_per_level = (budget_per_level * GRID_LEVERAGE) / price
        rounded_size = round(size_per_level, sz_decimals)
        
        # Check if we can afford at least minimum size
        if rounded_size >= min_size and rounded_size > 0:
            # Calculate actual margin needed per level
            actual_margin = (rounded_size * price) / GRID_LEVERAGE
            eligible_pairs.append({
                "coin": coin,
                "price": price,
                "sz_decimals": sz_decimals,
                "min_size": min_size,
                "rounded_size": rounded_size,
                "margin_per_level": actual_margin,
                "meta_info": meta_info
            })
            print(f"  [ELIGIBLE] {coin}: price=${price:.4f}, size={rounded_size}, margin/level=${actual_margin:.3f}")
        else:
            print(f"  [SKIP] {coin}: price=${price:.4f}, need size={size_per_level:.6f} but min={min_size} (szDec={sz_decimals})")
    
    # Sort by margin efficiency (lowest margin per level first = most affordable)
    eligible_pairs.sort(key=lambda x: x["margin_per_level"])
    
    return eligible_pairs[:MAX_GRID_PAIRS]

def setup_grid(coin, current_price, atr, meta_info, size_per_level):
    """Setup grid with pre-calculated size"""
    sz_decimals = meta_info.get("szDecimals", 0)
    
    grid_range = atr * GRID_RANGE_MULTIPLIER
    grid_upper = current_price + grid_range
    grid_lower = current_price - grid_range
    grid_interval = (grid_upper - grid_lower) / (GRID_LEVELS * 2)
    
    if grid_interval <= 0:
        print(f"Grid interval too small for {coin}, skipping.")
        return None
    
    print(f"  Setting up grid for {coin}:")
    print(f"    Center: ${current_price:.4f}")
    print(f"    Range: ${grid_lower:.4f} - ${grid_upper:.4f}")
    print(f"    Interval: ${grid_interval:.4f}")
    print(f"    Size/level: {size_per_level}")
    print(f"    Levels: {GRID_LEVELS} buy + {GRID_LEVELS} sell")
    
    try:
        exchange.update_leverage(GRID_LEVERAGE, coin)
    except Exception as e:
        print(f"  Error setting leverage for {coin}: {e}")
        
    orders_to_place = []
    
    # Buy orders below current price
    for i in range(1, GRID_LEVELS + 1):
        price = current_price - (grid_interval * i)
        px_str = format_price(price, sz_decimals)
        orders_to_place.append({
            "coin": coin,
            "is_buy": True,
            "sz": size_per_level,
            "limit_px": px_str,
            "order_type": {"limit": {"tif": "Gtc"}},
            "reduce_only": False
        })
        
    # Sell orders above current price
    for i in range(1, GRID_LEVELS + 1):
        price = current_price + (grid_interval * i)
        px_str = format_price(price, sz_decimals)
        orders_to_place.append({
            "coin": coin,
            "is_buy": False,
            "sz": size_per_level,
            "limit_px": px_str,
            "order_type": {"limit": {"tif": "Gtc"}},
            "reduce_only": False
        })
    
    placed_orders = []
    if orders_to_place:
        try:
            result = exchange.bulk_orders(orders_to_place)
            print(f"  Bulk order result: {result}")
            if isinstance(result, dict) and result.get("status") == "ok":
                statuses = result.get("response", {}).get("data", {}).get("statuses", [])
                for i, status in enumerate(statuses):
                    if "resting" in status:
                        oid = status["resting"]["oid"]
                        placed_orders.append({
                            "pair": coin,
                            "side": "buy" if orders_to_place[i]["is_buy"] else "sell",
                            "price": float(orders_to_place[i]["limit_px"]),
                            "size": orders_to_place[i]["sz"],
                            "order_id": oid,
                            "placed_at": datetime.now(timezone.utc).isoformat(),
                            "status": "open"
                        })
                    elif "filled" in status:
                        placed_orders.append({
                            "pair": coin,
                            "side": "buy" if orders_to_place[i]["is_buy"] else "sell",
                            "price": float(orders_to_place[i]["limit_px"]),
                            "size": orders_to_place[i]["sz"],
                            "order_id": status["filled"]["oid"],
                            "placed_at": datetime.now(timezone.utc).isoformat(),
                            "status": "filled"
                        })
                    elif "error" in status:
                        print(f"  Order error for {coin}: {status['error']}")
                        
                print(f"  Successfully placed {len(placed_orders)} orders for {coin}")
            else:
                print(f"  Unexpected result format: {result}")
        except Exception as e:
            print(f"  Error placing bulk orders for {coin}: {e}")
    
    if not placed_orders:
        print(f"  No orders placed for {coin}")
        return None
            
    # Send Telegram notification
    send_grid_telegram(
        f"\U0001f578\ufe0f <b>Grid Bot - New Grid Setup!</b>\n"
        f"Pair: <b>{coin}</b>\n"
        f"Range: ${grid_lower:.4f} - ${grid_upper:.4f}\n"
        f"Levels: {GRID_LEVELS}B + {GRID_LEVELS}S\n"
        f"Size: {size_per_level}/level\n"
        f"Orders placed: {len(placed_orders)}"
    )
    
    return {
        "grid_center": current_price,
        "grid_upper": grid_upper,
        "grid_lower": grid_lower,
        "grid_interval": grid_interval,
        "size_per_level": size_per_level,
        "status": "active",
        "placed_orders": placed_orders
    }

def format_price(price, sz_decimals):
    """Format price appropriately"""
    if price < 0.001:
        return f"{price:.6g}"
    elif price < 1:
        return f"{price:.5g}"
    elif price < 10:
        return f"{price:.4f}"
    elif price < 100:
        return f"{price:.3f}"
    elif price < 1000:
        return f"{price:.2f}"
    else:
        return f"{price:.1f}"

def manage_grid(coin, grid_config, active_orders, current_price, meta_info):
    """Check if any grid orders were filled and place opposite orders"""
    sz_decimals = meta_info.get("szDecimals", 0)
    
    try:
        fe_payload = {"type": "frontendOpenOrders", "user": MAIN_WALLET}
        fe_resp = requests.post("https://api.hyperliquid.xyz/info", json=fe_payload, timeout=10)
        api_open_orders = fe_resp.json()
    except Exception as e:
        print(f"Error getting open orders for {coin}: {e}")
        return active_orders, []
        
    api_order_ids = [str(o.get("oid")) for o in api_open_orders if o.get("coin") == coin]
    
    new_active_orders = []
    completed_trades = []
    orders_to_place = []
    
    for order in active_orders:
        if order["pair"] != coin:
            new_active_orders.append(order)
            continue
            
        order_id = str(order["order_id"])
        
        if order_id not in api_order_ids:
            # Order was filled!
            print(f"  Order {order_id} for {coin} ({order['side']} @ {order['price']}) was filled!")
            
            interval = grid_config["grid_interval"]
            size = order["size"]
            
            if order["side"] == "buy":
                new_price = order["price"] + interval
                new_side = False  # sell
                profit = 0
            else:
                new_price = order["price"] - interval
                new_side = True  # buy
                profit = (order["price"] - new_price) * size
                
                completed_trades.append({
                    "pair": coin,
                    "buy_price": new_price,
                    "sell_price": order["price"],
                    "size": size,
                    "profit_usd": profit,
                    "completed_at": datetime.now(timezone.utc).isoformat()
                })
                print(f"    -> Profit locked: ${profit:.4f}")
                send_grid_telegram(
                    f"\U0001f578\ufe0f <b>Grid Bot - Trade Completed!</b>\n"
                    f"Pair: <b>{coin}</b>\n"
                    f"Buy: ${new_price:.4f} -> Sell: ${order['price']:.4f}\n"
                    f"Size: {size}\n"
                    f"Profit: <b>+${profit:.4f}</b>"
                )
                
            orders_to_place.append({
                "coin": coin,
                "is_buy": new_side,
                "sz": size,
                "limit_px": format_price(new_price, sz_decimals),
                "order_type": {"limit": {"tif": "Gtc"}},
                "reduce_only": False
            })
        else:
            new_active_orders.append(order)
            
    if orders_to_place:
        try:
            result = exchange.bulk_orders(orders_to_place)
            if isinstance(result, dict) and result.get("status") == "ok":
                statuses = result.get("response", {}).get("data", {}).get("statuses", [])
                for i, status in enumerate(statuses):
                    if "resting" in status:
                        oid = status["resting"]["oid"]
                        new_active_orders.append({
                            "pair": coin,
                            "side": "buy" if orders_to_place[i]["is_buy"] else "sell",
                            "price": float(orders_to_place[i]["limit_px"]),
                            "size": orders_to_place[i]["sz"],
                            "order_id": oid,
                            "placed_at": datetime.now(timezone.utc).isoformat(),
                            "status": "open"
                        })
        except Exception as e:
            print(f"Error placing opposite orders for {coin}: {e}")
            
    return new_active_orders, completed_trades

def main():
    print("=" * 40)
    print("Starting Grid Bot...")
    print("=" * 40)
    
    regime = get_market_regime()
    print(f"Market Regime: {regime}")
    
    grid_data = load_grid_data()
    
    # Grid bot only active when market is NOT trending
    if regime == "TRENDING":
        print("Market is TRENDING. Grid bot on STANDBY.")
        send_grid_telegram("\U0001f578\ufe0f <b>Grid Bot:</b> STANDBY\nMarket TRENDING - letting scalping bot work.")
        # Still manage existing grids but don't open new ones
    else:
        print(f"Market is {regime}. Grid bot ACTIVE.")
    
    balance = get_account_balance()
    print(f"Account Balance: ${balance:.2f}")
    
    if balance < MIN_ACCOUNT_BALANCE:
        print(f"SAFETY STOP: Balance ${balance:.2f} < minimum ${MIN_ACCOUNT_BALANCE:.2f}")
        print("Protecting scalping bot's margin. Grid bot will not trade.")
        return
    
    # Get market data
    try:
        all_mids = info.all_mids()
        universe = get_meta()
        meta_dict = {m["name"]: m for m in universe}
    except Exception as e:
        print(f"Error getting market data: {e}")
        return
    
    # Select best pairs that we can actually afford
    print("\nSelecting eligible pairs...")
    eligible_pairs = select_best_pairs(all_mids, meta_dict)
    
    if not eligible_pairs:
        print("No eligible pairs found with current budget. Grid bot idle.")
        save_grid_data(grid_data)
        return
    
    print(f"\nSelected {len(eligible_pairs)} pairs for grid trading:")
    for p in eligible_pairs:
        print(f"  - {p['coin']}: ${p['price']:.4f}, size={p['rounded_size']}, margin/lvl=${p['margin_per_level']:.3f}")
    
    # Process each eligible pair
    for pair_info in eligible_pairs:
        coin = pair_info["coin"]
        current_price = pair_info["price"]
        meta_info = pair_info["meta_info"]
        size_per_level = pair_info["rounded_size"]
        
        coin_config = grid_data["grid_config"]["pairs"].get(coin)
        
        if not coin_config or coin_config.get("status") != "active":
            # No active grid for this coin - set up new one (only if not trending)
            if regime == "TRENDING":
                continue
                
            candles = get_candles(coin)
            atr = calculate_atr(candles)
            
            if atr > 0:
                print(f"\n  Setting up new grid for {coin}...")
                setup_result = setup_grid(coin, current_price, atr, meta_info, size_per_level)
                if setup_result:
                    placed = setup_result.pop("placed_orders", [])
                    grid_data["grid_config"]["pairs"][coin] = setup_result
                    grid_data["active_orders"].extend(placed)
                    grid_data["summary"]["total_grids_executed"] += 1
            else:
                print(f"  ATR=0 for {coin}, skipping.")
        else:
            # Existing active grid - manage it
            upper = coin_config["grid_upper"]
            lower = coin_config["grid_lower"]
            
            if current_price > upper * 1.1 or current_price < lower * 0.9:
                print(f"\n  {coin} price out of grid bounds. Rebalancing...")
                # Cancel all orders for this coin
                orders_to_cancel = [o for o in grid_data["active_orders"] if o["pair"] == coin]
                for o in orders_to_cancel:
                    try:
                        exchange.cancel(coin, o["order_id"])
                    except:
                        pass
                        
                grid_data["active_orders"] = [o for o in grid_data["active_orders"] if o["pair"] != coin]
                
                if regime != "TRENDING":
                    candles = get_candles(coin)
                    atr = calculate_atr(candles)
                    if atr > 0:
                        setup_result = setup_grid(coin, current_price, atr, meta_info, size_per_level)
                        if setup_result:
                            placed = setup_result.pop("placed_orders", [])
                            grid_data["grid_config"]["pairs"][coin] = setup_result
                            grid_data["active_orders"].extend(placed)
                else:
                    grid_data["grid_config"]["pairs"][coin]["status"] = "inactive"
            else:
                # Manage existing grid - check for filled orders
                new_active, completed = manage_grid(coin, coin_config, grid_data["active_orders"], current_price, meta_info)
                grid_data["active_orders"] = new_active
                
                if completed:
                    grid_data["completed_trades"].extend(completed)
                    for trade in completed:
                        grid_data["summary"]["total_profit_usd"] += trade["profit_usd"]
                        grid_data["summary"]["total_trades_completed"] += 1
    
    # Also manage grids for coins that are already active but not in current eligible list
    active_grid_coins = [c for c, v in grid_data["grid_config"]["pairs"].items() if v.get("status") == "active"]
    for coin in active_grid_coins:
        if coin not in [p["coin"] for p in eligible_pairs]:
            if coin in all_mids and coin in meta_dict:
                current_price = float(all_mids[coin])
                meta_info = meta_dict[coin]
                coin_config = grid_data["grid_config"]["pairs"][coin]
                new_active, completed = manage_grid(coin, coin_config, grid_data["active_orders"], current_price, meta_info)
                grid_data["active_orders"] = new_active
                if completed:
                    grid_data["completed_trades"].extend(completed)
                    for trade in completed:
                        grid_data["summary"]["total_profit_usd"] += trade["profit_usd"]
                        grid_data["summary"]["total_trades_completed"] += 1
                        
    grid_data["grid_config"]["last_updated"] = datetime.now(timezone.utc).isoformat()
    save_grid_data(grid_data)
    
    print(f"\n{'=' * 40}")
    print(f"Grid Bot Summary:")
    print(f"  Active grids: {len([c for c, v in grid_data['grid_config']['pairs'].items() if v.get('status') == 'active'])}")
    print(f"  Active orders: {len(grid_data['active_orders'])}")
    print(f"  Total profit: ${grid_data['summary']['total_profit_usd']:.4f}")
    print(f"  Total trades: {grid_data['summary']['total_trades_completed']}")
    print(f"{'=' * 40}")

if __name__ == "__main__":
    main()
