"""
test_stop_profit.py — 止盈止损监控模块单元测试

覆盖：
  - StopProfitConfig 默认值与自定义
  - PositionState 初始化
  - 止损信号检测（_check_stop_loss）
  - 首次止盈检测（_check_first_take_profit）—— 突破 + 回撤
  - 动态止盈检测（_check_dynamic_take_profit）
  - 动态止盈价格计算（_calc_dynamic_stop_price）
  - 信号去重（_is_duplicate / _emit_signal）
  - 手动卖出（manual_sell）
  - 状态快照（get_states）
  - 启用/禁用切换（update_config enabled=False）
"""
import sys
import os
import time
import unittest
from unittest.mock import patch

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from xtquant_manager.stop_profit import (
    StopProfitConfig,
    StopProfitMonitor,
    PositionState,
)
from xtquant_manager.manager import XtQuantManager
from xtquant_manager.account import AccountConfig, XtQuantAccount
from test.test_xtquant_manager.mocks import MockXtTrader, MockXtData, MockStockAccount


def _make_mock_account(manager, acc_id="55009640", positions=None):
    """向 manager 注入一个已连接的 mock 账号，可选指定持仓。"""
    cfg = AccountConfig(account_id=acc_id, qmt_path="mock")
    acct = XtQuantAccount(cfg)
    trader = MockXtTrader()
    if positions:
        for p in positions:
            trader.add_mock_position(
                stock_code=p["code"],
                volume=p.get("volume", 1000),
                cost_price=p.get("cost_price", 10.0),
                current_price=p.get("current_price", 10.5),
            )
    acct._xt_trader = trader
    acct._acc = MockStockAccount(acc_id)
    acct._xtdata = MockXtData()
    acct._connected = True
    acct._connected_at = time.time()
    acct._last_ping_ok_time = time.time()
    manager._accounts[acc_id] = acct
    return acct, trader


class TestStopProfitConfig(unittest.TestCase):
    """配置默认值与自定义"""

    def test_defaults(self):
        cfg = StopProfitConfig()
        self.assertTrue(cfg.enabled)
        self.assertEqual(cfg.stop_loss_ratio, -0.075)
        self.assertEqual(cfg.initial_take_profit_ratio, 0.06)
        self.assertEqual(cfg.initial_take_profit_pullback_ratio, 0.005)
        self.assertEqual(cfg.initial_take_profit_sell_ratio, 0.6)
        self.assertEqual(cfg.monitor_interval, 3.0)
        self.assertEqual(cfg.signal_dedup_seconds, 60.0)
        self.assertEqual(len(cfg.dynamic_take_profit), 5)

    def test_custom(self):
        cfg = StopProfitConfig(
            enabled=False,
            stop_loss_ratio=-0.10,
            initial_take_profit_ratio=0.08,
            monitor_interval=5.0,
            signal_dedup_seconds=30.0,
        )
        self.assertFalse(cfg.enabled)
        self.assertEqual(cfg.stop_loss_ratio, -0.10)
        self.assertEqual(cfg.initial_take_profit_ratio, 0.08)
        self.assertEqual(cfg.monitor_interval, 5.0)
        self.assertEqual(cfg.signal_dedup_seconds, 30.0)


