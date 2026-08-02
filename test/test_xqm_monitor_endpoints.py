"""XtQuantManager monitor read-only endpoint tests

Web2.0 is a pure monitor — the gateway must serve **real** read-only data.
This module covers the 2026-08-01 monitor-ification:

- /api/status, /api/config no longer return hardcoded True/defaults
- /api/positions injects base_cost_price / stop_profit_enabled
- /api/orders exposes pending orders (previously a blind spot)
- /api/grid/ledger read-only, must not write to monitored DB
"""
import os
import shutil
import sqlite3
import sys
import time
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from fastapi.testclient import TestClient

from xtquant_manager.manager import XtQuantManager
from xtquant_manager.account import AccountConfig, XtQuantAccount
from xtquant_manager.server import create_app
from xtquant_manager.security import SecurityConfig
from test.test_xtquant_manager.mocks import (
    MockXtTrader, MockXtData, MockStockAccount, MockXtOrder,
)

ACC = "test_monitor_a"


class _Order(MockXtOrder):
    def __init__(self, stock_code, order_id, order_type, order_volume,
                 price, order_status, traded_volume=0, order_time=None,
                 status_msg=""):
        super().__init__("STOCK", ACC, stock_code, order_id, order_type,
                         order_volume, price, order_status)
        self.traded_volume = traded_volume
        self.order_time = order_time
        self.status_msg = status_msg


def _inject_account(manager, account_id, positions=None, orders=None):
    cfg = AccountConfig(account_id=account_id, qmt_path="mock")
    acct = XtQuantAccount(cfg)
    trader = MockXtTrader()
    for p in (positions or []):
        trader.add_mock_position(
            stock_code=p["stock_code"], volume=p["volume"],
            cost_price=p.get("cost_price", 10.0),
            current_price=p.get("current_price", 10.5),
        )
    for i, o in enumerate(orders or []):
        trader._orders[i] = o
    acct._xt_trader = trader
    acct._acc = MockStockAccount(account_id)
    acct._xtdata = MockXtData()
    acct._connected = True
    acct._connected_at = time.time()
    acct._last_ping_ok_time = time.time()
    manager._accounts[account_id] = acct
    return acct


class MonitorEndpointTestBase(unittest.TestCase):
    orders = []

    def setUp(self):
        self._prev_instance = getattr(XtQuantManager, "_instance", None)
        XtQuantManager.reset_instance()
        self.manager = XtQuantManager.get_instance()
        _inject_account(self.manager, ACC, positions=[
            {"stock_code": "000001.SZ", "volume": 1000,
             "cost_price": 10.0, "current_price": 10.5},
        ], orders=self.orders)

        self._tmp_dirs = []
        self.db_path = self._db_path(ACC)
        self._init_db()

        sec = SecurityConfig(
            api_token="",
            local_ips=["127.0.0.1", "::1", "localhost", "testclient", "unknown"],
        )
        self.client = TestClient(create_app(sec))

    def _db_path(self, aid):
        tmp_dir = os.path.normpath(
            os.path.join(os.path.dirname(__file__), "..", "data_%s" % aid)
        )
        os.makedirs(tmp_dir, exist_ok=True)
        self._tmp_dirs.append(tmp_dir)
        return os.path.join(tmp_dir, "trading.db")

    def _init_db(self):
        conn = sqlite3.connect(self.db_path)
        conn.execute("""CREATE TABLE IF NOT EXISTS positions (
            stock_code TEXT PRIMARY KEY, stock_name TEXT, volume REAL,
            cost_price REAL, current_price REAL, market_value REAL,
            open_date TIMESTAMP, profit_triggered BOOLEAN DEFAULT FALSE,
            highest_price REAL, stop_loss_price REAL,
            base_cost_price REAL, stop_profit_enabled INTEGER DEFAULT 1)""")
        conn.execute("""CREATE TABLE IF NOT EXISTS system_config (
            config_key TEXT PRIMARY KEY, config_value TEXT, config_type TEXT)""")
        conn.commit()
        conn.close()

    def _set_position(self, code, **kw):
        import json as _j
        conn = sqlite3.connect(self.db_path)
        keys = list(kw.keys())
        vals = [code] + list(kw.values())
        conn.execute(
            "INSERT OR REPLACE INTO positions (stock_code,%s) VALUES (%s)"
            % (",".join(keys), ",".join("?" * len(vals))), vals)
        conn.commit()
        conn.close()

    def _set_config(self, key, value, ctype="float"):
        import json as _j
        conn = sqlite3.connect(self.db_path)
        conn.execute(
            "INSERT OR REPLACE INTO system_config "
            "(config_key, config_value, config_type) VALUES (?,?,?)",
            (key, _j.dumps(value), ctype))
        conn.commit()
        conn.close()

    def tearDown(self):
        for d in self._tmp_dirs:
            shutil.rmtree(d, ignore_errors=True)
        XtQuantManager._instance = self._prev_instance


