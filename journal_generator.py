"""
DeFi91 Trading Journal Generator
Berjalan setiap hari jam 21:00 WIB (14:00 UTC)
Menghasilkan jurnal trading harian lengkap dengan:
- Tabel semua trade hari ini (entry, TP, SL, PnL)
- Analisa teknikal kenapa bot masuk/keluar
- Pelajaran penting hari ini
- Koneksi dengan berita pasar
- Ringkasan dalam bahasa mudah dipahami
"""

import json
import os
import requests
import time
from datetime import datetime, timezone, timedelta

# Config
PRIVATE_KEY = os.getenv("HYPERLIQUID_PRIVATE_KEY", "")
MAIN_WALLET = "0x03562722fE32Ff3BaFE214be3F1828A9157eC23D"
OPENAI_API_KEY = os.getenv("OPENAI_API_KEY", "")
OPENAI_BASE_URL = os.getenv("OPENAI_BASE_URL", "https://api.openai.com/v1")
WIB = timezone(timedelta(hours=7))

def get_wib_time():
    return datetime.now(WIB)

def get_account_data():
    """Get current account state from Hyperliquid"""
    from hyperliquid.info import Info
    from hyperliquid.utils import constants
    
    info = Info(constants.MAINNET_API_URL, skip_ws=True)
    
    # Balance
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
            leverage = int(float(p.get("leverage", {}).get("value", 10))) if isinstance(p.get("leverage"), dict) else 10
            open_positions.append({
                "coin": p.get("coin"),
                "direction": "LONG" if szi > 0 else "SHORT",
                "size": abs(szi),
                "entry": float(p.get("entryPx", 0)),
                "unrealized_pnl": upnl,
                "leverage": leverage,
            })
    
    return {
        "balance": usdc_balance,
        "unrealized_pnl": unrealized_pnl,
        "open_positions": open_positions,
        "margin_used": float(user_state.get("marginSummary", {}).get("totalMarginUsed", 0)),
    }

def get_fills_24h():
    """Get trade fills from last 24 hours"""
    from hyperliquid.info import Info
    from hyperliquid.utils import constants
    
    info = Info(constants.MAINNET_API_URL, skip_ws=True)
    
    try:
        fills = info.user_fills(MAIN_WALLET)
        now = time.time() * 1000
        cutoff = now - (24 * 60 * 60 * 1000)
        
        recent_fills = []
        for fill in fills:
            fill_time = fill.get("time", 0)
            if fill_time >= cutoff:
                recent_fills.append(fill)
        
        return recent_fills
    except:
        return []

