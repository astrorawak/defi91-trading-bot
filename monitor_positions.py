#!/usr/bin/env python3
"""DeFi91 monitor posisi read-only. Berfungsi watchdog: cetak BARIS ALERT hanya
jika ada kondisi berisiko, diam kalau aman. Dipakai cron dengan no_agent=TRUE.

Kondisi alert:
  - posisi dalam <12% dari harga likuidasi
  - accountValue turun >10% dari baseline (file state)
  - posisi barunya yang tidak ada di baseline
Baseline disimpan ~/.defi91_mon_state.json (update tiap jalan aman).
"""
import json, os, sys, re, urllib.request

# Aku pakai alamat utama yang BENAR (bukan env): env HYPERLIQUID_ADDRESS bisa
# berformat desimal tidak valid dan bikin 422. Alamat utama selalu ini.
WALLET = "0x03562722fE32Ff3BaFE214be3F1828A9157eC23D"
_URL = "https://api.hyperliquid.xyz/info"
STATE = os.path.expanduser("~/.defi91_mon_state.json")
LIQ_ALERT_PCT = 12.0   # alert read-only. Harus SAMA dgn LIQ_SAFETY_PCT di github_bot_v3.py (force-close) biar sinkron.
ACV_DROP_PCT = 10.0

def post(p):
    d = json.dumps(p).encode()
    r = urllib.request.Request(_URL, data=d, headers={"Content-Type": "application/json"})
    return json.loads(urllib.request.urlopen(r, timeout=20).read())

def main():
    try:
        st = post({"type": "clearinghouseState", "user": WALLET})
        ma = post({"type": "metaAndAssetCtxs"})
    except Exception as e:
        print(f"[DEFI91-MON] GAGAL ambil data: {e}")
        return 0

    meta, ctxs = ma[0], ma[1]
    acv = float(st["marginSummary"]["accountValue"])
    lines = []
    marks = {}
    for i, u in enumerate(meta["universe"]):
        marks[u["name"]] = float(ctxs[i]["markPx"])

    positions = []
    for b in st["assetPositions"]:
        p = b["position"]
        coin = p["coin"]; sz = float(p["szi"])
        if abs(sz) < 1e-9:
            continue
        mark = marks.get(coin)
        liq = p.get("liquidationPx")
        liq = float(liq) if liq else None
        dist = (abs(mark - liq) / mark * 100) if (liq and mark) else None
        side = "LONG" if sz > 0 else "SHORT"
        positions.append({"coin": coin, "side": side, "sz": sz,
                          "upnl": float(p["unrealizedPnl"]), "dist": dist})
        if dist is not None and dist < LIQ_ALERT_PCT:
            lines.append(f"{coin} {side} JARAK LIKUIDASI {dist:.1f}% < {LIQ_ALERT_PCT}%")

    # baseline
    try:
        state = json.load(open(STATE))
    except Exception:
        state = {"acv": acv, "pos": {f"{p['coin']}{p['side']}": round(p['sz'], 4) for p in positions}}
    prev_acv = state.get("acv", acv)
    drop = (prev_acv - acv) / prev_acv * 100 if prev_acv else 0
    if drop > ACV_DROP_PCT:
        lines.append(f"accountValue turun {drop:.1f}% -> ${acv:.2f}")
    prev_pos = state.get("pos", {})
    cur_pos = {f"{p['coin']}{p['side']}": round(p['sz'], 4) for p in positions}
    new = [k for k in cur_pos if k not in prev_pos]
    if new:
        lines.append(f"posisi BARU dibuka: {', '.join(new)}")

    # update baseline aman
    json.dump({"acv": acv, "pos": cur_pos, "ts": time_now()}, open(STATE, "w"))

    if lines:
        print("\n".join(f"⚠ {l}" for l in lines))
        print(f"accountValue=${acv:.2f} | posisi aktif: {', '.join(f'{p[0]} {p[1]} uPnL=${p[2]:+.2f}' for p in [(x['coin'], x['side'], x['upnl']) for x in positions]) or 'tidak ada'}")
    # kondisi aman -> stdout kosong (watchdog silent)
    return 0

def time_now():
    import datetime
    return datetime.datetime.now(datetime.timezone.utc).isoformat()

if __name__ == "__main__":
    sys.exit(main())
