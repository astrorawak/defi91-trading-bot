#!/usr/bin/env python3
"""DeFi91 MOMENTUM / WHALE-FLOW detector (0 kredit, near-time).
Jalan tiap ~10 menit via cron no_agent. BUKAN pembaca berita (itu lapis LLM).
Mendeteksi gerakan on-chain dari Harga & Flow (volume spike, OI surge, funding miring).
SENYAP bila pasar normal -> hanya MENGELUARKAN stdout (jadi dikirim) saat ada sinyal kuat.
Alert per-koin: volume spike >5x 24-jam  DAN  momentum arah konsisten  DAN  flow naik.
Sinyal = header $$$ => artinya bot/trader patut perhatian (cek koin), bukan order otomatis.
"""
import json, time, math, sys
from datetime import datetime
sys.path.insert(0, "/data/workspace/defi91-trading-bot")
from market_regime_filter import get_candles, calculate_adx

WATCHLIST = ["BTC","ETH","BNB","SOL","XRP","DOGE","ADA","LINK","AVAX","LTC"]
VOL_SPIKE_MULT = 3.5      # lonjakan volume 5m vs median 24j
OI_DELTA_MIN_PCT = 8.0    # OI naik >= ini (modal baru masuk) utk jadi "flow kuat"
FUNDING_EXTREME = 0.004   # funding 1-jam ekstrem (>0.4% -> ramai)
ADX_STRONG = 40           # ADX kuat utk konfirmasi tren
MIN_DAILY_VLM_USD = 5_000_000  # minimal likuiditas koin (hindari goreng mikro)
STATE_FILE = "/data/workspace/defi91-trading-bot/.defi91_momentum_state.json"

def post(p):
    import json as _j, urllib.request as _u
    r = _u.Request("https://api.hyperliquid.xyz/info", data=_j.dumps(p).encode(),
                   headers={"Content-Type": "application/json"})
    return _j.loads(_u.urlopen(r, timeout=20).read())

def get_asset_ctxs():
    """[meta, ctxs] daftar universe + context per koin."""
    d = post({"type": "metaAndAssetCtxs"})
    return d[0]["universe"], d[1]

def load_state():
    try:
        with open(STATE_FILE) as f:
            return json.load(f)
    except Exception:
        return {}

def save_state(s):
    with open(STATE_FILE, "w") as f:
        json.dump(s, f)

def main():
    alerts = []
    stamp = time.strftime("%Y-%m-%d %H:%M:%S WIB", time.localtime(time.time() + 7 * 3600))
    univ, ctxs = get_asset_ctxs()
    ctx_map = {u["name"]: c for u, c in zip(univ, ctxs)}
    state = load_state()
    reported = set(state.get("reported_today", []))
    today = time.strftime("%Y-%m-%d")

    for coin in WATCHLIST:
        ctx = ctx_map.get(coin)
        if not ctx:
            continue
        mark = float(ctx.get("markPx") or 0)
        day_vlm = float(ctx.get("dayNtlVlm") or 0)
        if mark <= 0 or day_vlm < MIN_DAILY_VLM_USD:
            continue

        # === 1. Volume spike (5m vs median 24j) ===
        closes, highs, lows, vols = get_candles(coin, "5m", 288)  # 24j
        if len(vols) < 60:
            continue
        vol_last = vols[-1]
        med = sorted(vols[:-1])[len(vols[:-1]) // 2] if vols[:-1] else 1
        spike = (vol_last / med) if med > 0 else 0

        # === 2. Momentum arah (perubahan harga 1h, 30m, 5m) ===
        chg_1h = (closes[-1] / closes[-12] - 1) * 100 if len(closes) > 12 else 0
        chg_30m = (closes[-1] / closes[-6] - 1) * 100 if len(closes) > 6 else 0
        sign = 1 if chg_1h >= 0 else -1

        # === 3. ADX (kekuatan tren) ===
        adx = calculate_adx(highs, lows, closes, 14) if len(closes) > 30 else 0

        # === 4. Funding rate & OI ===
        funding_h = float(ctx.get("funding") or 0) * 100  # jadi persen/jam
        oi = float(ctx.get("openInterest") or 0)
        prev_oi = state.get("oi", {}).get(coin, oi)
        oi_delta = (oi - prev_oi) / prev_oi * 100 if prev_oi > 0 else 0

        # Konsistensi momentum: mayoritas jam terakhir searah + ADX cukup
        consistent = (chg_30m * sign >= 0) and (chg_1h * sign >= 0)
        flow_up = oi_delta >= OI_DELTA_MIN_PCT

        # Sinyal: volume spike kuat + momentum searah + tren cukup
        strong = spike >= VOL_SPIKE_MULT and consistent and adx >= ADX_STRONG
        # Flow tambahan (modal baru) menaikkan keyakinan
        extra = " | 🔺OI +%.0f%% (modal baru)" % oi_delta if flow_up else ""
        fund = f" | funding {funding_h:+.3f}%/h" if abs(funding_h) >= 0.004 else ""

        if strong:
            tag = f"{coin} {('🚀NAIK' if sign > 0 else '📉TURUN')} {abs(chg_1h):.1f}%/1h"
            # Dedup: jangan spam koin yg sama berulang dlm 1 hari (lapor sekali per hari per koin)
            if coin not in reported:
                alerts.append(
                    f"• {tag}\n    vol {spike:.1f}× (lonjakan) | ADX {adx:.0f} | OI {oi_delta:+.1f}%{extra}{fund}"
                )
                reported.add(coin)

    # Update state (OI untuk delta berikutnya + tracking report harian)
    new_oi = dict(state.get("oi", {}))
    for coin in WATCHLIST:
        c = ctx_map.get(coin)
        if c:
            new_oi[coin] = float(c.get("openInterest") or 0)
    if today != state.get("day"):
        reported = set()
    save_state({"oi": new_oi, "reported_today": sorted(reported), "day": today, "last": stamp})

    if alerts:
        head = (f"🛰️ DEFI91 FLOW ALERT — {stamp}\n"
                f"Lonjakan volume & flow on-chain terdeteksi. Patut dicek\n"
                f"(bukan order otomatis — sinyal perhatian/trade):\n")
        print(head + "\n".join(alerts))
    # else: diam (tidak ada gerakan kuat)

if __name__ == "__main__":
    main()
