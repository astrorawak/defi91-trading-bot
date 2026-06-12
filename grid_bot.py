import json
import time
import os
import numpy as np
import requests
from datetime import datetime, timezone
from eth_account import Account
from hyperliquid.info import Info
from hyperliquid.exchange import Exchange
from hyperliquid.utils import constants

# --- CONFIGURATION ---
GRID_PAIRS = ["BTC", "ETH", "SOL", "ZEC", "CRV", "ENA", "TON", "ADA", "FARTCOIN", "LIT", "VVV"]
GRID_LEVELS = 5
GRID_LEVERAGE = 5
GRID_TOTAL_BUDGET = 25.0 # Budget untuk grid bot
GRID_RANGE_MULTIPLIER = 2.0
GRID_MIN_PROFIT_PER_GRID = 0.15
MIN_ACCOUNT_BALANCE = 20.0 # Safety buffer untuk scalping bot

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
# Agent wallet address differs from main account address on Hyperliquid
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
        usdc_balance = 0.0
        for bal in spot_data.get("balances", []):
            if bal.get("coin") == "USDC":
                usdc_balance = float(bal.get("total", 0))
                break
        return usdc_balance
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
        
        tr1 = high - low
        tr2 = abs(high - prev_close)
        tr3 = abs(low - prev_close)
        tr = max(tr1, tr2, tr3)
        tr_list.append(tr)
        
    return sum(tr_list) / len(tr_list)

def get_meta():
    try:
        meta = info.meta()
        return meta.get("universe", [])
    except Exception as e:
        print(f"Error getting meta: {e}")
        return []

def format_price(price, sz_decimals):
    if price < 1:
        return f"{price:.5g}"
    elif price < 10:
        return f"{price:.4f}"
    elif price < 100:
        return f"{price:.3f}"
    elif price < 1000:
        return f"{price:.2f}"
    else:
        return f"{price:.1f}"

def format_size(size, sz_decimals):
    return round(size, sz_decimals)

def setup_grid(coin, current_price, atr, meta_info):
    sz_decimals = meta_info.get("szDecimals", 0)
    
    grid_range = atr * GRID_RANGE_MULTIPLIER
    grid_upper = current_price + grid_range
    grid_lower = current_price - grid_range
    grid_interval = (grid_upper - grid_lower) / (GRID_LEVELS * 2)
    
    budget_per_pair = GRID_TOTAL_BUDGET / len(GRID_PAIRS)
    budget_per_level = budget_per_pair / (GRID_LEVELS * 2)
    size_per_level = (budget_per_level * GRID_LEVERAGE) / current_price
    size_per_level = format_size(size_per_level, sz_decimals)
    
    if size_per_level <= 0:
        print(f"Size too small for {coin}, skipping grid setup.")
        return None
        
    print(f"Setting up grid for {coin}: Center={current_price}, Range={grid_lower:.4f}-{grid_upper:.4f}, Interval={grid_interval:.4f}, Size={size_per_level}")
    
    try:
        exchange.update_leverage(GRID_LEVERAGE, coin)
    except Exception as e:
        print(f"Error setting leverage for {coin}: {e}")
        
    orders_to_place = []
    
    for i in range(1, GRID_LEVELS + 1):
        price = current_price - (grid_interval * i)
        orders_to_place.append({
            "coin": coin,
            "is_buy": True,
            "sz": size_per_level,
            "limit_px": format_price(price, sz_decimals),
            "order_type": {"limit": {"tif": "Gtc"}},
            "reduce_only": False
        })
        
    for i in range(1, GRID_LEVELS + 1):
        price = current_price + (grid_interval * i)
        orders_to_place.append({
            "coin": coin,
            "is_buy": False,
            "sz": size_per_level,
            "limit_px": format_price(price, sz_decimals),
            "order_type": {"limit": {"tif": "Gtc"}},
            "reduce_only": False
        })
        
    placed_orders = []
    if orders_to_place:
        try:
            result = exchange.bulk_orders(orders_to_place)
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
        except Exception as e:
            print(f"Error placing bulk orders for {coin}: {e}")
            
    return {
        "grid_center": current_price,
        "grid_upper": grid_upper,
        "grid_lower": grid_lower,
        "grid_interval": grid_interval,
        "size_per_level": size_per_level,
        "status": "active",
        "placed_orders": placed_orders
    }

