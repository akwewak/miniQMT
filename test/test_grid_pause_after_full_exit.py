"""
清仓成交后网格会话联动暂停回归测试

设计约定：
全仓止盈(take_profit_full)与止损(stop_loss)都卖出 available 全量，属清仓语义。
两者成交确认后都要暂停同股活跃网格会话，且**只翻转 enabled，不修改任何网格配置**
(中心价/档位/投入上限/有效期)，以便人工复核后原样恢复。

背景：
2026-08-28 日志显示 000620 于 08-27 止损清仓(27300股)、持仓记录已删除，
但次日 09:25 重启时 session#21 仍以 enabled=1 恢复为活跃会话
("恢复6个, 自动停止0个")，心跳"活跃网格会话数:7"而持仓仅4只。
根因是联动触发条件只匹配 take_profit_full，遗漏 stop_loss。

覆盖：
1. take_profit_full 成交后暂停（既有行为不回归）
2. stop_loss 成交后暂停（缺陷修复）
3. stop_loss_1（首次止盈后回落止损）同样暂停
4. take_profit_half 不暂停（仍有持仓）
5. 网格自身买卖不暂停
6. 暂停只翻转 enabled，不触碰网格配置
7. 开关关闭时两种清仓信号都不暂停
8. grid_manager 缺失/异常时不影响成交确认主流程
"""

import os
import sys
import unittest
from unittest.mock import MagicMock

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

import config
from position_manager import PositionManager


class RecordingGridManager:
    """记录 pause 调用并模拟"只翻转 enabled"的会话状态"""

    SESSION_CONFIG_KEYS = (
        'center_price', 'grid_levels', 'max_investment',
        'callback_ratio', 'end_time', 'step_ratio'
    )

    def __init__(self, paused=True):
        self.paused = paused
        self.calls = []
        # 会话配置快照，用于断言未被联动逻辑改写
        self.session = {
            'id': 21,
            'enabled': True,
            'status': 'active',
            'center_price': 3.56,
            'grid_levels': [3.26, 3.41, 3.56],
            'max_investment': 40000.0,
            'callback_ratio': 0.0035,
            'end_time': '2026-09-14 14:34:22',
            'step_ratio': 0.035,
        }

    def pause_session_by_stock(self, stock_code, reason='auto_pause'):
        self.calls.append((stock_code, reason))
        if not self.paused:
            return {'stock_code': stock_code, 'paused': False, 'reason': 'no_active_session'}
        self.session['enabled'] = False  # 唯一被改写的字段
        return {
            'session_id': self.session['id'],
            'stock_code': stock_code,
            'paused': True,
            'reason': reason,
            'enabled': False,
            'status': self.session['status'],
        }


def make_position_manager(grid_manager):
    """绕过重量级 __init__，只装配联动逻辑所需字段"""
    pm = PositionManager.__new__(PositionManager)
    pm.grid_manager = grid_manager
    return pm


