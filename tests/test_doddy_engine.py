"""Tes offline otak DNA Doddy (doddy_engine.py). Tanpa jaringan, tanpa order."""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import doddy_engine as de  # noqa: E402

CFG = de.DnaConfig()


def ramp(n, start, step):
    return [start + i * step for i in range(n)]


# ---------------------------------------------------------------- bias
def test_trend_state_up_down_flat():
    assert de.trend_state(ramp(120, 100, 1)) == 1
    assert de.trend_state(ramp(120, 300, -1)) == -1
    assert de.trend_state([100.0] * 120) == 0
    assert de.trend_state(ramp(30, 100, 1)) == 0          # data kurang -> tidak jelas


def test_htf_bias_daily_must_not_oppose():
    up, down, flat = ramp(120, 100, 1), ramp(120, 300, -1), [100.0] * 120
    assert de.htf_bias(up, up) == 1
    assert de.htf_bias(up, flat) == 1          # daily netral boleh
    assert de.htf_bias(up, down) == 0          # daily berlawanan -> WNS
    assert de.htf_bias(down, up) == 0
    assert de.htf_bias(down, flat) == -1


# ---------------------------------------------------------------- flow
def test_spot_cvd_norm_math():
    v = [10.0] * 6
    assert abs(de.spot_cvd_norm(v, [6.0] * 6, 6) - 0.2) < 1e-12   # 60% taker buy
    assert abs(de.spot_cvd_norm(v, [4.0] * 6, 6) + 0.2) < 1e-12
    assert de.spot_cvd_norm(v[:3], [5.0] * 3, 6) is None
    assert de.spot_cvd_norm([0.0] * 6, [0.0] * 6, 6) is None


def test_classify_flow_matrix():
    s = CFG.spot_strong + 0.01
    assert de.classify_flow(1, s, 1) == de.FLOW_CONFIRMED
    assert de.classify_flow(1, s, -1) == de.FLOW_MARKING      # spot memimpin, perp belum ikut
    assert de.classify_flow(1, -s, 1) == de.FLOW_AGAINST
    assert de.classify_flow(1, 0.001, 1) == de.FLOW_WNS        # lemah -> WNS
    assert de.classify_flow(1, None, 1) == de.FLOW_UNKNOWN     # data spot hilang
    assert de.classify_flow(0, s, 1) == de.FLOW_WNS
    assert de.classify_flow(-1, -s, 1) == de.FLOW_MARKING


# ---------------------------------------------------------------- keputusan entry
def dec(**kw):
    base = dict(coin="BTC", bias=1, btc_bias=1, flow=de.FLOW_MARKING, trigger_ok=True,
                position_dir=0, newest_tranche_profit_atr=None, core_in_profit_dir=None,
                cap_allows=True, slots_free=True, discipline_ok=True)
    base.update(kw)
    return de.decide_entry(**base)


def test_core_opens_only_on_marking():
    assert dec().action == "OPEN"
    assert dec(flow=de.FLOW_CONFIRMED).action == "SKIP"      # sudah ramai -> jangan kejar
    assert dec(flow=de.FLOW_WNS).action == "SKIP"
    assert dec(flow=de.FLOW_AGAINST).action == "SKIP"
    assert dec(flow=de.FLOW_UNKNOWN).action == "SKIP"
    assert dec(trigger_ok=False).action == "SKIP"
    assert dec(bias=0).action == "SKIP"


def test_alt_needs_btc_compass_and_core_profit():
    assert dec(coin="SOL").action == "SKIP"                              # belum ada core profit
    assert dec(coin="SOL", core_in_profit_dir=1).action == "OPEN"
    assert dec(coin="SOL", core_in_profit_dir=1, btc_bias=-1).action == "SKIP"
    assert dec(coin="SOL", core_in_profit_dir=-1).action == "SKIP"


def test_never_average_down_never_open_opposite():
    assert dec(position_dir=-1).action == "SKIP"                         # lawan posisi
    assert dec(position_dir=1, newest_tranche_profit_atr=-0.5).action == "SKIP"
    assert dec(position_dir=1, newest_tranche_profit_atr=0.5).action == "SKIP"
    d = dec(position_dir=1, newest_tranche_profit_atr=1.2, flow=de.FLOW_CONFIRMED)
    assert d.action == "ADD"                                             # tambah yang menang
    assert dec(position_dir=1, newest_tranche_profit_atr=1.2, cap_allows=False).action == "SKIP"


def test_discipline_and_slots():
    assert dec(discipline_ok=False).action == "SKIP"
    assert dec(slots_free=False).action == "SKIP"
    # pyramid koin yg sudah ada tetap boleh walau slot simbol penuh
    assert dec(slots_free=False, position_dir=1, newest_tranche_profit_atr=1.5).action == "ADD"


# ---------------------------------------------------------------- manajemen
def test_stop_ladder_long_and_short_only_tightens():
    e, atr = 100.0, 2.0
    assert de.stop_ladder(e, 101.0, atr, 1, 97.0) is None                 # < 1 ATR: belum
    be = de.stop_ladder(e, 102.0, atr, 1, 97.0)
    assert be is not None and be > e                                     # SL entry (+fee)
    assert de.stop_ladder(e, 103.0, atr, 1, 97.0) == e + 0.5 * atr       # SL+
    assert de.stop_ladder(e, 105.0, atr, 1, 97.0) == 105.0 - atr         # trailing
    assert de.stop_ladder(e, 105.0, atr, 1, 104.5) is None               # tidak melonggarkan
    s = de.stop_ladder(e, 97.0, atr, -1, 103.0)
    assert s == e - 0.5 * atr                                            # short mirror


def test_exit_reasons():
    assert de.exit_reason(1, "BTC", -1, -1, de.FLOW_WNS, "MARKING", 1, 0.5) == "bias HTF berbalik"
    assert "kompas" in de.exit_reason(1, "SOL", 1, -1, de.FLOW_WNS, "MARKING", 1, 0.5)
    assert "flow" in de.exit_reason(1, "BTC", 1, 1, de.FLOW_AGAINST, "MARKING", 1, 0.5)
    assert "marking" in de.exit_reason(1, "BTC", 1, 1, de.FLOW_WNS, "MARKING", 9, -0.1)
    assert de.exit_reason(1, "BTC", 1, 1, de.FLOW_WNS, "MARKING", 9, 0.3) is None
    assert de.exit_reason(1, "BTC", 1, 1, de.FLOW_CONFIRMED, "MARKING", 2, 0.1) is None


def test_indicators_need_enough_data():
    assert de.adx_wilder([1] * 10, [1] * 10, [1] * 10) is None    # bukan default 50 palsu
    assert de.rsi_wilder([1, 2]) is None
    assert de.atr_price([1], [1], [1]) is None