class TestStatusNoFakeState(MonitorEndpointTestBase):
    def test_unknown_switches_are_null_not_true(self):
        r = self.client.get("/api/status")
        s = r.json()["settings"]
        self.assertIsNone(s["isMonitoring"])
        self.assertIsNone(s["simulationMode"])
        self.assertIsNone(s["positionMonitorRunning"])

    def test_no_switch_is_hardcoded_true(self):
        r = self.client.get("/api/status")
        s = r.json()["settings"]
        for v in s.values():
            if v is True:
                self.fail("no persisted config — no switch should be True")

    def test_persisted_switches_reported_truthfully(self):
        self._set_config("ENABLE_AUTO_TRADING", True, "bool")
        self._set_config("ENABLE_GRID_TRADING", False, "bool")
        self._set_config("ENABLE_ALLOW_BUY", False, "bool")
        r = self.client.get("/api/status")
        s = r.json()["settings"]
        self.assertTrue(s["enableAutoTrading"])
        self.assertFalse(s["enableGridTrading"])
        self.assertFalse(s["allowBuy"])

    def test_account_asset_still_present(self):
        r = self.client.get("/api/status")
        body = r.json()
        self.assertEqual(body["status"], "success")
        self.assertEqual(body["account"]["id"], ACC)


class TestFlaskReverseProbe(unittest.TestCase):
    """ENABLE_AUTO_OPERATION 反向探测

    该开关只存在于主进程内存、按设计不持久化，网关必须反向调用账号的
    Flask /api/status 才能读到真实值。Flask 不可达时必须回落为 None，
    绝不能猜成 False —— 显示"总闸已关"会让人误以为系统安全。
    """

    def setUp(self):
        self._prev_instance = getattr(XtQuantManager, "_instance", None)
        XtQuantManager.reset_instance()
        self.manager = XtQuantManager.get_instance()
        _inject_account(self.manager, ACC, positions=[])

        self._tmp_dir = os.path.normpath(
            os.path.join(os.path.dirname(__file__), "..", "data_%s" % ACC))
        os.makedirs(self._tmp_dir, exist_ok=True)
        db = os.path.join(self._tmp_dir, "trading.db")
        conn = sqlite3.connect(db)
        conn.execute("""CREATE TABLE IF NOT EXISTS system_config (
            config_key TEXT PRIMARY KEY, config_value TEXT, config_type TEXT)""")
        conn.execute("""CREATE TABLE IF NOT EXISTS positions (
            stock_code TEXT PRIMARY KEY, stock_name TEXT)""")
        conn.commit()
        conn.close()

        self.sec = SecurityConfig(
            api_token="",
            local_ips=["127.0.0.1", "::1", "localhost", "testclient", "unknown"])

    def tearDown(self):
        shutil.rmtree(self._tmp_dir, ignore_errors=True)
        XtQuantManager._instance = self._prev_instance

    def _client_with_flask(self, settings=None, reachable=True):
        """构造 app，并 patch urlopen 模拟 Flask 的可达性与响应。

        同时把测试账号注入 config 的账号列表——网关靠它推导 Flask 端口
        （5000 + 索引），账号不在列表中会直接放弃探测。
        """
        import json as _j
        from unittest.mock import patch

        class _Resp:
            def __init__(self, payload):
                self._p = payload.encode("utf-8")
            def read(self):
                return self._p
            def __enter__(self):
                return self
            def __exit__(self, *a):
                return False

        def _fake_urlopen(url, timeout=None):
            if not reachable:
                raise OSError("connection refused")
            return _Resp(_j.dumps({"status": "success", "settings": settings or {}}))

        import config as _config
        p_cfg = patch.object(_config, "get_all_accounts_config",
                             return_value=[{"account_id": ACC}])
        p_cfg.start()
        self.addCleanup(p_cfg.stop)

        p_url = patch("urllib.request.urlopen", side_effect=_fake_urlopen)
        p_url.start()
        self.addCleanup(p_url.stop)
        return TestClient(create_app(self.sec))

    def test_auto_operation_true_is_surfaced(self):
        """主进程总闸开启时，网关如实显示 True"""
        c = self._client_with_flask({"isMonitoring": True})
        s = c.get("/api/status").json()["settings"]
        self.assertTrue(s["isMonitoring"])

    def test_auto_operation_false_is_surfaced(self):
        c = self._client_with_flask({"isMonitoring": False})
        s = c.get("/api/status").json()["settings"]
        self.assertFalse(s["isMonitoring"])

    def test_flask_unreachable_falls_back_to_unknown(self):
        """Flask 不可达（如 QMT_NO_FLASK=1）时必须是 None，不能猜成 False"""
        c = self._client_with_flask(reachable=False)
        s = c.get("/api/status").json()["settings"]
        self.assertIsNone(s["isMonitoring"],
                          "Flask 不可达时总闸必须为未知，不能伪造成已关闭")

    def test_simulation_mode_also_probed(self):
        c = self._client_with_flask({"simulationMode": True})
        s = c.get("/api/status").json()["settings"]
        self.assertTrue(s["simulationMode"])

    def test_position_monitor_running_probed(self):
        c = self._client_with_flask({"positionMonitorRunning": True})
        s = c.get("/api/status").json()["settings"]
        self.assertTrue(s["positionMonitorRunning"])

    def test_live_value_overrides_persisted(self):
        """运行时被改过的开关以主进程内存为准，而非 SQLite 旧值"""
        db = os.path.join(self._tmp_dir, "trading.db")
        conn = sqlite3.connect(db)
        conn.execute(
            "INSERT OR REPLACE INTO system_config VALUES (?,?,?)",
            ("ENABLE_AUTO_TRADING", "false", "bool"))
        conn.commit()
        conn.close()

        c = self._client_with_flask({"enableAutoTrading": True})
        s = c.get("/api/status").json()["settings"]
        self.assertTrue(s["enableAutoTrading"], "内存态应覆盖 SQLite 持久化值")

    def test_persisted_used_when_live_missing_that_key(self):
        """Flask 可达但未返回某键时，回落到 SQLite 持久化值"""
        db = os.path.join(self._tmp_dir, "trading.db")
        conn = sqlite3.connect(db)
        conn.execute(
            "INSERT OR REPLACE INTO system_config VALUES (?,?,?)",
            ("ENABLE_GRID_TRADING", "true", "bool"))
        conn.commit()
        conn.close()

        c = self._client_with_flask({"isMonitoring": True})
        s = c.get("/api/status").json()["settings"]
        self.assertTrue(s["enableGridTrading"])

    def test_config_endpoint_surfaces_global_auto_operation(self):
        """/api/config 的 globalAutoOperation 同样走反向探测"""
        c = self._client_with_flask({"isMonitoring": True, "simulationMode": False})
        data = c.get("/api/config").json()["data"]
        self.assertTrue(data["globalAutoOperation"])
        self.assertFalse(data["simulationMode"])

    def test_config_global_auto_operation_unknown_when_unreachable(self):
        c = self._client_with_flask(reachable=False)
        data = c.get("/api/config").json()["data"]
        self.assertIsNone(data["globalAutoOperation"])

    def test_probe_result_is_cached(self):
        """5 秒内多次请求只探测一次，避免每轮轮询都打 Flask"""
        import json as _j
        from unittest.mock import patch

        calls = []

        class _Resp:
            def read(self):
                return _j.dumps(
                    {"status": "success", "settings": {"isMonitoring": True}}
                ).encode("utf-8")
            def __enter__(self):
                return self
            def __exit__(self, *a):
                return False

        def _counting_urlopen(url, timeout=None):
            calls.append(url)
            return _Resp()

        import config as _config
        with patch.object(_config, "get_all_accounts_config",
                          return_value=[{"account_id": ACC}]), \
             patch("urllib.request.urlopen", side_effect=_counting_urlopen):
            c = TestClient(create_app(self.sec))
            for _ in range(4):
                c.get("/api/status")

        self.assertEqual(len(calls), 1,
                         "5 秒内应只探测一次 Flask，实际 %d 次" % len(calls))

    def test_account_not_in_config_is_not_probed(self):
        """账号不在 account_config.json 中时放弃探测，不能张冠李戴读别人的状态"""
        import json as _j
        from unittest.mock import patch

        calls = []

        def _counting_urlopen(url, timeout=None):
            calls.append(url)
            raise OSError("should not be called")

        import config as _config
        with patch.object(_config, "get_all_accounts_config",
                          return_value=[{"account_id": "some_other_account"}]), \
             patch("urllib.request.urlopen", side_effect=_counting_urlopen):
            c = TestClient(create_app(self.sec))
            s = c.get("/api/status").json()["settings"]

        self.assertEqual(calls, [], "未配置的账号不应发起探测")
        self.assertIsNone(s["isMonitoring"])


