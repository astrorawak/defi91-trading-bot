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
    # FIX: dulu fetch userFills digerbang `if pkey:` - padahal endpoint "userFills" ini
    # adalah info publik (dikunci oleh param "user"=alamat wallet, BUKAN signature), sama
    # seperti clearinghouseState/openOrders di bawah yg juga dipanggil tanpa private key.
    # Akibatnya: kalau HYPERLIQUID_PRIVATE_KEY kosong di env cron eval (mis. konfigurasi
    # cron eval dipisah dari cron trading), per_coin selalu kosong -> recommend=[] ->
    # masuk cabang "kinerja pulih" & override (koin yg sedang ditangguhkan krn rugi)
    # DIHAPUS begitu saja, padahal bukan karena kinerja membaik. Sekarang: fetch selalu
    # dicoba; fills_ok menandai berhasil/tidaknya agar keputusan watchlist di bawah tidak
    # salah menganggap "pulih" saat sebenarnya cuma gagal ambil data.
    fills_ok = False
    fills = []
    try:
        fills = post({"type":"userFills","user":WALLET,"startTime":v3_start_ms,"endTime":now})
        fills_ok = True
    except Exception as e:
        print(f"[EVAL] gagal ambil userFills: {e}")
    if fills_ok:
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

    # === RISIKO POSISI TERBUKA (tutup blindspot: sebelum ini HANYA closedPnL) ===
    # Cek live clearinghouseState + openOrders: margin utilization, jarak liq, rugi terbuka,
    # dan keberadaan SL protektif. Keluarkan alert garis bila ada kondisi berisiko.
    try:
        ma = post({"type": "metaAndAssetCtxs"})
        marks = {u["name"]: float(ma[1][i]["markPx"]) for i, u in enumerate(ma[0]["universe"])}
    except Exception:
        marks = {}
    try:
        oo = post({"type": "frontendOpenOrders", "user": WALLET})
    except Exception:
        oo = []

    def has_protective_sl(coin, side, mark):
        """SL protektif = order reduceOnly lawan arah tipe STOP (atau limitPx di sisi protektif
        vs mark). TP (take profit) TIDAK dihitung sebagai SL. Pakai frontendOpenOrders krn
        openOrders tak mengembalikan orderType/triggerPx."""
        lo = [o for o in oo if o["coin"] == coin and o.get("reduceOnly")]
        if not lo:
            return False
        # orderType dari frontendOpenOrders = STRING ('Stop Market'/'Take Profit Market').
        # Hanya langkah "stop" yg berarti SL protektif; TP punya triggerPx & orderType tapi bukan SL.
        if any("stop" in str(o.get("orderType", "")).lower() for o in lo):
            return True
        for o in lo:
            lp = o.get("limitPx")
            if not lp:
                continue
            if side == "LONG" and float(lp) < mark:
                return True
            if side == "SHORT" and float(lp) > mark:
                return True
        return False

    risk_lines = []
    open_risks = []
    mu = (float(st["marginSummary"]["totalMarginUsed"]) / acv * 100) if acv else 0
    for b in st.get("assetPositions", []):
        p = b["position"]; sz = float(p.get("szi", 0))
        if abs(sz) < 1e-9:
            continue
        coin = p["coin"]; side = "LONG" if sz > 0 else "SHORT"
        upnl = float(p.get("unrealizedPnl", 0)); entry = float(p.get("entryPx", 0))
        mark = marks.get(coin, entry)
        liq = p.get("liquidationPx"); liq = float(liq) if liq else None
        liqdist = (abs(mark - liq) / mark * 100) if (liq and mark) else None
        sl_ok = has_protective_sl(coin, side, mark)
        roe = (upnl / acv * 100) if acv else 0
        r = {"coin": coin, "side": side, "sz": sz, "entry": entry, "mark": mark,
             "uPnl": round(upnl, 2), "roePct": round(roe, 1),
             "liqDistPct": (round(liqdist, 1) if liqdist is not None else None),
             "marginUsedPct": round(mu, 1), "hasSL": sl_ok}
        open_risks.append(r)
        prob = []
        if liqdist is not None and liqdist < 15:
            prob.append(f"jarak likuidasi {liqdist:.1f}%")
        if -roe >= 10:
            prob.append(f"rugi terbuka {roe:.0f}% equity")
        if not sl_ok and -roe >= 5:
            prob.append("TANPA SL protektif")
        if prob:
            risk_lines.append(f"{coin} {side}: " + "; ".join(prob) + f" (uPnL=${upnl:.2f}, ROE {roe:+.0f}%)")
    if mu > 90:
        risk_lines.insert(0, f"ACCOUNT margin terpakai {mu:.0f}% (hampir full)")

    report = {
        "ts": datetime.now(timezone.utc).isoformat(),
        "accountValue": acv,
        "positions": len([b for b in st.get("assetPositions",[]) if float(b.get("position",{}).get("szi",0))!=0]),
        "per_coin": per_coin,
        "v3_fills_since_start": sum(d["trades"] for d in per_coin.values()),
        "open_risks": open_risks,
        "margin_used_pct": round(mu, 1),
    }
    os.makedirs(os.path.dirname(REPORT), exist_ok=True)
    with open(REPORT,"w") as f: json.dump(report,f,indent=2)

    # Rekomendasi: SEMUA koin non-core di WATCHLIST dengan >=3 trade v3 & net negatif.
    # FIX: versi lama hanya menangguhkan SATU koin paling rugi (override di-overwrite
    # penuh tiap siklus) -> kalau ada 2+ koin sama-sama rugi, yang tidak "paling rugi"
    # tetap terus trading & terus loss, dan koin yang sudah ditangguhkan bisa "aktif
    # lagi" bukan karena membaik, tapi cuma karena koin lain jadi lebih buruk.
    # Sekarang: tangguhkan SEMUA yang memenuhi syarat sebagai satu set setiap siklus.
    recommend = []
    for c,d in per_coin.items():
        if c in CORE: continue
        if d["trades"]>=3 and d["net"]<0:
            recommend.append({"coin":c,"net":round(d["net"],2),"trades":d["trades"]})
    if not fills_ok:
        # FIX: jangan putuskan apa pun soal watchlist kalau data fills gagal diambil -
        # override/suspend yang sudah ada (kalau ada) dipertahankan apa adanya, BUKAN
        # dianggap "pulih" (lihat catatan FIX di atas dekat fetch userFills).
        print("🔎 EVAL(v3): lewati keputusan watchlist (gagal ambil userFills) - override lama dipertahankan.")
    elif recommend:
        rec_all = sorted(recommend, key=lambda x: x["net"])
        coins = [r["coin"] for r in rec_all]
        detail = ", ".join(f"{r['coin']} ${r['net']}" for r in rec_all)
        with open(OVERRIDE,"w") as f:
            json.dump({"remove":coins,"reason":f"net v3 PnL negatif: {detail}"},f,indent=2)
        # stdout terisi -> cron no_agent kirim alert ringkas
        print(f"🔎 EVAL(v3): rugi net -> ditangguhkan: {', '.join(coins)} ({detail})")
    else:
        if os.path.exists(OVERRIDE):
            try:
                before=json.load(open(OVERRIDE))
                if before.get("remove"):
                    print("🔎 EVAL(v3): kinerja pulih, watchlist penuh diaktifkan kembali.")
                    os.remove(OVERRIDE)
            except Exception: pass
    # Alert risiko posisi terbuka (email: cron no_agent kirim bila stdout non-kosong)
    for line in risk_lines:
        print("🔎 RISK(open): " + line)
    return 0

if __name__=="__main__":
    sys.exit(main())
