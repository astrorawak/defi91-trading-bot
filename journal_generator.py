"""
DeFi91 Trading Journal Generator
Berjalan setiap hari jam 13:00 WIB (06:00 UTC)
Menghasilkan jurnal trading harian lengkap dengan:
- Tabel semua trade hari ini (entry, TP, SL, PnL)
- Analisa teknikal kenapa bot masuk/keluar
- Pelajaran penting hari ini
- Koneksi dengan berita pasar
- Ringkasan dalam bahasa mudah dipahami
- File HTML terpisah per hari (shareable link)
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
- Win: {trade_stats['wins']} | Loss: {trade_stats['losses']}
- Win Rate: {win_rate:.0f}%
- Total P&L: ${trade_stats['total_pnl']:.4f}
- Saldo: ${account_data['balance']:.2f}

POSISI TERBUKA: {len(account_data['open_positions'])} posisi aktif
Unrealized P&L: ${account_data['unrealized_pnl']:.4f}

Bot berjalan normal sesuai strategi Almarhum + KJo Academy."""
    return journal

def generate_html_journal(journal_entry):
    """Generate a standalone HTML page for this journal entry that can be shared"""
    date_display = journal_entry.get("date_display", journal_entry["date"])
    date_str = journal_entry["date"]
    balance = journal_entry["balance"]
    total_pnl = journal_entry["total_pnl"]
    wins = journal_entry["wins"]
    losses = journal_entry["losses"]
    win_rate = journal_entry["win_rate"]
    entries_today = journal_entry.get("entries_today", [])
    closed_today = journal_entry.get("closed_today", [])
    open_positions = journal_entry.get("open_positions", [])
    journal_content = journal_entry.get("journal_content", "")
    generated_at = journal_entry.get("generated_at", "")
    
    # Build entries table rows
    entries_rows = ""
    for t in entries_today:
        time_short = t.get("time", "")[-8:-3] if len(t.get("time", "")) > 5 else t.get("time", "")
        direction_class = "long" if t.get("direction", "").upper() == "LONG" else "short"
        entries_rows += f"""<tr>
            <td>{time_short}</td>
            <td>{t.get('coin','')}</td>
            <td class="{direction_class}">{t.get('direction','')}</td>
            <td>${t.get('entry',0)}</td>
            <td>${t.get('tp',0)}</td>
            <td>${t.get('sl',0)}</td>
            <td>${t.get('margin',0)}</td>
            <td>{t.get('leverage',0)}x</td>
            <td>{t.get('cvd_score','')}</td>
            <td>{t.get('rsi','')}</td>
        </tr>"""
    
    # Build closed table rows
    closed_rows = ""
    for t in closed_today:
        direction_class = "long" if t.get("direction", "").upper() == "LONG" else "short"
        pnl_class = "profit" if t.get("pnl", 0) > 0 else "loss"
        status = "WIN" if t.get("pnl", 0) > 0 else "LOSS"
        closed_rows += f"""<tr>
            <td>{t.get('time','')}</td>
            <td>{t.get('coin','')}</td>
            <td class="{direction_class}">{t.get('direction','')}</td>
            <td>${t.get('exit_price',0)}</td>
            <td class="{pnl_class}">${t.get('pnl',0):.4f}</td>
            <td class="{pnl_class}">{status}</td>
        </tr>"""
    
    # Build open positions rows
    positions_rows = ""
    for p in open_positions:
        direction_class = "long" if p.get("direction", "").upper() == "LONG" else "short"
        pnl_class = "profit" if p.get("unrealized_pnl", 0) >= 0 else "loss"
        positions_rows += f"""<tr>
            <td>{p.get('coin','')}</td>
            <td class="{direction_class}">{p.get('direction','')}</td>
            <td>${p.get('entry',0)}</td>
            <td>{p.get('leverage',10)}x</td>
            <td class="{pnl_class}">${p.get('unrealized_pnl',0):.4f}</td>
        </tr>"""
    
    if not positions_rows:
        positions_rows = '<tr><td colspan="5" style="text-align:center;opacity:0.5;">Tidak ada posisi terbuka</td></tr>'
    
    # Convert journal markdown to simple HTML
    journal_html = journal_content.replace("\n\n", "</p><p>").replace("\n", "<br>")
    journal_html = journal_html.replace("### ", "<h3>").replace("**", "<strong>").replace("**", "</strong>")
    # Simple bold handling
    import re
    journal_html = re.sub(r'\*\*(.+?)\*\*', r'<strong>\1</strong>', journal_html)
    journal_html = re.sub(r'### (.+?)(<br>|</p>)', r'<h3>\1</h3>', journal_html)
    journal_html = f"<p>{journal_html}</p>"
    
    pnl_class = "profit" if total_pnl >= 0 else "loss"
    pnl_sign = "+" if total_pnl >= 0 else ""
    
    html = f"""<!DOCTYPE html>
<html lang="id">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>Jurnal Trading - {date_display} | By Karman</title>
    <meta name="description" content="Jurnal Trading Harian Bot DeFi91 - {date_display}. Strategi Almarhum Doddy Ali Wijaya + KJo Academy.">
    <meta property="og:title" content="Jurnal Trading - {date_display} | By Karman">
    <meta property="og:description" content="P&L: {pnl_sign}${total_pnl:.2f} | Win Rate: {win_rate:.0f}% | Trades: {wins + losses}">
    <meta property="og:type" content="article">
    <link href="https://fonts.googleapis.com/css2?family=Orbitron:wght@400;700;900&family=Space+Grotesk:wght@300;400;500;700&display=swap" rel="stylesheet">
    <style>
        * {{ margin: 0; padding: 0; box-sizing: border-box; }}
        body {{
            font-family: 'Space Grotesk', sans-serif;
            background: #0a0a0f;
            color: #e0e0e0;
            min-height: 100vh;
            padding: 20px;
        }}
        .container {{ max-width: 900px; margin: 0 auto; }}
        .header {{
            text-align: center;
            padding: 30px 0;
            border-bottom: 1px solid rgba(0,255,136,0.2);
            margin-bottom: 30px;
        }}
        .header h1 {{
            font-family: 'Orbitron', monospace;
            font-size: 1.8rem;
            font-weight: 900;
            background: linear-gradient(135deg, #00ff88, #00c8ff, #8a2be2);
            -webkit-background-clip: text;
            -webkit-text-fill-color: transparent;
            background-clip: text;
            margin-bottom: 8px;
        }}
        .header .subtitle {{
            color: #888;
            font-size: 0.9rem;
        }}
        .header .date {{
            font-family: 'Orbitron', monospace;
            font-size: 1.2rem;
            color: #00ff88;
            margin-top: 10px;
        }}
        .stats-grid {{
            display: grid;
            grid-template-columns: repeat(auto-fit, minmax(150px, 1fr));
            gap: 15px;
            margin-bottom: 30px;
        }}
        .stat-card {{
            background: rgba(255,255,255,0.03);
            border: 1px solid rgba(255,255,255,0.08);
            border-radius: 12px;
            padding: 20px;
            text-align: center;
        }}
        .stat-card .label {{ font-size: 0.75rem; color: #888; text-transform: uppercase; letter-spacing: 1px; }}
        .stat-card .value {{ font-family: 'Orbitron', monospace; font-size: 1.4rem; margin-top: 5px; }}
        .profit {{ color: #00ff88; }}
        .loss {{ color: #ff4757; }}
        .long {{ color: #00ff88; font-weight: 600; }}
        .short {{ color: #ff4757; font-weight: 600; }}
        .section {{
            background: rgba(255,255,255,0.02);
            border: 1px solid rgba(255,255,255,0.06);
            border-radius: 12px;
            padding: 25px;
            margin-bottom: 20px;
        }}
        .section h2 {{
            font-family: 'Orbitron', monospace;
            font-size: 0.9rem;
            color: #00c8ff;
            margin-bottom: 15px;
            text-transform: uppercase;
            letter-spacing: 1px;
        }}
        table {{
            width: 100%;
            border-collapse: collapse;
            font-size: 0.85rem;
        }}
        th {{
            background: rgba(0,200,255,0.1);
            padding: 10px 8px;
            text-align: left;
            font-size: 0.75rem;
            text-transform: uppercase;
            letter-spacing: 0.5px;
            color: #aaa;
        }}
        td {{
            padding: 8px;
            border-bottom: 1px solid rgba(255,255,255,0.05);
        }}
        .journal-content {{
            line-height: 1.8;
            font-size: 0.95rem;
        }}
        .journal-content h3 {{
            color: #00c8ff;
            margin: 20px 0 10px;
            font-size: 1rem;
        }}
        .journal-content strong {{
            color: #00ff88;
        }}
        .footer {{
            text-align: center;
            padding: 30px 0;
            color: #555;
            font-size: 0.8rem;
            border-top: 1px solid rgba(255,255,255,0.05);
            margin-top: 30px;
        }}
        .back-link {{
            display: inline-block;
            margin-top: 15px;
            color: #00c8ff;
            text-decoration: none;
            font-size: 0.85rem;
        }}
        .back-link:hover {{ color: #00ff88; }}
        @media (max-width: 600px) {{
            .stats-grid {{ grid-template-columns: repeat(2, 1fr); }}
            table {{ font-size: 0.75rem; }}
            td, th {{ padding: 6px 4px; }}
        }}
    </style>
</head>
<body>
    <div class="container">
        <div class="header">
            <h1>Trading Bot By: Karman</h1>
            <div class="subtitle">Strategi Almarhum Doddy Ali Wijaya + KJo Academy</div>
            <div class="date">{date_display}</div>
        </div>

        <div class="stats-grid">
            <div class="stat-card">
                <div class="label">Saldo</div>
                <div class="value">${balance:.2f}</div>
            </div>
            <div class="stat-card">
                <div class="label">P&L Hari Ini</div>
                <div class="value {pnl_class}">{pnl_sign}${total_pnl:.4f}</div>
            </div>
            <div class="stat-card">
                <div class="label">Win Rate</div>
                <div class="value">{win_rate:.0f}%</div>
            </div>
            <div class="stat-card">
                <div class="label">Total Trade</div>
                <div class="value">{wins + losses}</div>
            </div>
        </div>

        <div class="section">
            <h2>Trade yang Dibuka Hari Ini</h2>
            <div style="overflow-x:auto;">
            <table>
                <thead><tr>
                    <th>Waktu</th><th>Koin</th><th>Arah</th><th>Entry</th><th>TP</th><th>SL</th><th>Margin</th><th>Lev</th><th>CVD</th><th>RSI</th>
                </tr></thead>
                <tbody>{entries_rows if entries_rows else '<tr><td colspan="10" style="text-align:center;opacity:0.5;">Tidak ada trade baru</td></tr>'}</tbody>
            </table>
            </div>
        </div>

        <div class="section">
            <h2>Trade yang Ditutup Hari Ini</h2>
            <div style="overflow-x:auto;">
            <table>
                <thead><tr>
                    <th>Waktu</th><th>Koin</th><th>Arah</th><th>Exit Price</th><th>P&L</th><th>Status</th>
                </tr></thead>
                <tbody>{closed_rows if closed_rows else '<tr><td colspan="6" style="text-align:center;opacity:0.5;">Tidak ada trade ditutup</td></tr>'}</tbody>
            </table>
            </div>
        </div>

        <div class="section">
            <h2>Posisi Masih Terbuka</h2>
            <div style="overflow-x:auto;">
            <table>
                <thead><tr>
                    <th>Koin</th><th>Arah</th><th>Entry</th><th>Leverage</th><th>Unrealized P&L</th>
                </tr></thead>
                <tbody>{positions_rows}</tbody>
            </table>
            </div>
        </div>

        <div class="section">
            <h2>Analisa & Pelajaran Hari Ini</h2>
            <div class="journal-content">
                {journal_html}
            </div>
        </div>

        <div class="footer">
            <p>Generated: {generated_at} | Trading Bot By Karman</p>
            <a href="../index.html" class="back-link">&#8592; Kembali ke Dashboard</a>
            <br>
            <a href="index.html" class="back-link">&#8592; Semua Jurnal</a>
        </div>
    </div>
</body>
</html>"""
    return html

