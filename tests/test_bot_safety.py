"""Tes keselamatan github_bot_v3.py dengan mock (tanpa jaringan, tanpa order nyata)."""
import importlib
import json
import os
import sys
import time
from unittest.mock import MagicMock

import pytest

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, REPO)


@pytest.fixture
def bot(tmp_path, monkeypatch):
    monkeypatch.setenv("HOME", str(tmp_path))
    monkeypatch.delenv("HYPERLIQUID_PRIVATE_KEY", raising=False)
    import github_bot_v3
    mod = importlib.reload(github_bot_v3)
    monkeypatch.setattr(mod, "STATE_FILE", str(tmp_path / "v3_daily_state.json"))
    return mod


def test_override_corrupt_is_fail_closed(tmp_path, monkeypatch):
    (tmp_path / ".defi91_watch_override.json").write_text("{rusak")
    monkeypatch.setenv("HOME", str(tmp_path))
    import github_bot_v3
    mod = importlib.reload(github_bot_v3)
    assert mod.WATCHLIST == ["BTC", "ETH", "BNB"]


def test_override_never_removes_core(tmp_path, monkeypatch):
    (tmp_path / ".defi91_watch_override.json").write_text(json.dumps({"remove": ["BTC", "DOGE"]}))
    monkeypatch.setenv("HOME", str(tmp_path))
    import github_bot_v3
    mod = importlib.reload(github_bot_v3)
    assert "BTC" in mod.WATCHLIST and "DOGE" not in mod.WATCHLIST


def test_ceil_size_meets_min_notional(bot):
    for coin, px in (("BTC", 62190.9), ("ETH", 3011.7), ("DOGE", 0.1793), ("XRP", 2.31)):
        sz = bot.ceil_size(coin, bot.MIN_NOTIONAL_USD / px)
        assert sz * px >= bot.MIN_NOTIONAL_USD - 1e-9, coin


def test_execute_trade_aborts_when_leverage_fails(bot):
    ex = MagicMock()
    ex.update_leverage.return_value = {"status": "err", "response": "rejected"}
    res = bot.execute_trade(ex, MagicMock(), "BTC", "LONG", 62000.0, 300.0)
    assert res["success"] is False
    ex.bulk_orders.assert_not_called()


def test_execute_trade_bracket_and_notional(bot):
    ex = MagicMock()
    ex.update_leverage.return_value = {"status": "ok"}
    ex.bulk_orders.return_value = {"status": "ok", "response": {"data": {"statuses": [
        {"filled": {"avgPx": "62010"}}, {"resting": {"oid": 2}}, {"resting": {"oid": 3}}]}}}
    res = bot.execute_trade(ex, MagicMock(), "BTC", "SHORT", 62000.0, 300.0)
    orders = ex.bulk_orders.call_args[0][0]
    assert res["success"] and res["tp_set"] and res["sl_set"]
    assert orders[0]["is_buy"] is False and orders[0]["sz"] * 62000 >= bot.MIN_NOTIONAL_USD
    assert orders[1]["limit_px"] < 62000 < orders[2]["limit_px"]          # TP bawah, SL atas
    assert orders[1]["reduce_only"] and orders[2]["reduce_only"]


def _legacy_manage(bot, monkeypatch, szi, total):
    monkeypatch.setattr(bot, "STRATEGY", "legacy")
    monkeypatch.setattr(bot, "analyze_onchain", lambda c: (total, {}))
    monkeypatch.setattr(bot, "analyze_technical", lambda c: (0, {}))
    monkeypatch.setattr(bot, "get_candles", lambda *a, **k: ([], [], [], []))
    monkeypatch.setattr(bot.requests, "post", MagicMock(side_effect=Exception("offline")))
    info = MagicMock()
    info.user_state.return_value = {"assetPositions": [{"position": {
        "coin": "BTC", "szi": str(szi), "entryPx": "60000", "unrealizedPnl": "1",
        "liquidationPx": None}}]}
    info.frontend_open_orders.return_value = [{"coin": "BTC", "reduceOnly": True,
                                               "orderType": "Stop Market", "side": "A", "sz": "1"}]
    ex = MagicMock()
    bot.manage_open_positions(ex, info, {"BTC": 60000.0})
    return ex


def test_smart_exit_sign_fixed(bot, monkeypatch):
    # LONG + skor LONG kuat -> JANGAN ditutup (bug lama menutupnya)
    assert not _legacy_manage(bot, monkeypatch, 0.01, +8).market_close.called
    # LONG + skor SHORT kuat -> tutup
    assert _legacy_manage(bot, monkeypatch, 0.01, -8).market_close.called
    # SHORT + skor LONG kuat -> tutup
    assert _legacy_manage(bot, monkeypatch, -0.01, +8).market_close.called


