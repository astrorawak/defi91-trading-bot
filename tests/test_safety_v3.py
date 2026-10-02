"""Uji keselamatan github_bot_v3 (offline: tanpa kunci, tanpa jaringan, tanpa order nyata).
Jalankan: python3 -m unittest discover -s tests -v
SDK hyperliquid/eth_account di-stub; semua panggilan HTTP di-mock.
"""
import json
import os
import sys
import tempfile
import types
import unittest
from unittest import mock

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

# --- stub SDK (tak perlu terpasang; mencegah import nyata Exchange) ---
for name in ["hyperliquid", "hyperliquid.info", "hyperliquid.exchange", "hyperliquid.utils",
             "eth_account"]:
    sys.modules.setdefault(name, types.ModuleType(name))
sys.modules["hyperliquid.info"].Info = object
sys.modules["hyperliquid.exchange"].Exchange = object
sys.modules["hyperliquid.utils"].constants = types.SimpleNamespace(MAINNET_API_URL="http://mock")
sys.modules["eth_account"].Account = object
os.environ["HYPERLIQUID_PRIVATE_KEY"] = ""
os.environ["HOME"] = tempfile.mkdtemp()   # override self-eval tidak dibaca dari host

import github_bot_v3 as bot  # noqa: E402

# Bentuk frontendOpenOrders sesuai dokumentasi API Hyperliquid (orderType = string).
def fo(coin="ETH", side="A", sz="0.01", ot="Stop Market", trig="2900", oid=1, ro=True):
    return {"coin": coin, "side": side, "sz": sz, "orderType": ot, "triggerPx": trig,
            "limitPx": trig, "oid": oid, "reduceOnly": ro, "isTrigger": True}

OK_RESP = {"status": "ok", "response": {"type": "order", "data": {"statuses": [{"resting": {"oid": 9}}]}}}
ERR_RESP = {"status": "ok", "response": {"type": "order", "data": {"statuses": [{"error": "rejected"}]}}}


class FakeInfo:
    def __init__(self, orders=None, user_state=None, fail_orders=False, fail_state=False):
        self.orders = orders or []
        self.us = user_state or {}
        self.fail_orders = fail_orders
        self.fail_state = fail_state

    def frontend_open_orders(self, wallet):
        if self.fail_orders:
            raise TimeoutError("timeout")
        return self.orders

    def user_state(self, wallet):
        if self.fail_state:
            raise TimeoutError("timeout")
        return self.us


class FakeExchange:
    def __init__(self, resp=OK_RESP):
        self.resp = resp
        self.bulk = []
        self.modified = []
        self.closed = []

    def bulk_orders(self, orders, grouping="na"):
        self.bulk.append(orders)
        return self.resp

    def modify_order(self, oid, coin, **kw):
        self.modified.append((oid, coin, kw))
        return self.resp

    def market_close(self, coin):
        self.closed.append(coin)


def no_candles(*a, **k):
    return [], [], [], []


class TestSLDetection(unittest.TestCase):
    def test_tp_only_string_is_not_sl(self):
        self.assertEqual(bot.find_sl_orders([fo(ot="Take Profit Market", trig="3500")], "ETH", True), [])

    def test_tp_only_dict_is_not_sl(self):
        o = fo(ot={"trigger": {"tpsl": "tp", "triggerPx": "3500", "isMarket": True}})
        self.assertEqual(bot.find_sl_orders([o], "ETH", True), [])

    def test_sl_string_and_dict(self):
        self.assertEqual(len(bot.find_sl_orders([fo()], "ETH", True)), 1)
        o = fo(ot={"trigger": {"tpsl": "sl", "triggerPx": "2900", "isMarket": True}})
        self.assertEqual(len(bot.find_sl_orders([o], "ETH", True)), 1)

    def test_wrong_side_not_sl(self):
        # posisi LONG butuh SL sisi SELL ('A'); stop BUY bukan pelindung LONG
        self.assertEqual(bot.find_sl_orders([fo(side="B")], "ETH", True), [])
        self.assertEqual(len(bot.find_sl_orders([fo(side="B")], "ETH", False)), 1)

    def test_non_reduce_only_or_other_coin_not_sl(self):
        self.assertEqual(bot.find_sl_orders([fo(ro=False), fo(coin="BTC")], "ETH", True), [])