class TestConfigNoFakeDefaults(MonitorEndpointTestBase):
    def test_missing_config_returns_none_not_defaults(self):
        data = self.client.get("/api/config").json()["data"]
        self.assertIsNone(data["singleBuyAmount"])
        self.assertIsNone(data["stockStopLoss"])
        self.assertIsNone(data["firstProfitSell"])

    def test_no_legacy_hardcoded_values(self):
        data = self.client.get("/api/config").json()["data"]
        for legacy in (35000, 70000, 400000, 5.0, 7.0, 60.0):
            self.assertNotIn(legacy, data.values(),
                             "legacy default %s should not appear" % legacy)

    def test_persisted_values_converted_to_display_units(self):
        self._set_config("POSITION_UNIT", 35000.0)
        self._set_config("INITIAL_TAKE_PROFIT_RATIO", 0.06)
        self._set_config("STOP_LOSS_RATIO", -0.075)
        self._set_config("MAX_TOTAL_POSITION_RATIO", 0.4)
        data = self.client.get("/api/config").json()["data"]
        self.assertAlmostEqual(data["singleBuyAmount"], 35000.0)
        self.assertAlmostEqual(data["firstProfitSell"], 6.0)
        self.assertAlmostEqual(data["stockStopLoss"], 7.5)
        self.assertAlmostEqual(data["totalMaxPosition"], 400000.0)

    def test_buy_grid_level_converted_to_drop_pct(self):
        self._set_config("BUY_GRID_LEVEL_1", 0.95)
        data = self.client.get("/api/config").json()["data"]
        self.assertAlmostEqual(data["stopLossBuy"], 5.0, places=6)

    def test_non_persisted_switches_are_none(self):
        data = self.client.get("/api/config").json()["data"]
        self.assertIsNone(data["globalAutoOperation"])
        self.assertIsNone(data["simulationMode"])


