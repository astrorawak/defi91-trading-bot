"""
DeFi91 AI Daily Performance Report
Berjalan setiap hari jam 13:00 WIB (06:00 UTC)
Menganalisa performa trading 24 jam terakhir dan menghasilkan laporan AI
"""

import json
import os
import requests
import time
from datetime import datetime, timezone, timedelta
from eth_account import Account
from hyperliquid.info import Info
from hyperliquid.utils import constants

# Config
PRIVATE_KEY = os.getenv("HYPERLIQUID_PRIVATE_KEY", "")
MAIN_WALLET = "0x03562722fE32Ff3BaFE214be3F1828A9157eC23D"
OPENAI_API_KEY = os.getenv("OPENAI_API_KEY", "")
WIB = timezone(timedelta(hours=7))

def get_wib_time():
    return datetime.now(WIB)

def get_account_data():
    """Get current account state"""
    info = Info(constants.MAINNET_API_URL, skip_ws=True)
    
    # Unified Account balance
    spot_payload = {"type": "spotClearinghouseState", "user": MAIN_WALLET}
    spot_resp = requests.post("https://api.hyperliquid.xyz/info", json=spot_payload, timeout=10)
    spot_data = spot_resp.json()
    usdc_balance = 0.0
    for bal in spot_data.get("balances", []):
        if bal.get("coin") == "USDC":
            usdc_balance = float(bal.get("total", 0))
            break
    
    # Positions
    user_state = info.user_state(MAIN_WALLET)
    positions = user_state.get("assetPositions", [])
    open_positions = []
    unrealized_pnl = 0.0
    
    for pos in positions:
        p = pos.get("position", {})
        szi = float(p.get("szi", 0))
        if szi != 0:
            upnl = float(p.get("unrealizedPnl", 0))
            unrealized_pnl += upnl
            open_positions.append({
                "coin": p.get("coin"),
                "direction": "LONG" if szi > 0 else "SHORT",
                "size": abs(szi),
                "entry": float(p.get("entryPx", 0)),
                "unrealized_pnl": upnl,
            })
    
    return {
        "balance": usdc_balance,
        "unrealized_pnl": unrealized_pnl,
        "open_positions": open_positions,
        "margin_used": float(user_state.get("marginSummary", {}).get("totalMarginUsed", 0)),
    }

def get_fills_24h():
    """Get trade fills from last 24 hours"""
    info = Info(constants.MAINNET_API_URL, skip_ws=True)
    
    try:
        fills = info.user_fills(MAIN_WALLET)
        now = time.time() * 1000
        cutoff = now - (24 * 60 * 60 * 1000)  # 24 hours ago
        
        recent_fills = []
        for fill in fills:
            fill_time = fill.get("time", 0)
            if fill_time >= cutoff:
                recent_fills.append(fill)
        
        return recent_fills
    except:
        return []

def analyze_fills(fills):
    """Analyze fills to calculate P&L and stats"""
    if not fills:
        return {
            "total_trades": 0,
            "wins": 0,
            "losses": 0,
            "total_pnl": 0.0,
            "closed_trades": [],
        }
    
    # Group fills by coin to calculate realized P&L
    trades_by_coin = {}
    for fill in fills:
        coin = fill.get("coin", "")
        if coin not in trades_by_coin:
            trades_by_coin[coin] = []
        trades_by_coin[coin].append(fill)
    
    closed_trades = []
    total_pnl = 0.0
    wins = 0
    losses = 0
    
    for coin, coin_fills in trades_by_coin.items():
        # Look for close fills (reduce_only or opposite direction pairs)
        for fill in coin_fills:
            pnl = float(fill.get("closedPnl", 0))
            if pnl != 0:
                closed_trades.append({
                    "coin": coin,
                    "direction": "LONG" if fill.get("side") == "B" else "SHORT",
                    "entry": float(fill.get("px", 0)),
                    "exit": float(fill.get("px", 0)),
                    "pnl": pnl,
                    "time": datetime.fromtimestamp(fill.get("time", 0) / 1000, tz=WIB).strftime("%H:%M"),
                })
                total_pnl += pnl
                if pnl > 0:
                    wins += 1
                elif pnl < 0:
                    losses += 1
    
    return {
        "total_trades": len(closed_trades),
        "wins": wins,
        "losses": losses,
        "total_pnl": total_pnl,
        "closed_trades": closed_trades,
    }

