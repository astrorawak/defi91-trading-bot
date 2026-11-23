"""Backtest portofolio DeFi91: legacy v3 (as-is), legacy v3 (smart-exit diperbaiki), DNA Doddy.

Pemakaian: python3 -I backtest.py <repo_dir> <data_dir> [spot_strong]
- Keputusan di CLOSE candle 1h ke-i, eksekusi di OPEN candle i+1 (+slippage).
- SL/TP dicek intrabar candle berikutnya; bila keduanya tersentuh -> SL (pesimistis).
- Fee taker 0.045%/sisi + slippage 0.02%/sisi. Funding diabaikan (dicatat di laporan).
- Akun awal $58, margin $2 x 5x = notional $10 per tranche, cap 15% ekuitas/koin,
  maks 3 simbol, kill-switch harian 4% (hari WIB).
Legacy memakai fungsi ASLI dari github_bot_v3.py & market_regime_filter.py.
Orderbook & funding legacy tidak tersedia historis -> kontribusi 0 (dicatat).
"""
import bisect, json, os, sys
from collections import defaultdict

REPO, DATA = sys.argv[1], sys.argv[2]
sys.path.insert(0, REPO)
import doddy_engine as de          # noqa: E402
import github_bot_v3 as v3         # noqa: E402
import market_regime_filter as mrf  # noqa: E402

H = 3600_000
FEE, SLIP = 0.00045, 0.0002
NOTIONAL, MARGIN, START_EQ = 10.0, 2.0, 58.0
CAP_PCT, MAX_SYMS, KILL_PCT = 0.15, 3, 4.0
COINS = ["BTC", "ETH", "BNB", "SOL", "XRP", "DOGE", "ADA", "LINK", "AVAX", "LTC"]
WARM = 200


def load():
    out = {}
    for c in COINS:
        with open(os.path.join(DATA, f"{c}.json")) as f:
            out[c] = json.load(f)
    return out


