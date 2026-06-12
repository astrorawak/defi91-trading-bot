import os
import json
import requests
from datetime import datetime, timezone, timedelta

# Konfigurasi Telegram
TELEGRAM_BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN", "8944256953:AAF_gZniabFlHri_cStHseMmr2YdliPSAWQ")
TELEGRAM_CHAT_ID = os.getenv("TELEGRAM_CHAT_ID", "1604558816")
MAIN_WALLET = "0x03562722fE32Ff3BaFE214be3F1828A9157eC23D"

def get_wib_time():
    """Get current time in WIB (UTC+7)"""
    utc_now = datetime.now(timezone.utc)
    wib_now = utc_now + timedelta(hours=7)
    return wib_now

def load_json(filename, default_val):
    try:
        if os.path.exists(filename):
            with open(filename, 'r') as f:
                return json.load(f)
    except Exception as e:
        print(f"Error loading {filename}: {e}")
    return default_val

def get_real_positions():
    """Get REAL open positions from Hyperliquid API (not from trades.json)"""
    try:
        payload = {"type": "clearinghouseState", "user": MAIN_WALLET}
        resp = requests.post("https://api.hyperliquid.xyz/info", json=payload, timeout=10)
        data = resp.json()
        positions = []
        for pos in data.get("assetPositions", []):
            p = pos.get("position", {})
            szi = float(p.get("szi", 0))
            if szi == 0:
                continue
            coin = p.get("coin", "")
            entry_px = float(p.get("entryPx", 0))
            unrealized_pnl = float(p.get("unrealizedPnl", 0))
            leverage = p.get("leverage", {}).get("value", 0)
            side = "LONG" if szi > 0 else "SHORT"
            size_abs = abs(szi)
            margin_used = float(p.get("marginUsed", 0))
            positions.append({
                "coin": coin,
                "side": side,
                "size": size_abs,
                "entry_px": entry_px,
                "pnl": unrealized_pnl,
                "leverage": leverage,
                "margin": margin_used
            })
        return positions
    except Exception as e:
        print(f"Error getting real positions: {e}")
        return []

def get_account_balance():
    """Get USDC balance"""
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

def send_telegram_message(text):
    """Send message to Telegram"""
    if not TELEGRAM_BOT_TOKEN or not TELEGRAM_CHAT_ID:
        print("Telegram credentials not set. Skipping report.")
        return False
        
    url = f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/sendMessage"
    payload = {
        "chat_id": TELEGRAM_CHAT_ID,
        "text": text,
        "parse_mode": "HTML",
        "disable_web_page_preview": True
    }
    
    try:
        response = requests.post(url, json=payload)
        if response.status_code == 200:
            print("Telegram report sent successfully!")
            return True
        else:
            print(f"Failed to send Telegram report: {response.text}")
            return False
    except Exception as e:
        print(f"Error sending Telegram report: {e}")
        return False

