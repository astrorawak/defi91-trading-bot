"""Tes logika pengawas akun (ops/check_account.py) — murni, tanpa jaringan."""
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "ops"))
import check_account as ca  # noqa: E402


def state(equity=41.0, szi="0.01", entry="60000", liq="50000"):
    ap = []
    if szi:
        ap = [{"position": {"coin": "BTC", "szi": szi, "entryPx": entry, "unrealizedPnl": "0.1",
                            "liquidationPx": liq}}]
    return {"marginSummary": {"accountValue": str(equity), "totalMarginUsed": "2"}, "assetPositions": ap}


def order(kind, side, px, sz="0.01", coin="BTC", ro=True):
    return {"coin": coin, "reduceOnly": ro, "side": side, "sz": sz, "triggerPx": str(px),
            "limitPx": str(px), "orderType": kind, "oid": 1}


MARKS = {"BTC": 60000.0}


def test_flat_account_ok():
    r = ca.analyze(state(szi=None), [], [], MARKS)
    assert r["warnings"] == [] and r["positions"] == []


def test_long_with_valid_stop_and_tp_ok():
    o = [order("Stop Market", "A", 59000), order("Take Profit Market", "A", 61500)]
    r = ca.analyze(state(), o, [], MARKS)
    assert r["warnings"] == [] and r["positions"][0]["stops"] == 1 and r["positions"][0]["tps"] == 1


def test_missing_stop_warns_even_if_tp_exists():
    r = ca.analyze(state(), [order("Take Profit Market", "A", 61500)], [], MARKS)
    assert any("TANPA stop-loss" in w for w in r["warnings"])


def test_stop_on_wrong_side_is_not_valid():
    # long dgn "stop" di ATAS mark = bukan perlindungan
    r = ca.analyze(state(), [order("Stop Market", "A", 61000)], [], MARKS)
    assert any("TANPA stop-loss" in w for w in r["warnings"])


def test_short_position_needs_buy_side_stop_above_mark():
    s = state(szi="-0.01", liq="70000")
    ok = ca.analyze(s, [order("Stop Market", "B", 61000)], [], MARKS)
    bad = ca.analyze(s, [order("Stop Market", "A", 61000)], [], MARKS)   # sisi salah
    assert ok["warnings"] == []
    assert any("TANPA stop-loss" in w for w in bad["warnings"])


def test_equity_floor_and_liq_distance_and_orphans():
    r = ca.analyze(state(equity=36.0, liq="55000"), [order("Stop Market", "A", 59000)], [], MARKS, floor=37)
    txt = " | ".join(r["warnings"])
    assert "PAUSE trader" in txt and "jarak likuidasi" in txt
    orphan = ca.analyze(state(szi=None), [order("Stop Market", "A", 59000)], [], MARKS)
    assert any("YATIM" in w for w in orphan["warnings"])


def test_realized_pnl_24h_net_of_fees():
    now = 1_800_000_000_000
    fills = [{"time": now - 1000, "closedPnl": "0.50", "fee": "0.02"},
             {"time": now - 2000, "closedPnl": "-0.20", "fee": "0.02"},
             {"time": now - 30 * 3600_000, "closedPnl": "9", "fee": "0"}]   # di luar 24 jam
    r = ca.analyze(state(szi=None), [], fills, MARKS, now_ms=now)
    assert r["fills_24h"] == 2 and abs(r["realized_net_24h"] - 0.26) < 1e-9