@mock.patch.object(bot, "get_candles", no_candles)
class TestEnsureProtectiveSL(unittest.TestCase):
    def test_tp_only_full_size_still_places_sl(self):
        """P0 lama: TP penuh dianggap 'kapasitas habis'/SL -> posisi tanpa SL. Kini SL dipasang."""
        info = FakeInfo([fo(ot="Take Profit Market", trig="3500", sz="0.01")])
        ex = FakeExchange()
        self.assertTrue(bot.ensure_protective_sl(ex, info, "w", "ETH", 0.01, 3000.0))
        sl = ex.bulk[0][0]
        self.assertEqual(sl["order_type"]["trigger"]["tpsl"], "sl")
        self.assertFalse(sl["is_buy"])
        self.assertTrue(sl["reduce_only"])
        self.assertEqual(sl["sz"], 0.01)
        self.assertLess(sl["limit_px"], 3000.0)

    def test_full_sl_present_no_action(self):
        ex = FakeExchange()
        self.assertFalse(bot.ensure_protective_sl(ex, FakeInfo([fo(sz="0.01")]), "w", "ETH", 0.01, 3000.0))
        self.assertEqual(ex.bulk, [])

    def test_partial_sl_tops_up_remainder_rounded(self):
        ex = FakeExchange()
        bot.ensure_protective_sl(ex, FakeInfo([fo(sz="0.0033")]), "w", "ETH", 0.01, 3000.0)
        self.assertEqual(ex.bulk[0][0]["sz"], 0.0067)   # dibulatkan ke szDecimals ETH (4)

    def test_short_position_sl_above_mark(self):
        ex = FakeExchange()
        bot.ensure_protective_sl(ex, FakeInfo([]), "w", "ETH", -0.01, 3000.0)
        sl = ex.bulk[0][0]
        self.assertTrue(sl["is_buy"])
        self.assertGreater(sl["limit_px"], 3000.0)

    def test_orders_read_failure_does_not_place_blind(self):
        ex = FakeExchange()
        self.assertFalse(bot.ensure_protective_sl(ex, FakeInfo(fail_orders=True), "w", "ETH", 0.01, 3000.0))
        self.assertEqual(ex.bulk, [])

    def test_rejected_sl_reported_false(self):
        ex = FakeExchange(resp=ERR_RESP)
        self.assertFalse(bot.ensure_protective_sl(ex, FakeInfo([]), "w", "ETH", 0.01, 3000.0))


class TestTrailing(unittest.TestCase):
    def test_tightens_each_sl_only(self):
        info = FakeInfo([fo(sz="0.006", trig="2900", oid=1), fo(sz="0.004", trig="2990", oid=2),
                         fo(ot="Take Profit Market", trig="3500", oid=3)])
        ex = FakeExchange()
        bot._trail_update_sl(ex, info, "ETH", True, 0.01, 2950.0)
        self.assertEqual([m[0] for m in ex.modified], [1])          # 2990 sudah lebih ketat
        self.assertEqual(ex.modified[0][2]["sz"], 0.006)

    def test_never_loosens(self):
        ex = FakeExchange()
        bot._trail_update_sl(ex, FakeInfo([fo(trig="2990")]), "ETH", True, 0.01, 2950.0)
        self.assertEqual(ex.modified, [])


