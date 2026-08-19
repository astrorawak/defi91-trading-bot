#!/usr/bin/env python3
"""DeFi91 Self-Evaluation (lapisan self-improvement Hermes).
Baca riwayat trade nyata per koin (user_fills) -> hitung PnL bersih, win-rate,
frekuensi. Tulis laporan JSON + file rekomendasi watchlist yang bot baca.
0 KREDIT AI (script murni, no_agent). stdout KOSONG bila tidak ada rekomendasi
(untuk cron no_agent: tentu senyap). Cadang core BTC/ETH/BNB tak pernah disarankan off.

File output:
  ~/.defi91_eval_report.json   -> data mentah evaluasi
  ~/.defi91_watch_override.json -> { "remove": ["XRP"], "reason": "..." } jika perlu
"""
import json, os, sys, time, urllib.request
from datetime import datetime, timezone, timedelta

WALLET = "0x03562722fE32Ff3BaFE214be3F1828A9157eC23D"
URL = "https://api.hyperliquid.xyz/info"
REPORT = os.path.expanduser("~/.defi91_eval_report.json")
OVERRIDE = os.path.expanduser("~/.defi91_watch_override.json")

CORE = {"BTC", "ETH", "BNB"}            # tak pernah disarankan off
DEFAULT_WATCH = ["BTC","ETH","BNB","SOL","XRP","DOGE","ADA","LINK","AVAX","LTC"]
RSLEEP = 0.15

def post(p):
    r = urllib.request.Request(URL, data=json.dumps(p).encode(),
                               headers={"Content-Type":"application/json"})
    return json.loads(urllib.request.urlopen(r, timeout=20).read())

def main():
    now = int(time.time()*1000)
    days = 7
    start = now - days*86400*1000
    # Ambil state publik (0 kredit/readonly)
    try:
        st = post({"type":"clearinghouseState","user":WALLET})
        acv = float(st["marginSummary"]["accountValue"])
    except Exception as e:
        print(f"[EVAL] gagal state: {e}"); return 0

    # PENTING: evaluasi HANYA hasil bot v3 yang mulai jalan 19 Agu 2026 (sejak ~12:00 WIB),
    # dan HANYA koin yang live di watchlist kita. JANGAN campur data scalping v2 lama.
    v3_start_ms = int(datetime(2026, 8, 19, 5, 0, tzinfo=timezone.utc).timestamp()*1000)
    eval_coins = set(["BTC","ETH","BNB","SOL","XRP","DOGE","ADA","LINK","AVAX","LTC"])

    per_coin = {}
    pkey = os.environ.get("HYPERLIQUID_PRIVATE_KEY","")
    if pkey:
        try:
            fills = post({"type":"userFills","user":WALLET,"startTime":v3_start_ms,"endTime":now})
        except Exception as e:
            fills = []
        for f in fills:
            c = f.get("coin")
            if c not in eval_coins:        # abaikan koin luar watchlist / microcap lama
                continue
            ts = f.get("time", 0)
            if ts < v3_start_ms:           # abaikan data sebelum bot v3 hidup
                continue
            if c not in per_coin:
                per_coin[c] = {"net":0.0,"wins":0,"losses":0,"trades":0,"fees":0.0}
            fee = float(f.get("fee",0)); pnl = float(f.get("closedPnl",0))
            d = per_coin[c]
            d["trades"]+=1; d["fees"]+=fee; d["net"]+=pnl+(-fee)
            if pnl>0: d["wins"]+=1
            elif pnl<0: d["losses"]+=1

    report = {
        "ts": datetime.now(timezone.utc).isoformat(),
        "accountValue": acv,
        "positions": len([b for b in st.get("assetPositions",[]) if float(b.get("position",{}).get("szi",0))!=0]),
        "per_coin": per_coin,
        "v3_fills_since_start": sum(d["trades"] for d in per_coin.values()),
    }
    os.makedirs(os.path.dirname(REPORT), exist_ok=True)
    with open(REPORT,"w") as f: json.dump(report,f,indent=2)

    # Rekomendasi: koin non-core di WATCHLIST dengan >=3 trade v3 & net negatif
    recommend = []
    for c,d in per_coin.items():
        if c in CORE: continue
        if d["trades"]>=3 and d["net"]<0:
            recommend.append({"coin":c,"net":round(d["net"],2),"trades":d["trades"]})
    if recommend:
        rec = sorted(recommend, key=lambda x:x["net"])[0]
        with open(OVERRIDE,"w") as f:
            json.dump({"remove":[rec["coin"]],"reason":f"net v3 PnL ${rec['net']} dari {rec['trades']} trade"},f,indent=2)
        # stdout terisi -> cron no_agent kirim alert ringkas
        print(f"🔎 EVAL(v3): {rec['coin']} rugi net ${rec['net']} ({rec['trades']} trade v3) -> ditangguhkan")
    else:
        if os.path.exists(OVERRIDE):
            try:
                before=json.load(open(OVERRIDE))
                if before.get("remove"):
                    print("🔎 EVAL(v3): kinerja pulih, watchlist penuh diaktifkan kembali.")
                    os.remove(OVERRIDE)
            except Exception: pass
    return 0

if __name__=="__main__":
    sys.exit(main())