class TestPositionsExtraFields(MonitorEndpointTestBase):
    def test_base_cost_price_from_sqlite(self):
        self._set_position("000001", stock_name="平安银行", base_cost_price=8.5)
        pos = self.client.get("/api/positions").json()["data"]["positions"][0]
        self.assertAlmostEqual(pos["base_cost_price"], 8.5)

    def test_base_cost_price_falls_back_to_cost_price(self):
        self._set_position("000001", stock_name="平安银行")
        pos = self.client.get("/api/positions").json()["data"]["positions"][0]
        self.assertAlmostEqual(pos["base_cost_price"], pos["cost_price"])

    def test_stop_profit_enabled_false_is_preserved(self):
        self._set_position("000001", stock_name="平安银行", stop_profit_enabled=0)
        pos = self.client.get("/api/positions").json()["data"]["positions"][0]
        self.assertFalse(pos["stop_profit_enabled"])

    def test_stop_profit_enabled_defaults_true(self):
        self._set_position("000001", stock_name="平安银行", stop_profit_enabled=1)
        pos = self.client.get("/api/positions").json()["data"]["positions"][0]
        self.assertTrue(pos["stop_profit_enabled"])

    def test_missing_sqlite_row_defaults_to_enabled(self):
        pos = self.client.get("/api/positions").json()["data"]["positions"][0]
        self.assertTrue(pos["stop_profit_enabled"])

    def test_metrics_ratio_is_decimal(self):
        m = self.client.get("/api/positions").json()["data"]["metrics"]
        self.assertLess(abs(m["total_profit_ratio"]), 1.0)

    def test_positions_all_shares_new_fields(self):
        self._set_position("000001", stock_name="平安银行",
                           base_cost_price=8.5, stop_profit_enabled=0)
        pos = self.client.get("/api/positions-all").json()["data"][0]
        self.assertAlmostEqual(pos["base_cost_price"], 8.5)
        self.assertFalse(pos["stop_profit_enabled"])


