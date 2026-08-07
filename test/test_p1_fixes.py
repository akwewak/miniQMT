"""
P1 修复回归测试

覆盖四项 P1 缺陷的修复：

  P1-1 run_with_timeout 超时泄漏线程可观测
    - 超时且任务已在执行 → 记录泄漏计数
    - 正常返回 / 未开始即取消 → 不计泄漏

  P1-2 重连成功后强制刷新持仓缓存
    - _start_qmt_connect_worker 成功分支置零 last_position_update_time
    - 失败分支不置零

  P1-3 QMT 自行恢复时免去冗余重连
    - ping 成功 → 自恢复 qmt_connected，不触发重连
    - ping 失败 → 维持断连计数
    - 重连进行中 / 模拟模式 / 网关模式 → 一律不探测

  P1-4 瞬时止盈信号保活 + 执行前时效兜底
    - 已入队信号在保活窗口内不因"本轮无信号"被删除（核心缺陷复现）
    - 超出保活窗口 → 正常删除，不长期滞留
    - 网格信号不受保活影响
    - 信号过旧 → validate_trading_signal 拒绝执行（防止旧价格下单）
"""

import sys
import os
import time
import unittest
from datetime import datetime, timedelta
from unittest.mock import MagicMock, patch

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import config
import timeout_utils
from test.test_base import TestBase
from position_manager import PositionManager


class TestP1TimeoutLeakVisibility(TestBase):
    """P1-1: 超时泄漏线程可观测"""

    def setUp(self):
        super().setUp()
        timeout_utils.reset_leaked_call_count()

    def tearDown(self):
        timeout_utils.reset_leaked_call_count()
        super().tearDown()

    def test_p1_1_normal_return_records_no_leak(self):
        result = timeout_utils.run_with_timeout(lambda: 42, 2)
        self.assertEqual(result, 42)
        self.assertEqual(timeout_utils.get_leaked_call_count(), 0,
                         "正常返回不应计入泄漏")

    def test_p1_1_timeout_on_running_task_records_leak(self):
        """核心：超时且任务已在执行（cancel 失败）→ 必须计入泄漏。"""
        with self.assertRaises(Exception):
            timeout_utils.run_with_timeout(lambda: time.sleep(3), 0.1)

        self.assertEqual(
            timeout_utils.get_leaked_call_count(), 1,
            "超时后线程无法回收，必须记录泄漏计数以便观测"
        )

    def test_p1_1_leak_count_accumulates(self):
        for _ in range(3):
            try:
                timeout_utils.run_with_timeout(lambda: time.sleep(3), 0.05)
            except Exception:
                pass
        self.assertEqual(timeout_utils.get_leaked_call_count(), 3,
                         "多次泄漏应累加，便于发现持续增长")


class _P1PositionManagerBase(TestBase):
    def setUp(self):
        super().setUp()
        self.pm = PositionManager()
        self.pm.stop_sync_thread()

    def tearDown(self):
        try:
            self.pm.stop_sync_thread()
            self.pm.memory_conn.close()
        finally:
            super().tearDown()


class TestP1ReconnectCacheRefresh(_P1PositionManagerBase):
    """P1-2: 重连成功后强制刷新持仓缓存"""

    def _make_trader(self, ok=True):
        trader = MagicMock()
        trader.reconnect_xttrader.return_value = ok
        return trader

    def _run_worker_sync(self, ok=True):
        """同步执行重连 worker（把后台线程 join 掉，便于断言）。"""
        self.pm.qmt_trader = self._make_trader(ok=ok)
        self.pm.last_position_update_time = 999999.0
        with patch.object(config, "ENABLE_SIMULATION_MODE", False), \
             patch.object(config, "ENABLE_XTQUANT_MANAGER", False, create=True):
            self.pm._start_qmt_connect_worker(mode="reconnect")
            thread = getattr(self.pm, "_reconnect_thread", None)
            if thread is not None:
                thread.join(timeout=5)

    def test_p1_2_success_resets_position_cache_timestamp(self):
        """核心：重连成功必须置零 last_position_update_time，否则最长 10s 用旧持仓。"""
        self._run_worker_sync(ok=True)

        self.assertTrue(self.pm.qmt_connected)
        self.assertEqual(
            self.pm.last_position_update_time, 0,
            "重连成功后须置零持仓缓存时间戳，强制下轮拉取真实持仓"
        )

    def test_p1_2_failure_does_not_reset_timestamp(self):
        """重连失败不应假装刷新缓存。"""
        self._run_worker_sync(ok=False)

        self.assertFalse(self.pm.qmt_connected)
        self.assertEqual(
            self.pm.last_position_update_time, 999999.0,
            "重连失败时不应改动缓存时间戳"
        )