class TestDynamicStopPrice(unittest.TestCase):
    """动态止盈价格计算 — 复刻 position_manager.calculate_stop_loss_price()"""

    def setUp(self):
        XtQuantManager.reset_instance()
        self.mgr = XtQuantManager.get_instance()
        self.mon = StopProfitMonitor(self.mgr)
        self.cfg = StopProfitConfig()

    def tearDown(self):
        XtQuantManager.reset_instance()

    def test_no_profit_triggered_returns_fixed_stop_loss(self):
        price, level, coeff = self.mon._calc_dynamic_stop_price(
            cost_price=10.0, highest_price=12.0, profit_triggered=False, cfg=self.cfg
        )
        expected = 10.0 * (1 + self.cfg.stop_loss_ratio)  # 9.25
        self.assertAlmostEqual(price, expected, places=2)
        self.assertEqual(level, 0.0)
        self.assertEqual(coeff, 1.0)

    def test_level_5_percent(self):
        # highest=10.5 (5% profit) → should match (0.05, 0.96) tier
        price, level, coeff = self.mon._calc_dynamic_stop_price(
            cost_price=10.0, highest_price=10.5, profit_triggered=True, cfg=self.cfg
        )
        self.assertAlmostEqual(level, 0.05)
        self.assertAlmostEqual(coeff, 0.96)
        self.assertAlmostEqual(price, 10.5 * 0.96, places=3)

    def test_level_10_percent(self):
        price, level, coeff = self.mon._calc_dynamic_stop_price(
            cost_price=10.0, highest_price=11.0, profit_triggered=True, cfg=self.cfg
        )
        self.assertAlmostEqual(level, 0.10)
        self.assertAlmostEqual(coeff, 0.93)
        self.assertAlmostEqual(price, 11.0 * 0.93, places=3)

    def test_level_15_percent(self):
        price, level, coeff = self.mon._calc_dynamic_stop_price(
            cost_price=10.0, highest_price=11.5, profit_triggered=True, cfg=self.cfg
        )
        self.assertAlmostEqual(level, 0.15)
        self.assertAlmostEqual(coeff, 0.90)

    def test_level_30_percent(self):
        price, level, coeff = self.mon._calc_dynamic_stop_price(
            cost_price=10.0, highest_price=13.0, profit_triggered=True, cfg=self.cfg
        )
        self.assertAlmostEqual(level, 0.30)
        self.assertAlmostEqual(coeff, 0.85)

    def test_below_lowest_tier_falls_back_to_fixed_stop(self):
        # highest=10.4 (4% profit) → below lowest (5%) → fallback to fixed stop
        price, level, coeff = self.mon._calc_dynamic_stop_price(
            cost_price=10.0, highest_price=10.4, profit_triggered=True, cfg=self.cfg
        )
        expected = 10.0 * (1 + self.cfg.stop_loss_ratio)
        self.assertAlmostEqual(price, expected, places=2)
        self.assertEqual(level, 0.0)
        self.assertEqual(coeff, 1.0)

    def test_zero_cost_price(self):
        price, level, coeff = self.mon._calc_dynamic_stop_price(
            cost_price=0.0, highest_price=20.0, profit_triggered=True, cfg=self.cfg
        )
        self.assertEqual(price, 0.0)