class TestOrdersEndpoint(MonitorEndpointTestBase):
    orders = [
        _Order("000001.SZ", 1001, 24, 600, 11.5, 50),
        _Order("000001.SZ", 1002, 23, 1000, 10.0, 56,
               traded_volume=1000, order_time=1753900000),
        _Order("600036.SH", 1003, 24, 500, 36.0, 55,
               traded_volume=200, order_time=1754001000),
    ]

    def test_endpoint_returns_all_orders(self):
        body = self.client.get("/api/orders").json()
        self.assertEqual(body["status"], "success")
        self.assertEqual(len(body["data"]), 3)

    def test_pending_flag_matches_status_code(self):
        data = self.client.get("/api/orders").json()["data"]
        by_id = dict((o["order_id"], o) for o in data)
        self.assertTrue(by_id["1001"]["is_pending"], "status 50 should be pending")
        self.assertFalse(by_id["1002"]["is_pending"], "status 56 should not be pending")
        self.assertTrue(by_id["1003"]["is_pending"], "status 55 should be pending")

    def test_pending_orders_sorted_first(self):
        data = self.client.get("/api/orders").json()["data"]
        self.assertTrue(data[0]["is_pending"])
        self.assertFalse(data[-1]["is_pending"])

    def test_order_type_mapping(self):
        data = self.client.get("/api/orders").json()["data"]
        by_id = dict((o["order_id"], o) for o in data)
        self.assertEqual(by_id["1001"]["trade_type"], "SELL")
        self.assertEqual(by_id["1002"]["trade_type"], "BUY")

    def test_traded_volume_exposed_for_progress(self):
        data = self.client.get("/api/orders").json()["data"]
        by_id = dict((o["order_id"], o) for o in data)
        self.assertEqual(by_id["1003"]["traded_volume"], 200)
        self.assertEqual(by_id["1003"]["volume"], 500)

    def test_status_desc_is_human_readable(self):
        data = self.client.get("/api/orders").json()["data"]
        by_id = dict((o["order_id"], o) for o in data)
        self.assertEqual(by_id["1001"]["status_desc"], "已报")
        self.assertEqual(by_id["1003"]["status_desc"], "部成")

    def test_order_time_formatted_not_raw_timestamp(self):
        import re
        data = self.client.get("/api/orders").json()["data"]
        t = data[0]["order_time"]
        self.assertTrue(re.match(r"^\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2}$", str(t)))

    def test_stock_name_enriched_from_sqlite(self):
        self._set_position("000001", stock_name="平安银行")
        data = self.client.get("/api/orders").json()["data"]
        names = dict((o["order_id"], o["stock_name"]) for o in data)
        self.assertEqual(names["1001"], "平安银行")

    def test_stock_name_falls_back_to_code(self):
        data = self.client.get("/api/orders").json()["data"]
        by_id = dict((o["order_id"], o) for o in data)
        self.assertEqual(by_id["1003"]["stock_name"], by_id["1003"]["stock_code"])


class TestOrdersEmptyCases(MonitorEndpointTestBase):
    orders = []

    def test_no_orders_returns_empty_list(self):
        body = self.client.get("/api/orders").json()
        self.assertEqual(body["status"], "success")
        self.assertEqual(body["data"], [])