def generate_ai_report(account_data, trade_stats):
    """Generate AI analysis report using OpenAI API"""
    
    # Build context for AI
    context = f"""
Kamu adalah AI analyst untuk Trading Bot milik Karman.
Bot ini menggunakan strategi Almarhum Doddy Ali Wijaya (CVD/Order Flow) + KJo Academy (RSI/MACD).
Bot trading di Hyperliquid Perpetual Futures dengan 10 koin (BTC, HYPE, ETH, SOL, NEAR, XRP, WLD, SUI, DOGE, BNB).
Margin per trade: $2, Leverage: 20x, TP: 2.5%, SL: 1.2%. Entry threshold: skor >= 3 (ketat).

DATA HARI INI ({get_wib_time().strftime('%d %B %Y')}):
- Saldo: ${account_data['balance']:.2f}
- Unrealized P&L: ${account_data['unrealized_pnl']:.4f}
- Posisi terbuka: {len(account_data['open_positions'])}
- Margin terpakai: ${account_data['margin_used']:.2f}
- Total trade closed hari ini: {trade_stats['total_trades']}
- Win: {trade_stats['wins']} | Loss: {trade_stats['losses']}
- Total P&L hari ini: ${trade_stats['total_pnl']:.4f}

Detail posisi terbuka:
{json.dumps(account_data['open_positions'], indent=2)}

Detail trade closed hari ini:
{json.dumps(trade_stats['closed_trades'], indent=2)}

Buatkan laporan performa harian yang singkat, padat, dan informatif dalam Bahasa Indonesia.
Format:
1. Ringkasan performa hari ini (1-2 kalimat)
2. Statistik: Win/Loss, P&L
3. Insight: Koin mana yang perform baik/buruk
4. Status posisi yang masih terbuka
5. Saran singkat untuk besok

Gunakan bahasa yang mudah dipahami, tidak terlalu teknis. Maksimal 200 kata.
"""
    
    if not OPENAI_API_KEY:
        # Fallback: generate report tanpa AI
        win_rate = (trade_stats['wins'] / trade_stats['total_trades'] * 100) if trade_stats['total_trades'] > 0 else 0
        report = f"""LAPORAN PERFORMA - {get_wib_time().strftime('%d %B %Y')}

Ringkasan: Bot menyelesaikan {trade_stats['total_trades']} trade hari ini.

Statistik:
- Win: {trade_stats['wins']} | Loss: {trade_stats['losses']} | Win Rate: {win_rate:.0f}%
- Total P&L: ${trade_stats['total_pnl']:.4f}
- Saldo saat ini: ${account_data['balance']:.2f}

Posisi Terbuka: {len(account_data['open_positions'])} posisi aktif
Unrealized P&L: ${account_data['unrealized_pnl']:.4f}

Bot berjalan normal dan otomatis."""
        return report
    
    try:
        headers = {
            "Authorization": f"Bearer {OPENAI_API_KEY}",
            "Content-Type": "application/json"
        }
        
        # Use base URL from env or default
        base_url = os.getenv("OPENAI_BASE_URL", "https://api.openai.com/v1")
        
        payload = {
            "model": "gpt-4.1-nano",
            "messages": [
                {"role": "system", "content": "Kamu adalah AI trading analyst yang memberikan laporan harian singkat dan informatif."},
                {"role": "user", "content": context}
            ],
            "max_tokens": 500,
            "temperature": 0.7,
        }
        
        resp = requests.post(f"{base_url}/chat/completions", headers=headers, json=payload, timeout=30)
        data = resp.json()
        
        if "choices" in data:
            return data["choices"][0]["message"]["content"]
        else:
            # Fallback
            return f"LAPORAN {get_wib_time().strftime('%d %B %Y')}: {trade_stats['total_trades']} trade, P&L: ${trade_stats['total_pnl']:.4f}, Saldo: ${account_data['balance']:.2f}"
    except Exception as e:
        return f"LAPORAN {get_wib_time().strftime('%d %B %Y')}: {trade_stats['total_trades']} trade, P&L: ${trade_stats['total_pnl']:.4f} (AI report error: {e})"