class TestP1QmtSelfRecoveryProbe(_P1PositionManagerBase):
    """P1-3: QMT 自行恢复探测"""

    def _trader_with_ping(self, ping_result):
        trader = MagicMock()
        trader.ping_xttrader.return_value = ping_result
        return trader

    def test_p1_3_probe_true_when_ping_succeeds(self):
        self.pm.qmt_trader = self._trader_with_ping(True)
        with patch.object(config, "ENABLE_SIMULATION_MODE", False), \
             patch.object(config, "ENABLE_XTQUANT_MANAGER", False, create=True):
            self.assertTrue(self.pm._probe_qmt_recovered())

    def test_p1_3_probe_false_when_ping_fails(self):
        self.pm.qmt_trader = self._trader_with_ping(False)
        with patch.object(config, "ENABLE_SIMULATION_MODE", False), \
             patch.object(config, "ENABLE_XTQUANT_MANAGER", False, create=True):
            self.assertFalse(self.pm._probe_qmt_recovered())

    def test_p1_3_probe_false_when_ping_raises(self):
        trader = MagicMock()
        trader.ping_xttrader.side_effect = RuntimeError("QMT down")
        self.pm.qmt_trader = trader
        with patch.object(config, "ENABLE_SIMULATION_MODE", False), \
             patch.object(config, "ENABLE_XTQUANT_MANAGER", False, create=True):
            self.assertFalse(self.pm._probe_qmt_recovered(),
                             "探测异常须视为未恢复，不能假健康")

    def test_p1_3_probe_false_while_reconnect_in_progress(self):
        """重连进行中不得探测，避免与 worker 抢着改 qmt_connected。"""
        self.pm.qmt_trader = self._trader_with_ping(True)
        self.pm._reconnect_in_progress = True
        try:
            with patch.object(config, "ENABLE_SIMULATION_MODE", False), \
                 patch.object(config, "ENABLE_XTQUANT_MANAGER", False, create=True):
                self.assertFalse(self.pm._probe_qmt_recovered())
        finally:
            self.pm._reconnect_in_progress = False

    def test_p1_3_probe_false_in_simulation_and_gateway_mode(self):
        self.pm.qmt_trader = self._trader_with_ping(True)
        with patch.object(config, "ENABLE_SIMULATION_MODE", True):
            self.assertFalse(self.pm._probe_qmt_recovered())
        with patch.object(config, "ENABLE_SIMULATION_MODE", False), \
             patch.object(config, "ENABLE_XTQUANT_MANAGER", True, create=True):
            self.assertFalse(self.pm._probe_qmt_recovered())