def legacy_ad_score(h, l, c, v):
    """Salinan logika calculate_cvd_signal (tanpa fetch) pada 60 bar terakhir."""
    h, l, c, v = h[-60:], l[-60:], c[-60:], v[-60:]
    if len(c) < 30:
        return 0
    ad, s = 0.0, []
    for hi, lo, cl, vo in zip(h, l, c, v):
        ad += (((cl - lo) - (hi - cl)) / (hi - lo) if hi > lo else 0.0) * vo
        s.append(ad)
    win = min(12, len(s) // 2)
    ad_mom = (s[-1] - s[-1 - win]) - (s[-1 - win] - s[-1 - 2 * win])
    pc = (c[-1] - c[-1 - win]) / c[-1 - win]
    if ad_mom > 0:
        return 3 if pc <= 0.002 else (2 if pc < 0.015 else 1)
    if ad_mom < 0:
        return -3 if pc >= -0.002 else (-2 if pc > -0.015 else -1)
    return 0


def legacy_tech_score(c):
    c = c[-120:]
    sc = 0
    rsi = v3.calculate_rsi(c, 14)
    sc += 2 if rsi < 30 else 1 if rsi < 40 else -2 if rsi > 70 else -1 if rsi > 60 else 0
    m, sig = v3.calculate_macd(c)
    hist = m - sig
    sc += (2 if hist > 0 else 1) if m > 0 else ((-2 if hist < 0 else -1) if m < 0 else 0)
    w = c[-30:]
    rng = max(w) - min(w)
    if rng > 0:
        pos = (c[-1] - min(w)) / rng
        sc += 1 if pos < 0.2 else (-1 if pos > 0.8 else 0)
    return sc


def precompute(data, spot_strong):
    base = data["BTC"]["1h"]
    times = [b["t"] for b in base]
    sig = {}
    for coin in COINS:
        d = data[coin]
        idx = {b["t"]: b for b in d["1h"]}
        bars = [idx.get(t) for t in times]
        sp = {r["t"]: r for r in d["spot1h"]}
        t4 = [b["t"] for b in d["4h"]]; c4 = [b["c"] for b in d["4h"]]
        t1d = [b["t"] for b in d["1d"]]; c1d = [b["c"] for b in d["1d"]]
        O, Hh, L, C, V = [], [], [], [], []
        for b in bars:
            if b is None:
                b = {"o": None, "h": None, "l": None, "c": None, "v": None}
            O.append(b["o"]); Hh.append(b["h"]); L.append(b["l"]); C.append(b["c"]); V.append(b["v"])
        SV = [sp[t]["v"] if t in sp else None for t in times]
        STB = [sp[t]["tb"] if t in sp else None for t in times]
        rows = [None] * len(times)
        for i in range(WARM, len(times)):
            if C[i] is None or any(x is None for x in C[i - 150:i + 1]):
                continue
            tc = times[i] + H
            h1, l1, c1, v1 = Hh[i - 150:i + 1], L[i - 150:i + 1], C[i - 150:i + 1], V[i - 150:i + 1]
            j4 = bisect.bisect_right(t4, tc - 4 * H)
            j1 = bisect.bisect_right(t1d, tc - 24 * H)
            cc4, cc1 = c4[max(0, j4 - 120):j4], c1d[max(0, j1 - 120):j1]
            bias = de.htf_bias(cc4, cc1)
            w = de.DnaConfig().flow_window
            sv, stb = SV[i - w + 1:i + 1], STB[i - w + 1:i + 1]
            spot = None if any(x is None for x in sv + stb) else de.spot_cvd_norm(sv, stb, w)
            perp = de.perp_ad_sign(h1, l1, c1, v1, w)
            tl, _ = de.entry_trigger(c1, h1, l1, 1)
            ts, _ = de.entry_trigger(c1, h1, l1, -1)
            atr = de.atr_price(h1, l1, c1, 14)
            # legacy
            adx_l = mrf.calculate_adx(h1[-100:], l1[-100:], c1[-100:], 14)
            bb = mrf.calculate_bollinger_band_width(c1[-100:], 20, 2)
            trending = adx_l > 25 and bb > 2
            tot = legacy_ad_score(h1, l1, c1, v1) + legacy_tech_score(c1)
            if adx_l >= 70 and len(cc4) >= 55:
                ef = v3.ema_calc(cc4[-100:], 20)[-1]; es = v3.ema_calc(cc4[-100:], 50)[-1]
                tot += 4 if ef > es * 1.002 else (-4 if ef < es * 0.998 else 0)
            vol24 = sum((V[k] or 0) * (C[k] or 0) for k in range(i - 23, i + 1))
            rows[i] = {"bias": bias, "spot": spot, "perp": perp, "tl": tl, "ts": ts, "atr": atr,
                       "c": C[i], "trending": trending, "adx_l": adx_l, "tot": tot, "vol24": vol24}
        sig[coin] = {"O": O, "H": Hh, "L": L, "C": C, "rows": rows}
    return times, sig


def wib_day(t):
    return (t + 7 * H) // (24 * H)


def run(times, sig, mode, cfg, start_i, end_i):
    eq_real = START_EQ
    pos = {}                      # coin -> {"dir":, "tr":[...]}
    trades, eq_curve = [], []
    cooldown = defaultdict(int)
    day, day_start_eq, halted, day_losses = None, START_EQ, False, 0
    reasons = defaultdict(int)

    def mtm(i):
        u = 0.0
        for coin, p in pos.items():
            c = sig[coin]["C"][i]
            for t in p["tr"]:
                u += NOTIONAL * (c / t["e"] - 1) * p["dir"]
        return eq_real + u

    def close_tr(coin, t, px, i, why):
        nonlocal eq_real, day_losses
        p = pos[coin]
        d = p["dir"]
        fill = px * (1 - SLIP * d)
        pnl = NOTIONAL * (fill / t["e"] - 1) * d - NOTIONAL * FEE * 2
        eq_real += pnl
        trades.append({"coin": coin, "pnl": pnl, "i": i, "why": why, "stage": t["stage"],
                       "kind": t.get("kind"), "ext": t.get("ext", 0.0), "dir": d})
        reasons[why] += 1
        if pnl < 0:
            cooldown[coin] = i + cfg.loss_cooldown_bars
            day_losses += 1

    for i in range(start_i, end_i - 1):
        t_dec = times[i] + H
        dd = wib_day(t_dec)
        if dd != day:
            day, day_start_eq, halted, day_losses = dd, mtm(i), False, 0
        if (mtm(i) - day_start_eq) / day_start_eq * 100 <= -KILL_PCT:
            halted = True
        R = {c: sig[c]["rows"][i] for c in COINS}
        btc = R["BTC"]
        btc_bias = btc["bias"] if btc else 0

        # ---------- manajemen posisi (keputusan di close i, eksekusi open i+1)
        for coin in list(pos):
            r = R[coin]
            p = pos[coin]
            if r is None:
                continue
            nxt_open = sig[coin]["O"][i + 1]
            if mode == "dna":
                flow_d = de.classify_flow(p["dir"], r["spot"], r["perp"], cfg)
                avg_e = sum(t["e"] for t in p["tr"]) / len(p["tr"])
                pnl_atr = (r["c"] - avg_e) * p["dir"] / r["atr"] if r["atr"] else 0
                why = de.exit_reason(p["dir"], coin, r["bias"], btc_bias, flow_d,
                                     p["tr"][0]["stage"], i - p["tr"][0]["i"], pnl_atr, cfg)
                if why:
                    for t in list(p["tr"]):
                        close_tr(coin, t, nxt_open, i + 1, why)
                    del pos[coin]
                    continue
                for t in p["tr"]:
                    ns = de.stop_ladder(t["e"], r["c"], r["atr"], p["dir"], t["sl"], cfg)
                    if ns is not None:
                        t["sl"] = ns
            else:
                thr = 7
                if mode == "legacy_asis":
                    against = r["tot"] >= thr if p["dir"] == 1 else r["tot"] <= -thr
                else:
                    against = r["tot"] <= -thr if p["dir"] == 1 else r["tot"] >= thr
                if against:
                    for t in list(p["tr"]):
                        close_tr(coin, t, nxt_open, i + 1, "smart-exit")
                    del pos[coin]
                    continue
                for t in p["tr"]:
                    if r["atr"] and (r["c"] - t["e"]) * p["dir"] >= 1.0 * r["atr"]:
                        ns = r["c"] - p["dir"] * 1.5 * r["atr"]
                        if (ns > t["sl"]) if p["dir"] == 1 else (ns < t["sl"]):
                            t["sl"] = ns

        # ---------- entry
        eqm = mtm(i)
        used = sum(len(p["tr"]) for p in pos.values()) * MARGIN
        free_ok = eqm - used >= MARGIN
        if not halted and free_ok:
            if mode == "dna":
                core_dir = None
                for cc in de.CORE_COINS:
                    if cc in pos and R[cc]:
                        p = pos[cc]
                        avg_e = sum(t["e"] for t in p["tr"]) / len(p["tr"])
                        if (R[cc]["c"] - avg_e) * p["dir"] > 0:
                            core_dir = p["dir"]
                            break
                alts = sorted([c for c in COINS if c not in de.CORE_COINS and R[c]],
                              key=lambda c: -R[c]["vol24"])
                order = [c for c in de.CORE_COINS if R[c]] + alts
            else:
                order = [c for c in COINS if R[c]]
            for coin in order:
                r = R[coin]
                eqm = mtm(i)
                used = sum(len(p["tr"]) for p in pos.values()) * MARGIN
                if eqm - used < MARGIN:
                    break
                p = pos.get(coin)
                ntr = len(p["tr"]) if p else 0
                cap_ok = (ntr + 1) * MARGIN <= CAP_PCT * eqm
                atr = r["atr"]
                if not atr:
                    continue
                nxt_open = sig[coin]["O"][i + 1]
                if mode == "dna":
                    bias = r["bias"]
                    flow = de.classify_flow(bias, r["spot"], r["perp"], cfg)
                    trig = r["tl"] if bias == 1 else (r["ts"] if bias == -1 else False)
                    newest = None
                    if p:
                        newest = (r["c"] - p["tr"][-1]["e"]) * p["dir"] / atr
                    disc = i >= cooldown[coin] and day_losses < cfg.max_losses_per_day
                    dec = de.decide_entry(coin, bias, btc_bias, flow, trig,
                                          p["dir"] if p else 0, newest, core_dir, cap_ok,
                                          len(pos) < MAX_SYMS, disc, cfg)
                    if dec.action == "SKIP":
                        continue
                    d, stage = dec.direction, dec.stage
                else:
                    if len(pos) >= MAX_SYMS:
                        break
                    if not cap_ok or not (r["trending"] and r["adx_l"] >= 25):
                        continue
                    if abs(r["tot"]) < 5:
                        continue
                    d, stage = (1 if r["tot"] > 0 else -1), "LEGACY"
                    if (atr * 2.5) / r["c"] * 100 < 0.27:
                        continue
                    if p and p["dir"] == -d:   # order lawan = mengurangi posisi (netting)
                        close_tr(coin, p["tr"][-1], nxt_open, i + 1, "netting")
                        p["tr"].pop()
                        if not p["tr"]:
                            del pos[coin]
                        continue
                fill = nxt_open * (1 + SLIP * d)
                kind = "ADD" if p else ("CORE" if coin in de.CORE_COINS else "ALT")
                c6 = sig[coin]["C"][i - cfg.flow_window]
                ext = (r["c"] - c6) * d / atr if c6 else 0.0
                tr = {"e": fill, "sl": fill - d * cfg.sl_atr * atr, "tp": fill + d * cfg.tp_atr * atr,
                      "i": i + 1, "stage": stage, "kind": kind, "ext": ext}
                if p:
                    p["tr"].append(tr)
                else:
                    pos[coin] = {"dir": d, "tr": [tr]}

        # ---------- intrabar candle i+1: SL/TP
        for coin in list(pos):
            p = pos[coin]
            hi, lo = sig[coin]["H"][i + 1], sig[coin]["L"][i + 1]
            if hi is None:
                continue
            for t in list(p["tr"]):
                if p["dir"] == 1:
                    hit_sl, hit_tp = lo <= t["sl"], hi >= t["tp"]
                else:
                    hit_sl, hit_tp = hi >= t["sl"], lo <= t["tp"]
                if hit_sl:
                    gain = (t["sl"] - t["e"]) * p["dir"] > 0
                    close_tr(coin, t, t["sl"], i + 1, "SL+/trail" if gain else "SL")
                    p["tr"].remove(t)
                elif hit_tp:
                    close_tr(coin, t, t["tp"], i + 1, "TP")
                    p["tr"].remove(t)
            if not p["tr"]:
                del pos[coin]
        eq_curve.append(mtm(i + 1))

    for coin in list(pos):     # tutup sisa di akhir periode
        for t in list(pos[coin]["tr"]):
            close_tr(coin, t, sig[coin]["C"][end_i - 1], end_i - 1, "akhir-periode")
        del pos[coin]
    return trades, eq_curve, reasons


def stats(trades, curve):
    n = len(trades)
    pnl = sum(t["pnl"] for t in trades)
    wins = [t["pnl"] for t in trades if t["pnl"] > 0]
    loss = [t["pnl"] for t in trades if t["pnl"] <= 0]
    peak, mdd = START_EQ, 0.0
    for e in curve:
        peak = max(peak, e)
        mdd = max(mdd, (peak - e) / peak * 100)
    pf = (sum(wins) / -sum(loss)) if loss and sum(loss) < 0 else float("inf")
    return {"trades": n, "net$": round(pnl, 2), "ret%": round(pnl / START_EQ * 100, 1),
            "win%": round(len(wins) / n * 100, 1) if n else 0,
            "avgW": round(sum(wins) / len(wins), 3) if wins else 0,
            "avgL": round(sum(loss) / len(loss), 3) if loss else 0,
            "PF": round(pf, 2), "maxDD%": round(mdd, 1)}


if __name__ == "__main__":
    data = load()
    cfg = de.DnaConfig()
    if len(sys.argv) > 3:
        cfg.spot_strong = float(sys.argv[3])
    times, sig = precompute(data, cfg.spot_strong)
    n = len(times)
    mid = WARM + (n - WARM) // 2
    import datetime as _dt
    f = lambda i: _dt.datetime.utcfromtimestamp(times[i] / 1000).strftime("%Y-%m-%d")
    print(f"Periode: {f(WARM)} .. {f(n-1)} | TRAIN {f(WARM)}..{f(mid)} | TEST {f(mid)}..{f(n-1)}")
    # distribusi |spot| di TRAIN (kalibrasi ambang)
    vals = sorted(abs(sig[c]["rows"][i]["spot"]) for c in COINS for i in range(WARM, mid)
                  if sig[c]["rows"][i] and sig[c]["rows"][i]["spot"] is not None)
    q = lambda p: round(vals[int(p * (len(vals) - 1))], 4)
    print("TRAIN |spot_cvd| persentil 50/60/70/80:", q(.5), q(.6), q(.7), q(.8))
    print("spot_strong dipakai:", cfg.spot_strong)
    for mode in ("legacy_asis", "legacy_fixed", "dna"):
        for name, a, b in (("TRAIN", WARM, mid), ("TEST", mid, n), ("FULL", WARM, n)):
            tr, cv, rs = run(times, sig, mode, cfg, a, b)
            print(f"{mode:13s} {name:5s}", stats(tr, cv))
        print("   exit:", dict(rs))