class TestKillSwitch(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self.p = mock.patch.object(bot, "STATE_FILE", os.path.join(self.tmp, "state.json"))
        self.p.start()
        self.today = bot.get_wib_time().strftime("%Y-%m-%d")

    def tearDown(self):
        self.p.stop()

    def info(self, av):
        return FakeInfo(user_state={"marginSummary": {"accountValue": str(av)}})

    def write(self, text):
        with open(bot.STATE_FILE, "w") as f:
            f.write(text)

    def test_fresh_day_sets_baseline(self):
        halted, av, _ = bot.check_kill_switch(self.info(100))
        self.assertFalse(halted)
        with open(bot.STATE_FILE) as f:
            self.assertEqual(json.load(f)["start_equity"], 100.0)

    def test_loss_over_limit_halts_and_persists(self):
        self.write(json.dumps({"date": self.today, "start_equity": 100.0, "halted": False}))
        self.assertTrue(bot.check_kill_switch(self.info(95.9))[0])
        with open(bot.STATE_FILE) as f:
            self.assertTrue(json.load(f)["halted"])
        self.assertTrue(bot.check_kill_switch(self.info(120))[0])   # tetap halted hari itu

    def test_corrupt_state_fails_closed(self):
        self.write("{not json")
        halted, _, msg = bot.check_kill_switch(self.info(100))
        self.assertTrue(halted)
        self.assertIn("fail-closed", msg)
        with open(bot.STATE_FILE) as f:
            self.assertEqual(f.read(), "{not json")   # bukti tak ditimpa

    def test_non_object_state_fails_closed(self):
        self.write("[]")
        self.assertTrue(bot.check_kill_switch(self.info(100))[0])

    def test_invalid_start_equity_fails_closed(self):
        self.write(json.dumps({"date": self.today, "start_equity": 0, "halted": False}))
        self.assertTrue(bot.check_kill_switch(self.info(100))[0])

    def test_api_failure_and_zero_equity_fail_closed(self):
        self.assertTrue(bot.check_kill_switch(FakeInfo(fail_state=True))[0])
        self.assertTrue(bot.check_kill_switch(self.info(0))[0])

    def test_new_day_resets(self):
        self.write(json.dumps({"date": "2000-01-01", "start_equity": 100.0, "halted": True}))
        self.assertFalse(bot.check_kill_switch(self.info(90))[0])


def pos(coin, szi, entry, liq):
    return {"position": {"coin": coin, "szi": str(szi), "entryPx": str(entry),
                         "unrealizedPnl": "0", "liquidationPx": liq}}


@mock.patch.object(bot, "get_candles", no_candles)
@mock.patch.object(bot, "analyze_onchain", lambda c: (0, {}))
@mock.patch.object(bot, "analyze_technical", lambda c: (0, {}))
class TestManagePositions(unittest.TestCase):
    def setUp(self):
        bot._PROTECTION_ERRORS = 0

    def run_manage(self, positions, live, orders=None):
        info = FakeInfo(orders or [], user_state={"assetPositions": positions})
        ex = FakeExchange()
        resp = mock.Mock()
        resp.json.return_value = [{"universe": [{"name": c} for c in live]},
                                  [{"markPx": str(p)} for p in live.values()]]
        with mock.patch.object(bot.requests, "post", return_value=resp):
            bot.manage_open_positions(ex, info, {})
        return ex

    def test_liq_shield_closes_when_live_price_near_liq(self):
        ex = self.run_manage([pos("ETH", 0.01, 3000, "2800")], {"ETH": 2900})
        self.assertEqual(ex.closed, ["ETH"])

    def test_no_hard_close_on_stale_entry_price(self):
        # harga live hilang -> dulu memakai harga entry; kini tidak memutuskan apa pun
        ex = self.run_manage([pos("SOL", 1, 150, "140")], {})
        self.assertEqual(ex.closed, [])
        self.assertEqual(ex.bulk, [])
        self.assertGreater(bot._PROTECTION_ERRORS, 0)

    def test_one_coin_error_does_not_stop_others(self):
        bad = {"position": {"coin": "BAD", "szi": "abc"}}
        ex = self.run_manage([bad, pos("ETH", 0.01, 3000, None)], {"ETH": 3000})
        self.assertEqual(len(ex.bulk), 1)              # ETH tetap dapat AUTO-SL
        self.assertEqual(bot._PROTECTION_ERRORS, 1)

    def test_healthy_position_not_closed(self):
        ex = self.run_manage([pos("ETH", 0.01, 3000, "2000")], {"ETH": 3000}, orders=[fo()])
        self.assertEqual(ex.closed, [])
        self.assertEqual(ex.bulk, [])


class TestMainIsolation(unittest.TestCase):
    def test_entry_crash_still_runs_management(self):
        bot._PROTECTION_ERRORS = 0
        called = []
        with mock.patch.object(bot, "PRIVATE_KEY", "x"), \
             mock.patch.object(bot, "DRY_RUN", False), \
             mock.patch.object(bot, "Info", lambda *a, **k: FakeInfo()), \
             mock.patch.object(bot, "Exchange", lambda *a, **k: FakeExchange()), \
             mock.patch.object(bot, "parse_private_key", lambda k: None), \
             mock.patch.object(bot, "check_kill_switch", side_effect=RuntimeError("boom")), \
             mock.patch.object(bot, "_run_entries", side_effect=RuntimeError("entry boom")), \
             mock.patch.object(bot, "manage_open_positions", lambda *a: called.append(1)):
            rc = bot.main()
        self.assertEqual(called, [1])
        self.assertEqual(rc, 2)


def fake_post_factory(trend=True):
    """Respons API sintetis: candle tren naik kuat, orderbook, funding, mark price."""
    import math
    def candles(n):
        out = []
        px = 100.0
        for i in range(n):
            o = px
            px = px * (1.006 if trend else 1 + 0.004 * math.sin(i))
            out.append({"o": o, "c": px, "h": max(o, px) * 1.002, "l": min(o, px) * 0.998, "v": 1000 + i})
        return out

    def post(url, json=None, timeout=None):
        t = json.get("type")
        r = mock.Mock()
        if t == "candleSnapshot":
            r.json.return_value = candles(120)
        elif t == "l2Book":
            r.json.return_value = {"levels": [[{"sz": "30"}] * 10, [{"sz": "10"}] * 10]}
        elif t == "metaAndAssetCtxs":
            names = ["BTC", "ETH", "BNB", "SOL", "XRP", "DOGE", "ADA", "LINK", "AVAX", "LTC"]
            r.json.return_value = [{"universe": [{"name": n} for n in names]},
                                   [{"markPx": "100", "funding": "0"} for _ in names]]
        else:
            r.json.return_value = {}
        return r
    return post


class TestMainSmoke(unittest.TestCase):
    """main() end-to-end dgn API sintetis: tidak boleh NameError/crash di jalur entry."""

    def setUp(self):
        bot._PROTECTION_ERRORS = 0
        self.tmp = tempfile.mkdtemp()

    def test_dry_run_never_builds_exchange(self):
        built = []
        with mock.patch.object(bot.requests, "post", fake_post_factory()), \
             mock.patch("market_regime_filter.requests.post", fake_post_factory()), \
             mock.patch.object(bot, "DRY_RUN", True), \
             mock.patch.object(bot, "PRIVATE_KEY", "x"), \
             mock.patch.object(bot, "Info", lambda *a, **k: FakeInfo()), \
             mock.patch.object(bot, "Exchange", lambda *a, **k: built.append(1)):
            rc = bot.main()
        self.assertEqual(built, [])
        self.assertEqual(rc, 0)

    def test_live_path_with_fake_exchange_places_bracket(self):
        ex = FakeExchange(resp={"status": "ok", "response": {"data": {"statuses": [
            {"filled": {"avgPx": "100", "totalSz": "0.1"}}, "waitingForTrigger", "waitingForTrigger"]}}})
        ex.update_leverage = lambda *a, **k: None
        us = {"marginSummary": {"accountValue": "100", "totalMarginUsed": "0"}, "assetPositions": []}
        with mock.patch.object(bot.requests, "post", fake_post_factory()), \
             mock.patch("market_regime_filter.requests.post", fake_post_factory()), \
             mock.patch.object(bot, "STATE_FILE", os.path.join(self.tmp, "s.json")), \
             mock.patch.object(bot, "DRY_RUN", False), \
             mock.patch.object(bot, "PRIVATE_KEY", "x"), \
             mock.patch.object(bot, "parse_private_key", lambda k: None), \
             mock.patch.object(bot, "Info", lambda *a, **k: FakeInfo(user_state=us)), \
             mock.patch.object(bot, "Exchange", lambda *a, **k: ex):
            rc = bot.main()
        self.assertEqual(rc, 0)
        self.assertTrue(ex.bulk, "jalur entry tidak pernah mencapai execute_trade")
        legs = ex.bulk[0]
        self.assertEqual([l["order_type"].get("trigger", {}).get("tpsl") for l in legs], [None, "tp", "sl"])
        self.assertTrue(all(l["reduce_only"] for l in legs[1:]))
        self.assertLessEqual(len(ex.bulk), bot.MAX_OPEN_POSITIONS)


if __name__ == "__main__":
    unittest.main()