class TestP1SignalKeepAlive(_P1PositionManagerBase):
    """P1-4: 瞬时止盈信号保活 + 执行前时效兜底"""

    STOCK = "600000.SH"

    def _enqueue_signal(self, signal_type="take_profit_half", age_seconds=0):
        self.pm.latest_signals[self.STOCK] = {
            "type": signal_type,
            "info": {"current_price": 10.0, "volume": 1000, "sell_ratio": 60},
            "timestamp": datetime.now() - timedelta(seconds=age_seconds),
        }

    def _detect_with_no_signal(self):
        """模拟「本轮检测不到信号」（价格回踩）。"""
        with patch.object(config, "ENABLE_DYNAMIC_STOP_PROFIT", True), \
             patch.object(config, "ENABLE_AUTO_TRADING", True), \
             patch.object(self.pm, "_is_stop_profit_enabled", return_value=True), \
             patch.object(self.pm, "_has_tracked_pending_order", return_value=False), \
             patch.object(self.pm, "check_trading_signals", return_value=(None, None)):
            return self.pm._detect_and_enqueue_dynamic_signal(self.STOCK, 10.0)

    def test_p1_4_fresh_signal_survives_price_retrace(self):
        """核心缺陷复现：入队后价格回踩，信号不得被删除。"""
        self._enqueue_signal(age_seconds=1)

        with patch.object(config, "ENABLE_DYNAMIC_SIGNAL_KEEPALIVE", True, create=True), \
             patch.object(config, "DYNAMIC_SIGNAL_KEEPALIVE_SECONDS", 90, create=True):
            self._detect_with_no_signal()

        self.assertIn(
            self.STOCK, self.pm.latest_signals,
            "保活窗口内的待消费信号被删除——首次止盈会整单丢失"
        )
        self.assertEqual(self.pm.latest_signals[self.STOCK]["type"], "take_profit_half")

    def test_p1_4_stale_signal_is_dropped_after_window(self):
        """超出保活窗口须正常删除，避免过期信号长期滞留。"""
        self._enqueue_signal(age_seconds=500)

        with patch.object(config, "ENABLE_DYNAMIC_SIGNAL_KEEPALIVE", True, create=True), \
             patch.object(config, "DYNAMIC_SIGNAL_KEEPALIVE_SECONDS", 90, create=True):
            self._detect_with_no_signal()

        self.assertNotIn(self.STOCK, self.pm.latest_signals,
                         "超出保活窗口的信号应被清除")

    def test_p1_4_keepalive_disabled_restores_old_behavior(self):
        """开关关闭时回到原行为（可回退）。"""
        self._enqueue_signal(age_seconds=1)

        with patch.object(config, "ENABLE_DYNAMIC_SIGNAL_KEEPALIVE", False, create=True):
            self._detect_with_no_signal()

        self.assertNotIn(self.STOCK, self.pm.latest_signals)

    def test_p1_4_grid_signal_not_affected_by_keepalive(self):
        """网格信号走独立链路，不归动态信号保活管。"""
        self._enqueue_signal(signal_type="grid_buy", age_seconds=1)

        with patch.object(config, "ENABLE_DYNAMIC_SIGNAL_KEEPALIVE", True, create=True), \
             patch.object(config, "DYNAMIC_SIGNAL_KEEPALIVE_SECONDS", 90, create=True):
            keep = self.pm._should_keep_alive_signal_unlocked(self.STOCK)

        self.assertFalse(keep, "grid_ 前缀信号不应由动态信号保活逻辑处理")

    def test_p1_4_expired_signal_rejected_at_validation(self):
        """时效兜底：过旧信号必须被拒绝，防止以旧价格下单。"""
        self._enqueue_signal(age_seconds=999)
        signal_info = {"current_price": 10.0, "volume": 1000, "sell_ratio": 60}

        with patch.object(config, "DYNAMIC_SIGNAL_MAX_AGE_SECONDS", 120, create=True):
            ok, status, reason = self.pm.validate_trading_signal(
                self.STOCK, "take_profit_half", signal_info, return_reason=True
            )

        self.assertFalse(ok, "过期信号不得执行")
        self.assertEqual(reason, "signal_expired")

    def test_p1_4_fresh_signal_passes_age_check(self):
        """新鲜信号不应被时效兜底误伤（须走到后续校验，而非卡在 signal_expired）。"""
        self._enqueue_signal(age_seconds=1)
        signal_info = {"current_price": 10.0, "volume": 1000, "sell_ratio": 60}

        with patch.object(config, "DYNAMIC_SIGNAL_MAX_AGE_SECONDS", 120, create=True), \
             patch.object(self.pm, "_has_tracked_pending_order", return_value=False), \
             patch.object(self.pm, "_has_pending_orders", return_value=False), \
             patch.object(self.pm, "get_position", return_value=None):
            ok, status, reason = self.pm.validate_trading_signal(
                self.STOCK, "take_profit_half", signal_info, return_reason=True
            )

        self.assertNotEqual(reason, "signal_expired",
                            "新鲜信号不应被判为过期")


if __name__ == "__main__":
    unittest.main(verbosity=2)
