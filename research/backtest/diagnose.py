"""Diagnosa kerugian DNA di data TRAIN saja: PnL per alasan exit, per tahap, per koin, per arah."""
import sys
from collections import defaultdict
sys.argv = sys.argv[:3]
import backtest as bt  # noqa: E402

data = bt.load()
cfg = bt.de.DnaConfig()
times, sig = bt.precompute(data, cfg.spot_strong)
n = len(times)
mid = bt.WARM + (n - bt.WARM) // 2
tr, cv, rs = bt.run(times, sig, "dna", cfg, bt.WARM, mid)
for t in tr:
    t["kind_stage"] = f"{t['kind']}/{t['stage']}"
    t["dir_s"] = "LONG" if t["dir"] == 1 else "SHORT"
    e = t["ext"]
    t["ext_b"] = "ext<0 (pullback)" if e < 0 else ("0-1 ATR" if e < 1 else ("1-2 ATR" if e < 2 else ">=2 ATR"))
for key in ("why", "kind_stage", "dir_s", "ext_b"):
    agg = defaultdict(lambda: [0, 0.0])
    for t in tr:
        agg[t[key]][0] += 1
        agg[t[key]][1] += t["pnl"]
    print(f"== per {key}")
    for k, (c, p) in sorted(agg.items(), key=lambda x: x[1][1]):
        print(f"   {k:45s} n={c:4d} pnl={p:+.2f} avg={p/c:+.3f}")