def analyze_fills_detailed(fills):
    """Analyze fills with detailed info for journal"""
    if not fills:
        return {"total_trades": 0, "wins": 0, "losses": 0, "total_pnl": 0.0, "trades": []}
    
    closed_trades = []
    total_pnl = 0.0
    wins = 0
    losses = 0
    
    for fill in fills:
        pnl = float(fill.get("closedPnl", 0))
        if pnl != 0:
            fill_time = datetime.fromtimestamp(fill.get("time", 0) / 1000, tz=WIB)
            direction = "LONG" if fill.get("side") == "B" else "SHORT"
            # If closedPnl exists and side is B, it means closing a SHORT (buying back)
            # If closedPnl exists and side is A, it means closing a LONG (selling)
            if fill.get("side") == "B":
                original_direction = "SHORT"
            else:
                original_direction = "LONG"
            
            closed_trades.append({
                "coin": fill.get("coin", ""),
                "direction": original_direction,
                "exit_price": float(fill.get("px", 0)),
                "size": float(fill.get("sz", 0)),
                "pnl": pnl,
                "time": fill_time.strftime("%H:%M"),
                "fee": float(fill.get("fee", 0)),
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
        "trades": closed_trades,
    }

def get_trades_json_today():
    """Get today's entries from trades.json"""
    try:
        with open("trades.json", "r") as f:
            data = json.load(f)
        
        today_str = get_wib_time().strftime("%Y-%m-%d")
        today_trades = []
        for trade in data.get("trades", []):
            if trade.get("time", "").startswith(today_str):
                today_trades.append(trade)
        
        return today_trades
    except:
        return []

def get_crypto_news():
    """Get latest crypto news headlines for context"""
    try:
        # Use CoinGecko trending or simple news API
        resp = requests.get("https://api.coingecko.com/api/v3/search/trending", timeout=10)
        data = resp.json()
        trending = []
        for coin in data.get("coins", [])[:5]:
            item = coin.get("item", {})
            trending.append(f"{item.get('name', '')} ({item.get('symbol', '')})")
        return {"trending": trending}
    except:
        return {"trending": []}

def generate_journal_ai(account_data, trade_stats, today_entries, news_data):
    """Generate comprehensive journal using AI"""
    
    today = get_wib_time()
    
    # Build trade table for context
    trade_table = ""
    for t in today_entries:
        trade_table += f"- {t.get('time','')}: {t.get('coin','')} {t.get('signal','')} | Entry: ${t.get('entry',0)} | TP: ${t.get('tp',0)} | SL: ${t.get('sl',0)} | Margin: ${t.get('margin',0)} | Lev: {t.get('leverage',0)}x | CVD Score: {t.get('cvd_score','')} | RSI: {t.get('rsi','')}\n"
    
    closed_table = ""
    for t in trade_stats.get("trades", []):
        status = "PROFIT" if t["pnl"] > 0 else "LOSS"
        closed_table += f"- {t['time']}: {t['coin']} {t['direction']} | Exit: ${t['exit_price']} | PnL: ${t['pnl']:.4f} ({status})\n"
    
    positions_info = ""
    for p in account_data.get("open_positions", []):
        positions_info += f"- {p['coin']} {p['direction']} | Entry: ${p['entry']} | Unrealized: ${p['unrealized_pnl']:.4f} | Leverage: {p['leverage']}x\n"
    
    trending = ", ".join(news_data.get("trending", [])) if news_data.get("trending") else "Tidak ada data trending"
    
    prompt = f"""Kamu adalah AI Trading Journal Writer untuk bot trading milik Karman.
Bot menggunakan strategi gabungan:
1. Almarhum Doddy Ali Wijaya (CVD/Order Flow) - Melihat volume delta dan order book imbalance
2. KJo Academy (RSI + MACD + Support/Resistance) - Melihat momentum teknikal

TUGAS: Buatkan JURNAL TRADING HARIAN yang lengkap dan mudah dipahami.

DATA HARI INI ({today.strftime('%A, %d %B %Y')}):
=== AKUN ===
- Saldo: ${account_data['balance']:.2f}
- Margin Terpakai: ${account_data['margin_used']:.2f}
- Unrealized P&L: ${account_data['unrealized_pnl']:.4f}

=== TRADE YANG DIBUKA HARI INI ===
{trade_table if trade_table else "Tidak ada trade baru hari ini"}

=== TRADE YANG DITUTUP (CLOSED) HARI INI ===
{closed_table if closed_table else "Tidak ada trade yang ditutup hari ini"}

Total Closed: {trade_stats['total_trades']} trade
Win: {trade_stats['wins']} | Loss: {trade_stats['losses']}
Total Realized P&L: ${trade_stats['total_pnl']:.4f}

=== POSISI MASIH TERBUKA ===
{positions_info if positions_info else "Tidak ada posisi terbuka"}

=== TRENDING CRYPTO ===
{trending}

FORMAT JURNAL YANG HARUS KAMU BUAT:

1. **RINGKASAN HARI INI** (2-3 kalimat, seperti bercerita ke teman)
   - Apa yang terjadi hari ini secara keseluruhan

2. **ANALISA KENAPA BOT MASUK POSISI**
   - Untuk setiap trade yang dibuka, jelaskan:
     * Sinyal CVD (Almarhum): Apa yang dilihat dari order flow?
     * Sinyal Teknikal (KJo): RSI berapa? MACD bagaimana? Dekat support/resistance?
     * Kenapa skor bisa tinggi sehingga bot memutuskan masuk

3. **ANALISA KENAPA BOT KELUAR POSISI**
   - Untuk setiap trade yang ditutup, jelaskan:
     * Apakah kena TP (target tercapai)?
     * Apakah kena SL (cut loss)?
     * Apakah Smart Exit (sinyal berbalik)?

4. **PELAJARAN PENTING HARI INI**
   - Apa yang bisa dipelajari dari trade hari ini?
   - Apa yang berhasil dan apa yang tidak?
   - Hubungkan dengan kondisi pasar (trending/sideways)

5. **KONEKSI DENGAN BERITA/SENTIMEN PASAR**
   - Apakah ada berita yang mempengaruhi pergerakan harga?
   - Bagaimana sentimen pasar secara umum?

6. **SKOR PERFORMA HARI INI** (1-10)
   - Berikan rating dan alasannya

Gunakan bahasa Indonesia yang santai tapi informatif, seperti menulis blog pribadi.
Jangan terlalu panjang, maksimal 500 kata. Fokus pada insight yang bisa dipelajari."""

    if not OPENAI_API_KEY:
        return generate_fallback_journal(account_data, trade_stats, today_entries)
    
    try:
        headers = {
            "Authorization": f"Bearer {OPENAI_API_KEY}",
            "Content-Type": "application/json"
        }
        
        payload = {
            "model": "gpt-4.1-nano",
            "messages": [
                {"role": "system", "content": "Kamu adalah penulis jurnal trading yang ahli. Tulisanmu informatif, mudah dipahami, dan cocok untuk konten blog/reel."},
                {"role": "user", "content": prompt}
            ],
            "max_tokens": 1500,
            "temperature": 0.7,
        }
        
        resp = requests.post(f"{OPENAI_BASE_URL}/chat/completions", headers=headers, json=payload, timeout=60)
        data = resp.json()
        
        if "choices" in data:
            return data["choices"][0]["message"]["content"]
        else:
            return generate_fallback_journal(account_data, trade_stats, today_entries)
    except Exception as e:
        print(f"AI Error: {e}")
        return generate_fallback_journal(account_data, trade_stats, today_entries)

def generate_fallback_journal(account_data, trade_stats, today_entries):
    """Fallback journal tanpa AI"""
    today = get_wib_time()
    win_rate = (trade_stats['wins'] / trade_stats['total_trades'] * 100) if trade_stats['total_trades'] > 0 else 0
    
    journal = f"""JURNAL TRADING - {today.strftime('%A, %d %B %Y')}

RINGKASAN: Bot menjalankan {len(today_entries)} entry baru dan menutup {trade_stats['total_trades']} posisi hari ini.

STATISTIK:
- Trade Closed: {trade_stats['total_trades']}
- Win: {trade_stats['wins']} | Loss: {trade_stats['losses']} | Win Rate: {win_rate:.0f}%
- Total P&L: ${trade_stats['total_pnl']:.4f}
- Saldo: ${account_data['balance']:.2f}

POSISI TERBUKA: {len(account_data['open_positions'])} posisi aktif
Unrealized P&L: ${account_data['unrealized_pnl']:.4f}

Bot berjalan normal sesuai strategi Almarhum + KJo Academy."""
    return journal

def save_journal(journal_content, account_data, trade_stats, today_entries):
    """Save journal to journal.json for dashboard"""
    journal_file = "journal.json"
    today = get_wib_time()
    today_str = today.strftime("%Y-%m-%d")
    
    # Load existing journals
    try:
        with open(journal_file, "r") as f:
            data = json.load(f)
    except:
        data = {"journals": []}
    
    # Build trade table data
    trade_table = []
    for t in today_entries:
        trade_table.append({
            "time": t.get("time", ""),
            "coin": t.get("coin", ""),
            "direction": t.get("signal", ""),
            "entry": t.get("entry", 0),
            "tp": t.get("tp", 0),
            "sl": t.get("sl", 0),
            "margin": t.get("margin", 0),
            "leverage": t.get("leverage", 0),
            "cvd_score": t.get("cvd_score", ""),
            "rsi": t.get("rsi", ""),
        })
    
    closed_table = []
    for t in trade_stats.get("trades", []):
        closed_table.append({
            "time": t.get("time", ""),
            "coin": t.get("coin", ""),
            "direction": t.get("direction", ""),
            "exit_price": t.get("exit_price", 0),
            "pnl": t.get("pnl", 0),
            "fee": t.get("fee", 0),
        })
    
    # Create today's journal entry
    journal_entry = {
        "date": today_str,
        "date_display": today.strftime("%A, %d %B %Y"),
        "balance": account_data["balance"],
        "margin_used": account_data["margin_used"],
        "unrealized_pnl": account_data["unrealized_pnl"],
        "total_closed": trade_stats["total_trades"],
        "wins": trade_stats["wins"],
        "losses": trade_stats["losses"],
        "total_pnl": trade_stats["total_pnl"],
        "win_rate": (trade_stats['wins'] / trade_stats['total_trades'] * 100) if trade_stats['total_trades'] > 0 else 0,
        "entries_today": trade_table,
        "closed_today": closed_table,
        "open_positions": account_data["open_positions"],
        "journal_content": journal_content,
        "generated_at": today.strftime("%H:%M WIB"),
    }
    
    # Replace if same date exists, otherwise append
    existing_idx = None
    for i, j in enumerate(data["journals"]):
        if j.get("date") == today_str:
            existing_idx = i
            break
    
    if existing_idx is not None:
        data["journals"][existing_idx] = journal_entry
    else:
        data["journals"].append(journal_entry)
    
    # Keep last 30 days
    data["journals"] = data["journals"][-30:]
    
    # Save
    with open(journal_file, "w") as f:
        json.dump(data, f, indent=2, ensure_ascii=False)
    
    print(f"journal.json saved ({len(data['journals'])} entries)")

def main():
    print("=" * 60)
    print("TRADING JOURNAL GENERATOR")
    print(f"Time: {get_wib_time().strftime('%Y-%m-%d %H:%M:%S')} WIB")
    print("=" * 60)
    
    # 1. Get account data
    print("\n[1] Fetching account data...")
    account_data = get_account_data()
    print(f"  Balance: ${account_data['balance']:.2f}")
    print(f"  Open positions: {len(account_data['open_positions'])}")
    
    # 2. Get fills
    print("\n[2] Fetching 24h trade history...")
    fills = get_fills_24h()
    print(f"  Raw fills: {len(fills)}")
    
    # 3. Analyze
    print("\n[3] Analyzing trades...")
    trade_stats = analyze_fills_detailed(fills)
    print(f"  Closed: {trade_stats['total_trades']} | Win: {trade_stats['wins']} | Loss: {trade_stats['losses']}")
    print(f"  P&L: ${trade_stats['total_pnl']:.4f}")
    
    # 4. Get today's entries from trades.json
    print("\n[4] Loading today's entries from trades.json...")
    today_entries = get_trades_json_today()
    print(f"  Entries today: {len(today_entries)}")
    
    # 5. Get news/trending
    print("\n[5] Fetching market news...")
    news_data = get_crypto_news()
    print(f"  Trending: {news_data.get('trending', [])}")
    
    # 6. Generate AI journal
    print("\n[6] Generating AI journal...")
    journal_content = generate_journal_ai(account_data, trade_stats, today_entries, news_data)
    print(f"  Journal generated ({len(journal_content)} chars)")
    print(f"\n{'='*40}\n{journal_content}\n{'='*40}")
    
    # 7. Save
    print("\n[7] Saving journal...")
    save_journal(journal_content, account_data, trade_stats, today_entries)
    
    print("\n" + "=" * 60)
    print("JOURNAL GENERATION COMPLETE")
    print("=" * 60)

if __name__ == "__main__":
    main()