class TestSignalDetection(unittest.TestCase):
    """信号检测逻辑（Mock 账号，不真实下单）"""

    def setUp(self):
        XtQuantManager.reset_instance()
        self.mgr = XtQuantManager.get_instance()
        self.cfg = StopProfitConfig(
            enabled=True,
            stop_loss_ratio=-0.075,
            initial_take_profit_ratio=0.06,
            initial_take_profit_pullback_ratio=0.005,
            signal_dedup_seconds=0.1,   # 短期去重方便测试
        )
        self.mon = StopProfitMonitor(self.mgr, self.cfg)
        self.acc_id = "55009640"
        self.stock = "000001.SZ"

    def tearDown(self):
        XtQuantManager.reset_instance()

    def _set_position(self, code, cost, current, volume=1000):
        """设置 mock 持仓价格。"""
        acc = self.mgr._accounts.get(self.acc_id)
        if acc:
            trader = acc._xt_trader
            trader.clear_positions()
            trader.add_mock_position(stock_code=code, volume=volume, cost_price=cost, current_price=current)
            # 更新 account.query_positions() 返回市价
            trader._positions[code].market_value = current * volume

    def _inject_state(self, code, **kw):
        """向 monitor 注入已有持仓状态。"""
        if self.acc_id not in self.mon._states:
            self.mon._states[self.acc_id] = {}
        state = self.mon._states[self.acc_id].get(code)
        if state is None:
            state = PositionState(stock_code=code)
            self.mon._states[self.acc_id][code] = state
        for k, v in kw.items():
            setattr(state, k, v)
        state.last_price = kw.get("last_price", kw.get("highest_price", 10.0))
        state.last_price_time = time.time()
        return state

    # ---- 止损检测 ----

    def test_stop_loss_triggered(self):
        cost, current = 10.0, 9.0  # -10% < -7.5% → trigger
        acc, _ = _make_mock_account(self.mgr, self.acc_id, [
            {"code": self.stock, "volume": 1000, "cost_price": cost, "current_price": current}
        ])
        state = self._inject_state(self.stock, highest_price=cost)
        result = self.mon._check_stop_loss(self.stock, cost, current, 1000, state, self.cfg)
        self.assertIsNotNone(result)
        self.assertEqual(result["reason"], "stop_loss_0")

    def test_stop_loss_not_triggered_above_threshold(self):
        cost, current = 10.0, 9.5  # -5% > -7.5% → no trigger
        state = self._inject_state(self.stock, highest_price=cost)
        result = self.mon._check_stop_loss(self.stock, cost, current, 1000, state, self.cfg)
        self.assertIsNone(result)

    def test_stop_loss_after_profit_triggered(self):
        cost, current = 10.0, 9.0
        state = self._inject_state(self.stock, highest_price=12.0, profit_triggered=True)
        result = self.mon._check_stop_loss(self.stock, cost, current, 1000, state, self.cfg)
        self.assertIsNotNone(result)
        self.assertEqual(result["reason"], "stop_loss_1")

    # ---- 首次止盈检测 ----

    def test_first_take_profit_breakout(self):
        cost, current = 10.0, 10.7  # 7% > 6% → breakout registered
        state = self._inject_state(self.stock, highest_price=current)
        result = self.mon._check_first_take_profit(self.stock, cost, current, 1000, state, self.cfg)
        # Should mark breakout but NOT trigger trade yet
        self.assertIsNone(result)
        self.assertTrue(state.profit_breakout_triggered)
        self.assertAlmostEqual(state.breakout_highest_price, current)

    def test_first_take_profit_pullback_triggers(self):
        cost = 10.0
        # Simulate: breakout at 10.7, then price drops to 10.64 (0.56% pullback > 0.5%)
        state = self._inject_state(
            self.stock, highest_price=10.7,
            profit_breakout_triggered=True, breakout_highest_price=10.7,
        )
        result = self.mon._check_first_take_profit(self.stock, cost, 10.64, 1000, state, self.cfg)
        self.assertIsNotNone(result)
        self.assertIn("pullback_ratio", result)
        self.assertAlmostEqual(result["sell_ratio"], 0.6)

    def test_first_take_profit_no_pullback_no_trigger(self):
        cost = 10.0
        state = self._inject_state(
            self.stock, highest_price=10.7,
            profit_breakout_triggered=True, breakout_highest_price=10.7,
        )
        # Price rises further → no pullback → no trigger
        result = self.mon._check_first_take_profit(self.stock, cost, 10.75, 1000, state, self.cfg)
        self.assertIsNone(result)
        self.assertAlmostEqual(state.breakout_highest_price, 10.75)  # updated

    # ---- 动态止盈检测 ----

    def test_dynamic_take_profit_triggered(self):
        cost, highest = 10.0, 11.0  # 10% profit → tier (0.10, 0.93), stop=11.0*0.93=10.23
        state = self._inject_state(self.stock, highest_price=highest, profit_triggered=True)
        # Price drops below dynamic stop
        result = self.mon._check_dynamic_take_profit(self.stock, cost, 10.20, 1000, state, self.cfg)
        self.assertIsNotNone(result)
        self.assertGreater(result["matched_level"], 0)

    def test_dynamic_take_profit_not_triggered_above_stop(self):
        cost, highest = 10.0, 11.0
        state = self._inject_state(self.stock, highest_price=highest, profit_triggered=True)
        result = self.mon._check_dynamic_take_profit(self.stock, cost, 10.50, 1000, state, self.cfg)
        self.assertIsNone(result)

    def test_dynamic_take_profit_skips_when_available_zero(self):
        # available=0 的检查在 _check_position() 层面，不是 _check_dynamic_take_profit
        cost, highest = 10.0, 11.0
        acc, _ = _make_mock_account(self.mgr, self.acc_id, [
            {"code": self.stock, "volume": 0, "cost_price": cost, "current_price": 10.20}
        ])
        # tick 正常执行，volume=0 → _check_position 第 183 行直接 return，不触发信号
        self.mon._tick()
        # 验证没有产生信号（position volume=0）
        key = self.mon._signal_key(self.acc_id, self.stock, "take_profit_full")
        self.assertFalse(self.mon._is_duplicate(key, 60.0))

    # ---- 信号去重 ----

    def test_signal_dedup_blocks_repeat(self):
        key = self.mon._signal_key(self.acc_id, self.stock, "stop_loss")
        # First: should pass
        self.assertFalse(self.mon._is_duplicate(key, 60.0))
        # Record it
        self.mon._signal_history[key] = time.time()
        # Second: should be blocked
        self.assertTrue(self.mon._is_duplicate(key, 60.0))

    def test_signal_dedup_expires(self):
        key = self.mon._signal_key(self.acc_id, self.stock, "stop_loss")
        self.mon._signal_history[key] = time.time() - 61.0  # 61s ago
        self.assertFalse(self.mon._is_duplicate(key, 60.0))


