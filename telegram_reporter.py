import os
import json
import requests
from datetime import datetime, timezone, timedelta

# Konfigurasi Telegram
TELEGRAM_BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN", "8944256953:AAF_gZniabFlHri_cStHseMmr2YdliPSAWQ")
TELEGRAM_CHAT_ID = os.getenv("TELEGRAM_CHAT_ID", "1604558816")

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
    
    # Calculate today's stats
    today_trades = [t for t in trades if isinstance(t, dict) and t.get("time", "").startswith(date_str)]
    today_pnl = sum(float(t.get("pnl", 0)) for t in today_trades if t.get("status") == "CLOSED")
    today_wins = len([t for t in today_trades if t.get("status") == "CLOSED" and float(t.get("pnl", 0)) > 0])
    today_losses = len([t for t in today_trades if t.get("status") == "CLOSED" and float(t.get("pnl", 0)) <= 0])
    today_closed = today_wins + today_losses
    
    # Get overall stats
    total_pnl = performance.get("total_pnl", 0)
    win_rate = performance.get("win_rate", 0)
    
    # Get market regime
    regime = market_regime.get("global_regime", "UNKNOWN")
    regime_emoji = "🟢" if regime == "TRENDING" else "🟡" if regime == "NEUTRAL" else "🔴"
    
    # Format message
    msg = f"📊 <b>DeFi91 Daily Report</b>\n"
    msg += f"📅 {wib_now.strftime('%d %b %Y - %H:%M WIB')}\n\n"
    
    msg += f"<b>Market Status:</b> {regime_emoji} {regime}\n\n"
    
    msg += f"<b>Today's Performance:</b>\n"
    msg += f"💰 PnL: <b>${today_pnl:.2f}</b>\n"
    msg += f"🔄 Trades: {today_closed} closed\n"
    msg += f"✅ Wins: {today_wins} | ❌ Losses: {today_losses}\n\n"
    
    msg += f"<b>Overall Performance:</b>\n"
    msg += f"🏆 Total PnL: <b>${total_pnl:.2f}</b>\n"
    msg += f"🎯 Win Rate: {win_rate:.1f}%\n\n"
    
    # Get open positions
    open_positions = [t for t in trades if t.get("status") == "OPEN"]
    if open_positions:
        msg += f"<b>Open Positions ({len(open_positions)}):</b>\n"
        for p in open_positions:
            coin = p.get("coin", "")
            side = p.get("side", "")
            side_emoji = "📈" if side == "LONG" else "📉"
            msg += f"{side_emoji} {coin} @ {p.get('entry_price', 0)}\n"
    else:
        msg += "<i>No open positions currently.</i>\n"
        
    msg += f"\n🔗 <a href='https://astrorawak.github.io/defi91-trading-bot/'>View Full Dashboard</a>"
    
    return send_telegram_message(msg)

if __name__ == "__main__":
    print("Generating Telegram Report...")
    generate_daily_report()