def generate_daily_report():
    """Generate and send daily report"""
    wib_now = get_wib_time()
    date_str = wib_now.strftime("%Y-%m-%d")
    
    # Load data
    performance = load_json("performance.json", {})
    market_regime = load_json("market_regime.json", {})
    trades_data = load_json("trades.json", {"trades": []})
    trades = trades_data.get("trades", []) if isinstance(trades_data, dict) else trades_data
    grid_data = load_json("grid_trades.json", {})
    
    # Get real account balance
    balance = get_account_balance()
    
    # Calculate today's stats (only CLOSED trades)
    today_trades = [t for t in trades if isinstance(t, dict) and t.get("time", "").startswith(date_str) and t.get("status") == "CLOSED"]
    today_pnl = sum(float(t.get("pnl", 0)) for t in today_trades)
    today_wins = len([t for t in today_trades if float(t.get("pnl", 0)) > 0])
    today_losses = len([t for t in today_trades if float(t.get("pnl", 0)) <= 0])
    today_closed = today_wins + today_losses
    
    # Get overall stats
    total_pnl = performance.get("total_pnl", 0)
    win_rate = performance.get("win_rate", 0)
    total_trades = performance.get("total_trades", 0)
    
    # Get market regime
    regime = market_regime.get("global_regime", "UNKNOWN")
    regime_emoji = "\U0001f7e2" if regime == "TRENDING" else "\U0001f7e1" if regime == "NEUTRAL" else "\U0001f534"
    
    # Get REAL open positions from Hyperliquid
    real_positions = get_real_positions()
    total_unrealized_pnl = sum(p["pnl"] for p in real_positions)
    
    # === BUILD MESSAGE ===
    msg = f"\U0001f4ca <b>DeFi91 Daily Report</b>\n"
    msg += f"\U0001f4c5 {wib_now.strftime('%d %b %Y - %H:%M WIB')}\n"
    msg += f"{'=' * 28}\n\n"
    
    # Account Overview
    msg += f"\U0001f4b0 <b>Account:</b> ${balance:.2f}\n"
    msg += f"{regime_emoji} <b>Market:</b> {regime}\n\n"
    
    # Today's Performance
    msg += f"<b>\U0001f4c8 Hari Ini:</b>\n"
    pnl_emoji = "\U0001f7e2" if today_pnl >= 0 else "\U0001f534"
    msg += f"  {pnl_emoji} PnL: <b>${today_pnl:+.2f}</b>\n"
    msg += f"  \U0001f504 Trades: {today_closed} ({today_wins}W / {today_losses}L)\n\n"
    
    # Overall Performance
    msg += f"<b>\U0001f3c6 Keseluruhan:</b>\n"
    msg += f"  \U0001f4b5 Total PnL: <b>${total_pnl:.2f}</b>\n"
    msg += f"  \U0001f3af Win Rate: {win_rate:.1f}% ({total_trades} trades)\n\n"
    
    # Grid Bot Stats
    if grid_data and "summary" in grid_data:
        grid_summary = grid_data["summary"]
        grid_pnl = grid_summary.get("total_profit_usd", 0)
        grid_trades_count = grid_summary.get("total_trades_completed", 0)
        active_grids = len([k for k, v in grid_data.get("grid_config", {}).get("pairs", {}).items() if v.get("status") == "active"])
        
        msg += f"<b>\U0001f578\ufe0f Grid Bot:</b>\n"
        msg += f"  PnL: ${grid_pnl:.2f} | Trades: {grid_trades_count}\n"
        msg += f"  Active Grids: {active_grids} pairs\n\n"
    
    # Real Open Positions (from API)
    if real_positions:
        msg += f"<b>\U0001f4cd Posisi Terbuka ({len(real_positions)}):</b>\n"
        msg += f"{'─' * 28}\n"
        
        # Sort by PnL (best first)
        real_positions.sort(key=lambda x: x["pnl"], reverse=True)
        
        for p in real_positions:
            side_emoji = "\U0001f7e2" if p["side"] == "LONG" else "\U0001f534"
            pnl_sign = "+" if p["pnl"] >= 0 else ""
            pnl_color = "\u2705" if p["pnl"] >= 0 else "\u274c"
            msg += f"  {side_emoji} <b>{p['coin']}</b> {p['side']} {p['leverage']}x\n"
            msg += f"     Entry: ${p['entry_px']:.2f} | {pnl_color} {pnl_sign}${p['pnl']:.2f}\n"
        
        msg += f"{'─' * 28}\n"
        unrealized_emoji = "\U0001f7e2" if total_unrealized_pnl >= 0 else "\U0001f534"
        msg += f"  {unrealized_emoji} <b>Unrealized: ${total_unrealized_pnl:+.2f}</b>\n\n"
    else:
        msg += "<i>Tidak ada posisi terbuka saat ini.</i>\n\n"
    
    # Footer
    msg += f"\U0001f517 <a href='https://astrorawak.github.io/defi91-trading-bot/'>Dashboard</a>"
    
    return send_telegram_message(msg)

if __name__ == "__main__":
    print("Generating Telegram Report...")
    generate_daily_report()