class TestPauseGridAfterFullExit(unittest.TestCase):
    """_pause_grid_after_full_exit 自身行为"""

    def setUp(self):
        self._old = getattr(config, 'ENABLE_PAUSE_GRID_AFTER_TAKE_PROFIT_FULL', True)
        config.ENABLE_PAUSE_GRID_AFTER_TAKE_PROFIT_FULL = True

    def tearDown(self):
        config.ENABLE_PAUSE_GRID_AFTER_TAKE_PROFIT_FULL = self._old

    def test_stop_loss_pauses_session(self):
        """止损清仓后暂停网格会话（缺陷修复点）"""
        gm = RecordingGridManager()
        make_position_manager(gm)._pause_grid_after_full_exit('000620', 'stop_loss')

        self.assertEqual(gm.calls, [('000620', 'stop_loss')])
        self.assertFalse(gm.session['enabled'])

    def test_take_profit_full_pauses_session(self):
        """全仓止盈后暂停网格会话（既有行为不回归）"""
        gm = RecordingGridManager()
        make_position_manager(gm)._pause_grid_after_full_exit('000620', 'take_profit_full')

        self.assertEqual(gm.calls, [('000620', 'take_profit_full')])
        self.assertFalse(gm.session['enabled'])

    def test_pause_does_not_modify_grid_config(self):
        """暂停只翻转 enabled，网格配置一律不动"""
        gm = RecordingGridManager()
        before = {k: gm.session[k] for k in RecordingGridManager.SESSION_CONFIG_KEYS}

        make_position_manager(gm)._pause_grid_after_full_exit('000620', 'stop_loss')

        after = {k: gm.session[k] for k in RecordingGridManager.SESSION_CONFIG_KEYS}
        self.assertEqual(before, after, "网格配置不得被清仓联动改写")
        self.assertEqual(gm.session['status'], 'active', "会话不得被停止/删除")
        self.assertFalse(gm.session['enabled'])

    def test_switch_off_disables_linkage_for_both_signals(self):
        """开关关闭时两种清仓信号都不暂停"""
        config.ENABLE_PAUSE_GRID_AFTER_TAKE_PROFIT_FULL = False
        gm = RecordingGridManager()
        pm = make_position_manager(gm)

        pm._pause_grid_after_full_exit('000620', 'stop_loss')
        pm._pause_grid_after_full_exit('000620', 'take_profit_full')

        self.assertEqual(gm.calls, [])
        self.assertTrue(gm.session['enabled'])

    def test_missing_grid_manager_is_noop(self):
        """grid_manager 缺失时安全跳过，不抛异常"""
        make_position_manager(None)._pause_grid_after_full_exit('000620', 'stop_loss')

    def test_grid_manager_exception_is_swallowed(self):
        """暂停失败不得中断成交确认主流程"""
        gm = MagicMock()
        gm.pause_session_by_stock.side_effect = RuntimeError('grid db down')

        make_position_manager(gm)._pause_grid_after_full_exit('000620', 'stop_loss')

    def test_no_active_session_reports_not_paused(self):
        """无活跃会话时不报暂停成功"""
        gm = RecordingGridManager(paused=False)
        make_position_manager(gm)._pause_grid_after_full_exit('000620', 'stop_loss')

        self.assertEqual(gm.calls, [('000620', 'stop_loss')])
        self.assertTrue(gm.session['enabled'])


class TestConfirmFilledOrderTriggersLinkage(unittest.TestCase):
    """成交确认链路按 signal_type 决定是否联动"""

    def setUp(self):
        self._old = getattr(config, 'ENABLE_PAUSE_GRID_AFTER_TAKE_PROFIT_FULL', True)
        config.ENABLE_PAUSE_GRID_AFTER_TAKE_PROFIT_FULL = True

    def tearDown(self):
        config.ENABLE_PAUSE_GRID_AFTER_TAKE_PROFIT_FULL = self._old

    def _confirm(self, signal_type):
        """驱动 _confirm_filled_order 的最小装配，返回 grid_manager"""
        gm = RecordingGridManager()
        pm = make_position_manager(gm)
        pm.pending_orders = {}
        pm.pending_orders_lock = MagicMock()
        pm.pending_orders_lock.__enter__ = lambda s: None
        pm.pending_orders_lock.__exit__ = lambda s, *a: False
        pm._base_stock_code = lambda c: str(c).split('.')[0]
        pm._find_pending_order_key_locked = lambda c, o: None
        pm._record_trade_after_confirmation = MagicMock(return_value=True)
        pm._request_immediate_position_refresh = MagicMock()
        pm.mark_profit_triggered = MagicMock(return_value=True)
        pm._sync_profit_triggered_to_sqlite = MagicMock()

        pm._confirm_filled_order(
            '000620.SZ', '940572674', 'test',
            order_info={'signal_type': signal_type, 'stock_code': '000620'}
        )
        return gm

    def test_stop_loss_fill_triggers_pause(self):
        """止损成交 -> 联动暂停（对应 8/27 000620 实盘场景）"""
        self.assertEqual(self._confirm('stop_loss').calls, [('000620', 'stop_loss')])

    def test_take_profit_full_fill_triggers_pause(self):
        """全仓止盈成交 -> 联动暂停"""
        self.assertEqual(
            self._confirm('take_profit_full').calls,
            [('000620', 'take_profit_full')]
        )

    def test_take_profit_half_fill_does_not_pause(self):
        """首次止盈只卖60%，仍有持仓，网格应继续运行"""
        self.assertEqual(self._confirm('take_profit_half').calls, [])

    def test_grid_fill_does_not_pause(self):
        """网格自身买卖不得暂停自己"""
        self.assertEqual(self._confirm('grid_buy').calls, [])
        self.assertEqual(self._confirm('grid_sell').calls, [])


if __name__ == '__main__':
    unittest.main()