def test_dna_exit_never_closes_manual_position(bot, monkeypatch):
    """Posisi yang tidak dibuka bot (tidak ada di state) tidak ditutup oleh alasan strategi."""
    sig = {"bias": -1, "spot": -0.2, "perp": -1, "atr": 300.0, "close": 60000.0,
           "trig": {1: False, -1: True}, "vol24": 1.0}
    monkeypatch.setattr(bot, "dna_signals", lambda c: sig)
    ex = MagicMock()
    closed = bot.dna_manage_position(ex, MagicMock(), "BTC", 0.01, 60000.0, 60000.0, {}, -1)
    assert closed is False and not ex.market_close.called
    state = {"BTC": {"dir": 1, "stage": "MARKING", "opened_ms": int(time.time() * 1000)}}
    closed = bot.dna_manage_position(ex, MagicMock(), "BTC", 0.01, 60000.0, 60000.0, state, -1)
    assert closed is True and ex.market_close.called                  # milik bot -> ditutup


def test_dna_entries_fail_closed_without_fill_history(bot, monkeypatch, capsys):
    info = MagicMock()
    info.user_fills_by_time.side_effect = Exception("offline")
    ex = MagicMock()
    monkeypatch.setattr(bot, "dna_signals", MagicMock())
    bot.run_dna_entries(ex, info, {"BTC": 60000.0}, {"assetPositions": []}, 58.0, 50.0)
    assert not ex.bulk_orders.called and not bot.dna_signals.called
    assert "fail-closed" in capsys.readouterr().out


def test_dna_entries_open_core_marking_and_record_state(bot, monkeypatch):
    sig = {"bias": 1, "spot": 0.2, "perp": -1, "atr": 600.0, "close": 60000.0,
           "trig": {1: True, -1: False}, "vol24": 1.0}
    monkeypatch.setattr(bot, "dna_signals", lambda c: dict(sig) if c == "BTC" else None)
    monkeypatch.setattr(bot, "execute_trade",
                        MagicMock(return_value={"success": True, "entry_price": 60010.0}))
    info = MagicMock()
    info.user_fills_by_time.return_value = []
    bot.run_dna_entries(MagicMock(), info, {"BTC": 60000.0}, {"assetPositions": []}, 58.0, 50.0)
    bot.execute_trade.assert_called_once()
    assert bot.execute_trade.call_args[0][3] == "LONG"
    st = bot.load_dna_state()
    assert st["BTC"]["stage"] == "MARKING" and st["BTC"]["last_add_px"] == 60010.0


def test_dna_entries_never_add_to_losing_position(bot, monkeypatch):
    sig = {"bias": 1, "spot": 0.2, "perp": 1, "atr": 600.0, "close": 59500.0,
           "trig": {1: True, -1: False}, "vol24": 1.0}
    monkeypatch.setattr(bot, "dna_signals", lambda c: dict(sig) if c == "BTC" else None)
    monkeypatch.setattr(bot, "execute_trade", MagicMock())
    info = MagicMock()
    info.user_fills_by_time.return_value = []
    ust = {"assetPositions": [{"position": {"coin": "BTC", "szi": "0.0002", "entryPx": "60000",
                                            "unrealizedPnl": "-0.1", "marginUsed": "2"}}]}
    bot.run_dna_entries(MagicMock(), info, {"BTC": 59500.0}, ust, 58.0, 50.0)
    bot.execute_trade.assert_not_called()


def test_discipline_counts_losing_closes(bot):
    now = int(time.time() * 1000)
    info = MagicMock()
    info.user_fills_by_time.return_value = [
        {"coin": "ETH", "oid": 1, "closedPnl": "-0.30", "fee": "0.01", "time": now - 600_000},
        {"coin": "ETH", "oid": 1, "closedPnl": "-0.10", "fee": "0.01", "time": now - 590_000},
        {"coin": "SOL", "oid": 2, "closedPnl": "0.50", "fee": "0.01", "time": now - 500_000},
        {"coin": "BTC", "oid": 3, "closedPnl": "0", "fee": "0.01", "time": now - 400_000},
    ]
    d = bot.discipline_from_fills(info, now)
    assert set(d["cooldown_until"]) == {"ETH"}
    assert d["cooldown_until"]["ETH"] > now


def test_closed_candles_drop_running_and_reject_gaps(bot, monkeypatch):
    ms = 3600_000
    now = int(time.time() * 1000)
    last_closed = (now // ms - 1) * ms
    rows = [{"t": last_closed - i * ms, "o": 1, "h": 2, "l": 0.5, "c": 1.5, "v": 10}
            for i in range(80)][::-1]
    running = {"t": last_closed + ms, "o": 1, "h": 2, "l": 0.5, "c": 9, "v": 10}
    resp = MagicMock()
    resp.json.return_value = rows + [running]
    monkeypatch.setattr(bot.requests, "post", MagicMock(return_value=resp))
    out = bot.get_closed_candles("BTC", "1h", 80)
    assert out is not None and out["t"][-1] == last_closed and 9 not in out["c"]
    gap = rows[:40] + rows[41:]
    resp.json.return_value = gap
    assert bot.get_closed_candles("BTC", "1h", 70) is None
