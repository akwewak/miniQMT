"""
TradingExecutor.cancel_order 撤单通道回归测试

背景：
2026-08-28 实盘日志出现 "没有找到可用的撤单方法"，网格委托超时撤单失败。
根因是 cancel_order 只探测 xtquant.xttrader 的 create_trader()/cancel_order()
两个早已不存在的接口，实盘直连模式下必然落到 else 分支，撤单能力全程不可用。
既有网格测试把整个 executor Mock 掉，因此该缺陷零覆盖。

覆盖：
1. 实盘撤单委托给 PositionManager._cancel_order（真实交易通道）
2. 撤单失败时如实返回 False
3. 模拟订单(SIM前缀)短路返回，不触碰实盘通道
4. 撤单接口缺失时安全返回 False
5. int 型 order_id 不再触发 AttributeError
6. 不依赖已废弃的 xtt.create_trader / xtt.cancel_order（缺陷复现）
7. 网格 _cancel_grid_order 接真实 TradingExecutor 的端到端链路
"""

import os
import sys
import unittest
from unittest.mock import Mock

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

from xtquant import xttrader as xtt

from grid_trading_manager import GridTradingManager
from trading_executor import TradingExecutor


class FakePositionManager:
    """只暴露 _cancel_order 的最小持仓管理器替身"""

    def __init__(self, result=True):
        self.result = result
        self.calls = []

    def _cancel_order(self, stock_code, order_id):
        self.calls.append((stock_code, order_id))
        return self.result


def make_executor(position_manager):
    """绕过重量级 __init__，只装配 cancel_order 所需依赖"""
    executor = TradingExecutor.__new__(TradingExecutor)
    executor.position_manager = position_manager
    executor.trader = None  # 实盘直连模式下的真实取值
    executor.account_id = '25105132'
    executor.account_type = 'STOCK'
    return executor


class TestExecutorCancelOrder(unittest.TestCase):

    def test_live_cancel_delegates_to_position_manager(self):
        """实盘撤单走 PositionManager._cancel_order 并透传 order_id"""
        pm = FakePositionManager(result=True)
        executor = make_executor(pm)

        self.assertTrue(executor.cancel_order('1209008129'))
        self.assertEqual(len(pm.calls), 1)
        self.assertEqual(pm.calls[0][1], '1209008129')

    def test_stock_code_passed_through_for_logging(self):
        """传入 stock_code 时用作日志标识，未传入时降级为 order#<id>"""
        pm = FakePositionManager(result=True)
        executor = make_executor(pm)

        executor.cancel_order('1209008129', stock_code='301218.SZ')
        self.assertEqual(pm.calls[0][0], '301218.SZ')

        executor.cancel_order('1209008130')
        self.assertEqual(pm.calls[1][0], 'order#1209008130')

    def test_cancel_failure_returns_false(self):
        """底层撤单失败时如实返回 False，不吞掉失败"""
        pm = FakePositionManager(result=False)
        executor = make_executor(pm)

        self.assertFalse(executor.cancel_order('1209008129'))
        self.assertEqual(len(pm.calls), 1)

    def test_simulation_order_short_circuits(self):
        """SIM 前缀订单直接返回 True，不触碰实盘撤单通道"""
        pm = FakePositionManager(result=False)
        executor = make_executor(pm)

        self.assertTrue(executor.cancel_order('SIM202608281452170001'))
        self.assertEqual(pm.calls, [])

    def test_missing_cancel_interface_returns_false(self):
        """撤单接口缺失时安全返回 False，不抛异常"""
        executor = make_executor(object())

        self.assertFalse(executor.cancel_order('1209008129'))

    def test_int_order_id_accepted(self):
        """int 型 order_id 不再触发 startswith 的 AttributeError"""
        pm = FakePositionManager(result=True)
        executor = make_executor(pm)

        self.assertTrue(executor.cancel_order(1209008129))
        self.assertEqual(pm.calls[0][1], '1209008129')

    def test_underlying_exception_returns_false(self):
        """底层撤单抛异常时被捕获并返回 False"""
        pm = Mock()
        pm._cancel_order.side_effect = RuntimeError('QMT boom')
        executor = make_executor(pm)

        self.assertFalse(executor.cancel_order('1209008129'))


class TestCancelOrderLegacyApiRegression(unittest.TestCase):
    """缺陷复现：撤单不得依赖 xtquant.xttrader 上不存在的接口"""

    def test_xttrader_module_lacks_legacy_helpers(self):
        """固化前提：xtquant.xttrader 确实没有 create_trader / cancel_order"""
        self.assertFalse(hasattr(xtt, 'create_trader'))
        self.assertFalse(hasattr(xtt, 'cancel_order'))

    def test_cancel_succeeds_with_trader_none_and_no_module_api(self):
        """实盘直连的真实前提(self.trader=None + 模块无函数式API)下撤单仍须成功

        修复前此用例必然失败：两个分支都进不去，只会打印
        "没有找到可用的撤单方法" 并返回 False。
        """
        pm = FakePositionManager(result=True)
        executor = make_executor(pm)
        self.assertIsNone(executor.trader)

        self.assertTrue(executor.cancel_order('1209008129'))


class TestGridCancelIntegration(unittest.TestCase):
    """网格撤单接真实 TradingExecutor 的端到端链路"""

    def _make_manager(self, executor):
        manager = GridTradingManager.__new__(GridTradingManager)
        manager.executor = executor
        return manager

    def test_grid_cancel_reaches_position_manager(self):
        """_cancel_grid_order -> TradingExecutor.cancel_order -> PositionManager"""
        pm = FakePositionManager(result=True)
        manager = self._make_manager(make_executor(pm))

        self.assertTrue(manager._cancel_grid_order('1209008129'))
        self.assertEqual(pm.calls[0][1], '1209008129')

    def test_grid_cancel_propagates_failure(self):
        """底层撤单失败时网格侧同样得到 False，走人工确认分支"""
        pm = FakePositionManager(result=False)
        manager = self._make_manager(make_executor(pm))

        self.assertFalse(manager._cancel_grid_order('1209008129'))


if __name__ == '__main__':
    unittest.main()
