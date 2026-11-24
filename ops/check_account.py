#!/usr/bin/env python3
"""check_account.py — pengawas akun DeFi91 BACA-SAJA (tanpa key, tanpa order).

Pakai:  python3 ops/check_account.py [--wallet 0x...] [--floor 37] [--json]
Exit code 0 = tidak ada peringatan, 1 = ada peringatan (cetak baris ⚠), 2 = gagal ambil data.

Yang diperiksa (semua dari API info publik Hyperliquid):
  - ekuitas perp & margin terpakai; ekuitas <= --floor  -> PERINGATAN
  - tiap posisi: sisi, ukuran, entry, mark, uPnL, jarak likuidasi (<15% -> PERINGATAN)
  - tiap posisi harus punya STOP reduce-only di sisi yang benar (jika tidak -> PERINGATAN)
    dan TP; total ukuran reduce-only dibanding ukuran posisi
  - order reduce-only yatim (tanpa posisi) -> PERINGATAN
  - fill 24 jam terakhir: jumlah, PnL terealisasi bersih (closedPnl - fee)
Bukan sertifikat keamanan: hanya potret saat dijalankan.
"""
import argparse
import json
import sys
import time
import urllib.request

WALLET = "0x03562722fE32Ff3BaFE214be3F1828A9157eC23D"
URL = "https://api.hyperliquid.xyz/info"


def post(payload, timeout=20):
    req = urllib.request.Request(URL, data=json.dumps(payload).encode(),
                                 headers={"Content-Type": "application/json"})
    return json.loads(urllib.request.urlopen(req, timeout=timeout).read())


def _f(x, d=0.0):
    try:
        return float(x)
    except Exception:
        return d


def analyze(state, orders, fills, marks, floor=37.0, now_ms=None):
    """Murni (tanpa jaringan) -> dict laporan + daftar peringatan."""
    now_ms = now_ms or int(time.time() * 1000)
    ms = state.get("marginSummary", {})
    equity = _f(ms.get("accountValue"))
    used = _f(ms.get("totalMarginUsed"))
    warns, positions = [], []
    if equity <= floor:
        warns.append(f"ekuitas ${equity:.2f} <= batas ${floor:.2f} -> PAUSE trader")

    pos_by_coin = {}
    for ap in state.get("assetPositions", []):
        p = ap.get("position", {})
        szi = _f(p.get("szi"))
        if szi != 0:
            pos_by_coin[p.get("coin")] = p

    for coin, p in pos_by_coin.items():
        szi = _f(p.get("szi"))
        long = szi > 0
        mark = marks.get(coin) or _f(p.get("entryPx"))
        liq = _f(p.get("liquidationPx"), None) if p.get("liquidationPx") else None
        dist = abs(mark - liq) / mark * 100 if (liq and mark) else None
        # order penutup = reduce-only, sisi berlawanan (jual utk long, beli utk short)
        closing = [o for o in orders if o.get("coin") == coin and o.get("reduceOnly")
                   and ((o.get("side") == "A") == long)]
        stops = [o for o in closing if "stop" in str(o.get("orderType", "")).lower()]
        tps = [o for o in closing if "take profit" in str(o.get("orderType", "")).lower()]
        red_sz = sum(_f(o.get("sz")) for o in closing)
        # stop harus di sisi rugi: long -> trigger < mark; short -> trigger > mark
        good_stops = []
        for o in stops:
            tp_ = _f(o.get("triggerPx") or o.get("limitPx"))
            if tp_ and ((long and tp_ < mark) or ((not long) and tp_ > mark)):
                good_stops.append(o)
        row = {"coin": coin, "side": "LONG" if long else "SHORT", "size": abs(szi),
               "entry": _f(p.get("entryPx")), "mark": mark, "upnl": _f(p.get("unrealizedPnl")),
               "liq_dist_pct": dist, "stops": len(good_stops), "tps": len(tps),
               "reduce_only_size": red_sz}
        positions.append(row)
        if not good_stops:
            warns.append(f"{coin}: TANPA stop-loss yang valid (reduce-only, sisi rugi)")
        if dist is not None and dist < 15:
            warns.append(f"{coin}: jarak likuidasi {dist:.1f}% (<15%)")

    for o in orders:
        if o.get("reduceOnly") and o.get("coin") not in pos_by_coin:
            warns.append(f"{o.get('coin')}: order reduce-only YATIM (tidak ada posisi) oid={o.get('oid')}")

    since = now_ms - 24 * 3600_000
    recent = [f for f in fills if _f(f.get("time")) >= since]
    realized = sum(_f(f.get("closedPnl")) - _f(f.get("fee")) for f in recent)
    return {"equity": equity, "margin_used": used, "positions": positions,
            "open_orders": len(orders), "fills_24h": len(recent),
            "realized_net_24h": realized, "warnings": warns}


def main(argv=None):
    ap = argparse.ArgumentParser()
    ap.add_argument("--wallet", default=WALLET)
    ap.add_argument("--floor", type=float, default=37.0)
    ap.add_argument("--json", action="store_true")
    a = ap.parse_args(argv)
    try:
        state = post({"type": "clearinghouseState", "user": a.wallet})
        orders = post({"type": "frontendOpenOrders", "user": a.wallet})
        now = int(time.time() * 1000)
        fills = post({"type": "userFillsByTime", "user": a.wallet,
                      "startTime": now - 24 * 3600_000, "endTime": now})
        meta = post({"type": "metaAndAssetCtxs"})
        marks = {u["name"]: _f(meta[1][i].get("markPx")) for i, u in enumerate(meta[0]["universe"])}
    except Exception as e:
        print(f"GAGAL ambil data: {e}")
        return 2
    rep = analyze(state, orders if isinstance(orders, list) else [],
                  fills if isinstance(fills, list) else [], marks, a.floor)
    if a.json:
        print(json.dumps(rep, indent=2))
    else:
        print(f"Ekuitas perp ${rep['equity']:.2f} | margin terpakai ${rep['margin_used']:.2f} | "
              f"open orders {rep['open_orders']} | fill 24j {rep['fills_24h']} | "
              f"realisasi bersih 24j ${rep['realized_net_24h']:+.2f}")
        if not rep["positions"]:
            print("Posisi: tidak ada")
        for r in rep["positions"]:
            d = f"{r['liq_dist_pct']:.1f}%" if r["liq_dist_pct"] is not None else "n/a"
            print(f"  {r['coin']} {r['side']} {r['size']} @ {r['entry']} (mark {r['mark']}) "
                  f"uPnL ${r['upnl']:+.2f} | liq {d} | stop {r['stops']} TP {r['tps']} "
                  f"reduce-only {r['reduce_only_size']}")
        for w in rep["warnings"]:
            print("⚠ " + w)
        if not rep["warnings"]:
            print("OK: tidak ada peringatan")
    return 1 if rep["warnings"] else 0


if __name__ == "__main__":
    sys.exit(main())