def update_performance_json(account_data, trade_stats, ai_report):
    """Update performance.json for dashboard"""
    perf_file = "performance.json"
    
    # Load existing data
    try:
        with open(perf_file, "r") as f:
            data = json.load(f)
    except:
        data = {
            "total_pnl": 0.0,
            "wins": 0,
            "losses": 0,
            "total_trades": 0,
            "today_trades": 0,
            "today_pnl": 0.0,
            "win_rate": 0,
            "avg_profit": 0.0,
            "best_trade": "--",
            "equity_curve": [],
            "daily_pnl": [],
            "closed_trades": [],
            "ai_report": None,
        }
    
    # Update with today's data
    data["today_trades"] = trade_stats["total_trades"]
    data["today_pnl"] = trade_stats["total_pnl"]
    
    # Cek apakah hari ini sudah pernah diproses (prevent double-counting)
    today_str = get_wib_time().strftime("%Y-%m-%d")
    last_report_date = data.get("last_report_date", "")
    
    if last_report_date != today_str:
        # Hari baru - akumulasi totals
        data["total_pnl"] = data.get("total_pnl", 0) + trade_stats["total_pnl"]
        data["wins"] = data.get("wins", 0) + trade_stats["wins"]
        data["losses"] = data.get("losses", 0) + trade_stats["losses"]
        data["total_trades"] = data.get("total_trades", 0) + trade_stats["total_trades"]
        data["last_report_date"] = today_str
    else:
        # Hari yang sama - update (replace), bukan akumulasi
        # Hitung selisih dari update sebelumnya
        prev_today_pnl = data.get("_prev_today_pnl", 0)
        prev_today_wins = data.get("_prev_today_wins", 0)
        prev_today_losses = data.get("_prev_today_losses", 0)
        prev_today_trades = data.get("_prev_today_trades", 0)
        
        data["total_pnl"] = data.get("total_pnl", 0) - prev_today_pnl + trade_stats["total_pnl"]
        data["wins"] = data.get("wins", 0) - prev_today_wins + trade_stats["wins"]
        data["losses"] = data.get("losses", 0) - prev_today_losses + trade_stats["losses"]
        data["total_trades"] = data.get("total_trades", 0) - prev_today_trades + trade_stats["total_trades"]
    
    # Simpan data hari ini untuk referensi jika dijalankan ulang
    data["_prev_today_pnl"] = trade_stats["total_pnl"]
    data["_prev_today_wins"] = trade_stats["wins"]
    data["_prev_today_losses"] = trade_stats["losses"]
    data["_prev_today_trades"] = trade_stats["total_trades"]
    
    total_completed = data["wins"] + data["losses"]
    data["win_rate"] = (data["wins"] / total_completed * 100) if total_completed > 0 else 0
    data["avg_profit"] = (data["total_pnl"] / total_completed) if total_completed > 0 else 0
    
    # Best trade
    if trade_stats["closed_trades"]:
        best = max(trade_stats["closed_trades"], key=lambda x: x["pnl"])
        if best["pnl"] > 0:
            current_best = data.get("best_trade", "--")
            if current_best == "--" or best["pnl"] > float(current_best.replace("$", "").replace("+", "").split(" ")[0] if current_best != "--" else "0"):
                data["best_trade"] = f"+${best['pnl']:.3f} ({best['coin']})"
    
    # Add to equity curve
    equity_point = {
        "time": get_wib_time().strftime("%d/%m %H:%M"),
        "equity": data["total_pnl"],
    }
    data.setdefault("equity_curve", []).append(equity_point)
    # Keep last 100 points
    data["equity_curve"] = data["equity_curve"][-100:]
    
    # Add to daily P&L
    today_str = get_wib_time().strftime("%d/%m")
    daily_pnl_list = data.setdefault("daily_pnl", [])
    
    # Check if today already exists
    today_exists = False
    for dp in daily_pnl_list:
        if dp["date"] == today_str:
            dp["pnl"] = trade_stats["total_pnl"]
            today_exists = True
            break
    if not today_exists:
        daily_pnl_list.append({"date": today_str, "pnl": trade_stats["total_pnl"]})
    # Keep last 30 days
    data["daily_pnl"] = data["daily_pnl"][-30:]
    
    # Add closed trades
    for t in trade_stats["closed_trades"]:
        t["time"] = get_wib_time().strftime("%d/%m") + " " + t.get("time", "")
        data.setdefault("closed_trades", []).append(t)
    # Keep last 50 trades
    data["closed_trades"] = data.get("closed_trades", [])[-50:]
    
    # AI Report
    data["ai_report"] = {
        "content": ai_report,
        "time": get_wib_time().strftime("%d %B %Y, %H:%M WIB"),
    }
    
    # Save
    with open(perf_file, "w") as f:
        json.dump(data, f, indent=2)
    
    print(f"performance.json updated successfully")

def main():
    print("=" * 60)
    print(f"AI DAILY PERFORMANCE REPORT")
    print(f"Time: {get_wib_time().strftime('%Y-%m-%d %H:%M:%S')} WIB")
    print("=" * 60)
    
    # 1. Get account data
    print("\n[1] Fetching account data...")
    account_data = get_account_data()
    print(f"  Balance: ${account_data['balance']:.2f}")
    print(f"  Open positions: {len(account_data['open_positions'])}")
    print(f"  Unrealized P&L: ${account_data['unrealized_pnl']:.4f}")
    
    # 2. Get fills from last 24h
    print("\n[2] Fetching 24h trade history...")
    fills = get_fills_24h()
    print(f"  Raw fills: {len(fills)}")
    
    # 3. Analyze fills
    print("\n[3] Analyzing trades...")
    trade_stats = analyze_fills(fills)
    print(f"  Closed trades: {trade_stats['total_trades']}")
    print(f"  Wins: {trade_stats['wins']} | Losses: {trade_stats['losses']}")
    print(f"  Total P&L: ${trade_stats['total_pnl']:.4f}")
    
    # 4. Generate AI report
    print("\n[4] Generating AI report...")
    ai_report = generate_ai_report(account_data, trade_stats)
    print(f"  Report generated ({len(ai_report)} chars)")
    print(f"\n--- AI REPORT ---\n{ai_report}\n-----------------")
    
    # 5. Update performance.json
    print("\n[5] Updating performance.json...")
    update_performance_json(account_data, trade_stats, ai_report)
    
    print("\n" + "=" * 60)
    print("DAILY REPORT COMPLETE")
    print("=" * 60)

if __name__ == "__main__":
    main()