def manage_grid(coin, grid_config, active_orders, current_price, meta_info):
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
            print(f"Order {order_id} for {coin} ({order['side']} @ {order['price']}) was filled!")
            
            interval = grid_config["grid_interval"]
            size = order["size"]
            
            if order["side"] == "buy":
                new_price = order["price"] + interval
                new_side = False
                profit = 0
            else:
                new_price = order["price"] - interval
                new_side = True
                profit = (order["price"] - new_price) * size
                
                completed_trades.append({
                    "pair": coin,
                    "buy_price": new_price,
                    "sell_price": order["price"],
                    "size": size,
                    "profit_usd": profit,
                    "completed_at": datetime.now(timezone.utc).isoformat()
                })
                print(f"  -> Profit locked: ${profit:.4f}")
                send_grid_telegram(
                    f"\U0001f578\ufe0f <b>Grid Bot - Trade Completed!</b>\n"
                    f"Pair: <b>{coin}</b>\n"
                    f"Buy: ${new_price:.4f} -> Sell: ${order['price']:.4f}\n"
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
    print("Starting Grid Bot...")
    regime = get_market_regime()
    print(f"Current Market Regime: {regime}")
    
    grid_data = load_grid_data()
    
    if regime == "TRENDING":
        print("Market is TRENDING. Grid bot standby. Scalping bot is active.")
        send_grid_telegram("\U0001f578\ufe0f <b>Grid Bot Status:</b> STANDBY\nMarket is TRENDING - Scalping bot is active.")
    else:
        print("Market is SIDEWAYS/CHOPSAW. Grid bot active.")
        send_grid_telegram(f"\U0001f578\ufe0f <b>Grid Bot Status:</b> ACTIVE\nMarket: {regime} - Grid bot scanning for opportunities.")
    
    balance = get_account_balance()
    print(f"Current Account Balance: ${balance:.2f}")
    
    if balance < MIN_ACCOUNT_BALANCE:
        print(f"Safety stop: balance too low (${balance:.2f} < ${MIN_ACCOUNT_BALANCE:.2f})")
        return
        
    try:
        all_mids = info.all_mids()
        universe = get_meta()
        meta_dict = {m["name"]: m for m in universe}
    except Exception as e:
        print(f"Error getting market data: {e}")
        return
        
    for coin in GRID_PAIRS:
        if coin not in all_mids or coin not in meta_dict:
            continue
            
        current_price = float(all_mids[coin])
        meta_info = meta_dict[coin]
        
        coin_config = grid_data["grid_config"]["pairs"].get(coin)
        
        if not coin_config or coin_config.get("status") != "active":
            if regime == "TRENDING":
                continue
                
            candles = get_candles(coin)
            atr = calculate_atr(candles)
            
            if atr > 0:
                setup_result = setup_grid(coin, current_price, atr, meta_info)
                if setup_result:
                    grid_data["grid_config"]["pairs"][coin] = setup_result
                    grid_data["active_orders"].extend(setup_result.pop("placed_orders", []))
        else:
            upper = coin_config["grid_upper"]
            lower = coin_config["grid_lower"]
            
            if current_price > upper * 1.1 or current_price < lower * 0.9:
                print(f"Price for {coin} out of grid bounds. Rebalancing...")
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
                        setup_result = setup_grid(coin, current_price, atr, meta_info)
                        if setup_result:
                            grid_data["grid_config"]["pairs"][coin] = setup_result
                            grid_data["active_orders"].extend(setup_result.pop("placed_orders", []))
                else:
                    grid_data["grid_config"]["pairs"][coin]["status"] = "inactive"
            else:
                new_active, completed = manage_grid(coin, coin_config, grid_data["active_orders"], current_price, meta_info)
                grid_data["active_orders"] = new_active
                
                if completed:
                    grid_data["completed_trades"].extend(completed)
                    for trade in completed:
                        grid_data["summary"]["total_profit_usd"] += trade["profit_usd"]
                        grid_data["summary"]["total_trades_completed"] += 1
                        
    grid_data["grid_config"]["last_updated"] = datetime.now(timezone.utc).isoformat()
    save_grid_data(grid_data)
    print("Grid Bot execution completed.")

if __name__ == "__main__":
    main()
