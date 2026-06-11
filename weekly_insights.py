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

def generate_weekly_insights():
    """Generate and send weekly insights"""
    wib_now = get_wib_time()
    
    # Load data
    performance = load_json("performance.json", {})
    trades_data = load_json("trades.json", {"trades": []})
    trades = trades_data.get("trades", []) if isinstance(trades_data, dict) else trades_data
    
    # Calculate weekly stats (last 7 days)
    seven_days_ago = wib_now - timedelta(days=7)
    weekly_trades = []
    
    for t in trades:
        if not isinstance(t, dict) or t.get("status") != "CLOSED":
            continue
            
        time_str = t.get("time", "")
        try:
            trade_time = datetime.strptime(time_str, "%Y-%m-%d %H:%M:%S")
            # Make trade_time timezone-aware (WIB)
            trade_time = trade_time.replace(tzinfo=timezone(timedelta(hours=7)))
            if trade_time >= seven_days_ago:
                weekly_trades.append(t)
        except:
            pass
            
    weekly_pnl = sum(float(t.get("pnl", 0)) for t in weekly_trades)
    weekly_wins = len([t for t in weekly_trades if float(t.get("pnl", 0)) > 0])
    weekly_losses = len([t for t in weekly_trades if float(t.get("pnl", 0)) <= 0])
    weekly_total = weekly_wins + weekly_losses
    weekly_win_rate = (weekly_wins / weekly_total * 100) if weekly_total > 0 else 0
    
    # Analyze best/worst coins
    coin_stats = {}
    for t in weekly_trades:
        coin = t.get("coin")
        pnl = float(t.get("pnl", 0))
        if coin not in coin_stats:
            coin_stats[coin] = 0
        coin_stats[coin] += pnl
        
    sorted_coins = sorted(coin_stats.items(), key=lambda x: x[1], reverse=True)
    best_coin = sorted_coins[0] if sorted_coins else ("None", 0)
    worst_coin = sorted_coins[-1] if sorted_coins else ("None", 0)
    
    # Format message
    msg = f"📈 <b>DeFi91 Weekly Insights</b> 📉\n"
    msg += f"📅 {seven_days_ago.strftime('%d %b')} - {wib_now.strftime('%d %b %Y')}\n\n"
    
    msg += f"<b>Weekly Performance:</b>\n"
    msg += f"💰 PnL: <b>${weekly_pnl:.2f}</b>\n"
    msg += f"🎯 Win Rate: {weekly_win_rate:.1f}%\n"
    msg += f"🔄 Trades: {weekly_total} ({weekly_wins}W / {weekly_losses}L)\n\n"
    
    msg += f"<b>Coin Analysis:</b>\n"
    msg += f"🌟 Best: #{best_coin[0]} (${best_coin[1]:.2f})\n"
    msg += f"⚠️ Worst: #{worst_coin[0]} (${worst_coin[1]:.2f})\n\n"
    
    msg += f"<b>AI Recommendations:</b>\n"
    if weekly_pnl > 0:
        msg += "✅ Strategy is performing well. Maintain current parameters.\n"
    else:
        msg += "🔄 Market conditions are challenging. Consider tightening entry threshold or reducing margin.\n"
        
    if worst_coin[1] < -10:
        msg += f"❌ Consider removing #{worst_coin[0]} from watchlist due to poor performance.\n"
        
    msg += f"\n🔗 <a href='https://astrorawak.github.io/defi91-trading-bot/'>View Full Dashboard</a>"
    
    return send_telegram_message(msg)

if __name__ == "__main__":
    print("Generating Weekly Insights...")
    generate_weekly_insights()
