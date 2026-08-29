#!/usr/bin/env python3
"""refresh_dashboard.py — Regenerasi performance.json dari data LIVE Hyperliquid (0 kredit, pure urllib).
Sumber kebenaran: user_fills (closed PnL + fee) + clearinghouseState (akun & posisi terbuka).
Menghindari ketidaksesuaian akumulator lama yang membeku sejak 22-Agu saat pipeline pindah ke Hermes cron."""
import json, os, sys, time, urllib.request
from datetime import datetime, timezone, timedelta

WALLET = "0x03562722fE32Ff3BaFE214be3F1828A9157eC23D"
URL = "https://api.hyperliquid.xyz/info"
BASE = os.path.dirname(os.path.abspath(__file__))
# lingkup performa = bot v3 (selaras dgn defi91_eval.py baris 42)
V3_START_MS = int(datetime(2026, 8, 19, 5, 0, tzinfo=timezone.utc).timestamp()*1000)

def post(p):
    r = urllib.request.Request(URL, data=json.dumps(p).encode(), headers={"Content-Type":"application/json"})
    return json.loads(urllib.request.urlopen(r, timeout=25).read())

def wib(ms):
    return datetime.fromtimestamp(ms/1000, timezone(timedelta(hours=7)))

# --- ambil data live ---
st = post({"type":"clearinghouseState","user":WALLET})
acv = float(st["marginSummary"]["accountValue"])
fills = post({"type":"userFills","user":WALLET, "limit": 2000}) or []
# API mengabaikan startTime; filter manual ke lingkup v3 (selaras dgn defi91_eval.py)
fills = [f for f in fills if float(f.get("time",0)) >= V3_START_MS]

# --- posisi terbuka ---
positions = []
for b in st.get("assetPositions", []):
    p = b["position"]; sz = float(p.get("szi",0))
    if abs(sz) < 1e-9: continue
    positions.append({"coin":p["coin"],"side":"LONG" if sz>0 else "SHORT","sz":sz,
                      "entry":p["entryPx"],"uPnl":round(float(p.get("unrealizedPnl",0)),4),
                      "liq":p.get("liquidationPx")})

# --- statistik closed dari fills ---
total_pnl=0.0; wins=0; losses=0; closes=[]; best=None; today_pnl=0.0; today_trades=0
now_utc = datetime.now(timezone.utc)
today_str = (now_utc + timedelta(hours=7)).strftime("%Y-%m-%d")
daily_pnl = {}
for f in fills:
    cp = float(f.get("closedPnl",0)); fee = float(f.get("fee",0))
    if abs(cp) < 1e-12:   # bukan penutupan posisi
        continue
    net = cp + (-fee if fee==abs(cp) else -fee)
    total_pnl += net
    if cp > 0: wins += 1
    else: losses += 1
    closes.append({"time": f["time"], "coin": f.get("coin"), "side": f.get("dir"),
                   "px": f.get("px"), "pnl": round(cp,4), "fee": round(fee,4)})
    if best is None or cp > best["pnl"]:
        best = {"label": f"{f.get('coin')}", "pnl": round(cp,4)}
    d = wib(f["time"]).strftime("%Y-%m-%d")
    daily_pnl[d] = daily_pnl.get(d,0) + net
    if d == today_str:
        today_pnl += net; today_trades += 1

total_trades = len(closes)
avg_profit = total_pnl/total_trades if total_trades else 0
win_rate = wins/total_trades*100 if total_trades else 0

# --- equity curve: jangan kehilangan titik lama, tambah yang sekarang ---
try:
    old = json.load(open(os.path.join(BASE,"performance.json")))
except Exception:
    old = {}
eq = old.get("equity_curve", [])
now_wib = datetime.now(timezone(timedelta(hours=7)))
eq = [e for e in eq if e.get("time","").count(":")==2][-400:]  # sisakan titik waktu jam:menit
eq.append({"time": now_wib.strftime("%H:%M"), "equity": round(acv,4)})

perf = {
    "total_pnl": round(total_pnl,6),
    "wins": wins, "losses": losses,
    "total_trades": total_trades,
    "today_trades": today_trades,
    "today_pnl": round(today_pnl,6),
    "win_rate": round(win_rate,4),
    "avg_profit": round(avg_profit,6),
    "best_trade": (f"+${best['pnl']} ({best['label']})" if best else "--"),
    "equity_curve": eq,
    "daily_pnl": [{"date":d,"pnl":round(v,4)} for d,v in sorted(daily_pnl.items())[-21:]],
    "closed_trades": sorted(closes, key=lambda x:x["time"] , reverse=True)[-60:],
    "account_value": round(acv,2),
    "positions": positions,
    "margin_used_pct": round((float(st["marginSummary"]["totalMarginUsed"])/acv*100) if acv else 0,1),
    "ai_report": old.get("ai_report"),
    "last_refresh": datetime.now(timezone.utc).isoformat(),
}
json.dump(perf, open(os.path.join(BASE,"performance.json"),"w"), indent=2)
print("performance.json diperbarui (live):")
print("  accountValue=$%.2f  total_pnl=$%.4f  today_trades=%d  today_pnl=$%.4f  win_rate=%.1f%%  closes=%d" %
      (acv, total_pnl, today_trades, today_pnl, win_rate, total_trades))
print("  posisi:", positions)