def generate_journal_index(journals):
    """Generate index page listing all journal entries"""
    rows = ""
    for j in reversed(journals):
        date_str = j.get("date", "")
        date_display = j.get("date_display", date_str)
        pnl = j.get("total_pnl", 0)
        pnl_class = "profit" if pnl >= 0 else "loss"
        pnl_sign = "+" if pnl >= 0 else ""
        win_rate = j.get("win_rate", 0)
        total_trades = j.get("wins", 0) + j.get("losses", 0)
        rows += f"""<tr onclick="window.location='journal/{date_str}.html'" style="cursor:pointer;">
            <td><a href="journal/{date_str}.html" style="color:#00c8ff;text-decoration:none;">{date_display}</a></td>
            <td class="{pnl_class}">{pnl_sign}${pnl:.4f}</td>
            <td>{win_rate:.0f}%</td>
            <td>{total_trades}</td>
        </tr>"""
    
    html = f"""<!DOCTYPE html>
<html lang="id">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>Jurnal Trading - Semua Hari | By Karman</title>
    <link href="https://fonts.googleapis.com/css2?family=Orbitron:wght@400;700;900&family=Space+Grotesk:wght@300;400;500;700&display=swap" rel="stylesheet">
    <style>
        * {{ margin: 0; padding: 0; box-sizing: border-box; }}
        body {{
            font-family: 'Space Grotesk', sans-serif;
            background: #0a0a0f;
            color: #e0e0e0;
            min-height: 100vh;
            padding: 20px;
        }}
        .container {{ max-width: 700px; margin: 0 auto; }}
        .header {{
            text-align: center;
            padding: 30px 0;
            border-bottom: 1px solid rgba(0,255,136,0.2);
            margin-bottom: 30px;
        }}
        .header h1 {{
            font-family: 'Orbitron', monospace;
            font-size: 1.6rem;
            font-weight: 900;
            background: linear-gradient(135deg, #00ff88, #00c8ff, #8a2be2);
            -webkit-background-clip: text;
            -webkit-text-fill-color: transparent;
            background-clip: text;
            margin-bottom: 8px;
        }}
        .header .subtitle {{ color: #888; font-size: 0.9rem; }}
        .profit {{ color: #00ff88; }}
        .loss {{ color: #ff4757; }}
        table {{
            width: 100%;
            border-collapse: collapse;
            font-size: 0.9rem;
        }}
        th {{
            background: rgba(0,200,255,0.1);
            padding: 12px 10px;
            text-align: left;
            font-size: 0.8rem;
            text-transform: uppercase;
            letter-spacing: 0.5px;
            color: #aaa;
        }}
        td {{
            padding: 12px 10px;
            border-bottom: 1px solid rgba(255,255,255,0.05);
        }}
        tr:hover {{ background: rgba(0,255,136,0.05); }}
        .back-link {{
            display: inline-block;
            margin-top: 20px;
            color: #00c8ff;
            text-decoration: none;
            font-size: 0.85rem;
        }}
        .back-link:hover {{ color: #00ff88; }}
        .footer {{
            text-align: center;
            padding: 20px 0;
            color: #555;
            font-size: 0.8rem;
            margin-top: 30px;
        }}
    </style>
</head>
<body>
    <div class="container">
        <div class="header">
            <h1>Jurnal Trading Harian</h1>
            <div class="subtitle">Trading Bot By Karman - Strategi Almarhum + KJo Academy</div>
        </div>
        <table>
            <thead><tr>
                <th>Tanggal</th><th>P&L</th><th>Win Rate</th><th>Trades</th>
            </tr></thead>
            <tbody>{rows if rows else '<tr><td colspan="4" style="text-align:center;opacity:0.5;">Belum ada jurnal</td></tr>'}</tbody>
        </table>
        <div class="footer">
            <a href="../index.html" class="back-link">&#8592; Kembali ke Dashboard</a>
        </div>
    </div>
</body>
</html>"""
    return html

def save_journal(journal_content, account_data, trade_stats, today_entries):
    """Save journal to journal.json and generate HTML files"""
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
    
    # Save JSON
    with open(journal_file, "w") as f:
        json.dump(data, f, indent=2, ensure_ascii=False)
    print(f"journal.json saved ({len(data['journals'])} entries)")
    
    # Generate HTML files
    os.makedirs("journal", exist_ok=True)
    
    # Generate today's HTML journal page
    html_content = generate_html_journal(journal_entry)
    html_path = f"journal/{today_str}.html"
    with open(html_path, "w", encoding="utf-8") as f:
        f.write(html_content)
    print(f"HTML journal saved: {html_path}")
    
    # Generate index page
    index_html = generate_journal_index(data["journals"])
    with open("journal/index.html", "w", encoding="utf-8") as f:
        f.write(index_html)
    print("Journal index page saved: journal/index.html")

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
    
    # 7. Save (JSON + HTML)
    print("\n[7] Saving journal (JSON + HTML)...")
    save_journal(journal_content, account_data, trade_stats, today_entries)
    
    print("\n" + "=" * 60)
    print("JOURNAL GENERATION COMPLETE")
    print("=" * 60)

if __name__ == "__main__":
    main()
