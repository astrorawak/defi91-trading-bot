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

def send_telegram_message(text):
    """Send message to Telegram"""
    if not TELEGRAM_BOT_TOKEN or not TELEGRAM_CHAT_ID:
        print("Telegram credentials not set. Skipping signal.")
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
            print("Telegram signal sent successfully!")
            return True
        else:
            print(f"Failed to send Telegram signal: {response.text}")
            return False
    except Exception as e:
        print(f"Error sending Telegram signal: {e}")
        return False

def send_trade_signal(coin, side, entry_price, tp_price, sl_price, leverage, margin, cvd_score):
    """Send a new trade signal to Telegram"""
    wib_now = get_wib_time()
    
    side_emoji = "🟢 LONG" if side == "LONG" else "🔴 SHORT"
    
    msg = f"🚨 <b>NEW TRADE SIGNAL</b> 🚨\n"
    msg += f"📅 {wib_now.strftime('%d %b %Y - %H:%M WIB')}\n\n"
    
    msg += f"<b>Coin:</b> #{coin}\n"
    msg += f"<b>Direction:</b> {side_emoji}\n"
    msg += f"<b>Leverage:</b> {leverage}x\n"
    msg += f"<b>Margin:</b> ${margin:.2f}\n\n"
    
    msg += f"<b>Entry Price:</b> {entry_price}\n"
    msg += f"<b>Take Profit (TP):</b> {tp_price} 🎯\n"
    msg += f"<b>Stop Loss (SL):</b> {sl_price} 🛑\n\n"
    
    msg += f"<b>Signal Strength:</b> {cvd_score}/10\n"
    msg += f"<i>(Auto-executed by DeFi91 Bot)</i>\n"
    
    return send_telegram_message(msg)

def send_close_signal(coin, side, exit_price, pnl, reason):
    """Send a trade close signal to Telegram"""
    wib_now = get_wib_time()
    
    side_emoji = "🟢 LONG" if side == "LONG" else "🔴 SHORT"
    pnl_emoji = "✅ PROFIT" if pnl > 0 else "❌ LOSS"
    
    msg = f"🏁 <b>TRADE CLOSED</b> 🏁\n"
    msg += f"📅 {wib_now.strftime('%d %b %Y - %H:%M WIB')}\n\n"
    
    msg += f"<b>Coin:</b> #{coin}\n"
    msg += f"<b>Direction:</b> {side_emoji}\n"
    msg += f"<b>Exit Price:</b> {exit_price}\n\n"
    
    msg += f"<b>Result:</b> {pnl_emoji}\n"
    msg += f"<b>PnL:</b> ${pnl:.2f}\n"
    msg += f"<b>Reason:</b> {reason}\n"
    
    return send_telegram_message(msg)