class TestGridLedgerReadOnly(MonitorEndpointTestBase):
    def setUp(self):
        super().setUp()
        conn = sqlite3.connect(self.db_path)
        conn.execute("""CREATE TABLE grid_trading_sessions (
            id INTEGER PRIMARY KEY, stock_code TEXT,
            status TEXT, center_price REAL, current_center_price REAL,
            max_investment REAL, current_investment REAL,
            start_time TEXT, end_time TEXT)""")
        conn.execute("""CREATE TABLE grid_lots (
            id INTEGER PRIMARY KEY, session_id INTEGER,
            stock_code TEXT, buy_trade_id TEXT, buy_price REAL,
            original_volume INTEGER, remaining_volume INTEGER,
            realized_volume INTEGER, buy_amount REAL, opened_at TEXT,
            status TEXT)""")
        conn.execute("""CREATE TABLE grid_lot_matches (
            id INTEGER PRIMARY KEY, session_id INTEGER,
            stock_code TEXT, buy_lot_id INTEGER, sell_trade_id TEXT,
            match_type TEXT, volume INTEGER, buy_price REAL, sell_price REAL,
            buy_amount REAL, sell_amount REAL, realized_pnl REAL,
            matched_at TEXT)""")
        conn.execute("""CREATE TABLE grid_trades (
            id INTEGER PRIMARY KEY, session_id INTEGER,
            stock_code TEXT, trade_type TEXT, trigger_price REAL,
            volume INTEGER, amount REAL, grid_level INTEGER,
            trade_id TEXT, trade_time TEXT)""")
        conn.execute(
            "INSERT INTO grid_trading_sessions "
            "(id,stock_code,status,center_price,current_center_price,"
            "max_investment,current_investment,start_time,end_time) "
            "VALUES (1,'000001.SZ','active',10.0,10.5,10000,2500,'2026-07-01','2026-08-01')")
        conn.execute(
            "INSERT INTO grid_lots "
            "(id,session_id,stock_code,buy_trade_id,buy_price,"
            "original_volume,remaining_volume,realized_volume,buy_amount,opened_at,status) "
            "VALUES (1,1,'000001.SZ','B1',10.0,200,100,100,2000,'2026-07-02','open')")
        conn.execute(
            "INSERT INTO grid_lot_matches "
            "(session_id,stock_code,buy_lot_id,sell_trade_id,match_type,"
            "volume,buy_price,sell_price,buy_amount,sell_amount,realized_pnl,matched_at) "
            "VALUES (1,'000001.SZ',1,'S1','matched',100,10.0,11.0,1000,1100,100,'2026-07-10')")
        conn.execute(
            "INSERT INTO grid_trades "
            "(session_id,stock_code,trade_type,trigger_price,"
            "volume,amount,grid_level,trade_id,trade_time) "
            "VALUES (1,'000001.SZ','SELL',11.0,100,1100,1,'S1','2026-07-10 10:00:00')")
        conn.commit()
        conn.close()

    def test_ledger_summary_matches_grid_database_formula(self):
        body = self.client.get("/api/grid/ledger/1").json()
        self.assertTrue(body["success"])
        s = body["summary"]
        self.assertTrue(s["has_ledger"])
        self.assertEqual(s["open_volume"], 100)
        self.assertAlmostEqual(s["open_cost"], 1000.0)
        self.assertAlmostEqual(s["realized_pnl"], 100.0)
        self.assertAlmostEqual(s["unrealized_pnl"], 50.0)
        self.assertAlmostEqual(s["true_pnl"], 150.0)

    def test_lots_and_matches_returned(self):
        body = self.client.get("/api/grid/ledger/1").json()
        self.assertEqual(len(body["lots"]), 1)
        self.assertEqual(len(body["matches"]), 1)

    def test_trades_paginated(self):
        body = self.client.get("/api/grid/ledger/1?limit=1&offset=0").json()
        self.assertEqual(len(body["trades"]), 1)
        self.assertEqual(body["total_count"], 1)
        self.assertFalse(body["pagination"]["has_more"])

    def test_unknown_session_returns_404(self):
        r = self.client.get("/api/grid/ledger/999")
        self.assertEqual(r.status_code, 404)

    def test_ledger_query_does_not_modify_database(self):
        before = (os.path.getmtime(self.db_path), os.path.getsize(self.db_path))
        time.sleep(0.01)
        self.client.get("/api/grid/ledger/1")
        after = (os.path.getmtime(self.db_path), os.path.getsize(self.db_path))
        self.assertEqual(before, after, "ledger query must not write to DB")

    def test_no_journal_or_wal_file_created(self):
        self.client.get("/api/grid/ledger/1")
        for sfx in ("-journal", "-wal"):
            self.assertFalse(os.path.exists(self.db_path + sfx),
                             "should not create %s file" % sfx)


if __name__ == "__main__":
    unittest.main()