class TestStateManagement(unittest.TestCase):
    """持仓状态跟踪"""

    def setUp(self):
        XtQuantManager.reset_instance()
        self.mgr = XtQuantManager.get_instance()
        self.mon = StopProfitMonitor(self.mgr)

    def tearDown(self):
        XtQuantManager.reset_instance()

    def test_get_states_empty(self):
        states = self.mon.get_states()
        self.assertEqual(states, {})

    def test_get_states_with_data(self):
        self.mon._states["acc1"] = {
            "000001.SZ": PositionState(stock_code="000001.SZ", highest_price=10.5, profit_triggered=True),
        }
        states = self.mon.get_states()
        self.assertIn("acc1", states)
        self.assertIn("000001.SZ", states["acc1"])
        self.assertTrue(states["acc1"]["000001.SZ"]["profit_triggered"])
        self.assertAlmostEqual(states["acc1"]["000001.SZ"]["highest_price"], 10.5)

    def test_update_config_disables(self):
        self.assertTrue(self.mon.get_config().enabled)
        self.mon.update_config(StopProfitConfig(enabled=False))
        self.assertFalse(self.mon.get_config().enabled)


class TestManualSell(unittest.TestCase):
    """手动卖出"""

    def setUp(self):
        XtQuantManager.reset_instance()
        self.mgr = XtQuantManager.get_instance()
        self.mon = StopProfitMonitor(self.mgr)

    def tearDown(self):
        XtQuantManager.reset_instance()

    def test_manual_sell_with_valid_account(self):
        acc, trader = _make_mock_account(self.mgr, "test_acc", [
            {"code": "000001.SZ", "volume": 1000, "cost_price": 10.0, "current_price": 10.5}
        ])
        order_id = self.mon.manual_sell("test_acc", "000001.SZ", 500, 10.5, "manual")
        self.assertGreater(order_id, 0)

    def test_manual_sell_account_not_found(self):
        order_id = self.mon.manual_sell("no_such", "000001.SZ", 500, 10.0)
        self.assertEqual(order_id, -1)

    def test_manual_sell_disconnected(self):
        acc, _ = _make_mock_account(self.mgr, "disc_acc")
        acc._connected = False
        order_id = self.mon.manual_sell("disc_acc", "000001.SZ", 500, 10.0)
        self.assertEqual(order_id, -1)


class TestPerStockGate(unittest.TestCase):
    """个股级「动态止盈止损」开关（sp_flags）在 _check_position 的门控。

    网关从账号 SQLite 读取 stock_code -> stop_profit_enabled，关闭的股票应跳过 emit；
    缺行/空 map/None 一律按开启处理（向后兼容）。
    """

    def setUp(self):
        XtQuantManager.reset_instance()
        self.mgr = XtQuantManager.get_instance()
        self.cfg = StopProfitConfig(enabled=True, stop_loss_ratio=-0.075)
        self.mon = StopProfitMonitor(self.mgr, self.cfg)
        self.acc_id = "55009640"
        self.stock = "000001.SZ"
        self.acc, _ = _make_mock_account(self.mgr, self.acc_id, [
            {"code": self.stock, "volume": 1000, "cost_price": 10.0, "current_price": 9.0}
        ])
        # cost=10, current=9 → -10% < -7.5% 触发止损，正常会 emit
        self.pos = {"证券代码": self.stock, "股票余额": 1000, "可用余额": 1000,
                    "成本价": 10.0, "市价": 9.0}

    def tearDown(self):
        XtQuantManager.reset_instance()

    def test_disabled_stock_skips_emit(self):
        with patch.object(self.mon, "_emit_signal") as spy:
            self.mon._check_position(self.acc_id, self.acc, self.pos, self.cfg,
                                     sp_flags={"000001": False})
            spy.assert_not_called()

    def test_enabled_stock_emits(self):
        with patch.object(self.mon, "_emit_signal") as spy:
            self.mon._check_position(self.acc_id, self.acc, self.pos, self.cfg,
                                     sp_flags={"000001": True})
            spy.assert_called()

    def test_missing_flag_defaults_enabled(self):
        with patch.object(self.mon, "_emit_signal") as spy:
            self.mon._check_position(self.acc_id, self.acc, self.pos, self.cfg, sp_flags={})
            spy.assert_called()

    def test_none_flags_defaults_enabled(self):
        with patch.object(self.mon, "_emit_signal") as spy:
            self.mon._check_position(self.acc_id, self.acc, self.pos, self.cfg, sp_flags=None)
            spy.assert_called()

    def test_load_flags_missing_db_returns_empty(self):
        """账号 DB 不存在时返回空 map（不抛异常）。"""
        self.assertEqual(self.mon._load_stop_profit_flags("no_such_account_id"), {})


if __name__ == "__main__":
    unittest.main()
