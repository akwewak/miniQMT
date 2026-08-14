"""
网格对手价下单 + 涨跌停/停牌防护测试

覆盖：
A. 对手价下单（GRID_USE_COUNTERPARTY_PRICE）
   - 实盘+确认模式: 买入下单 price=None(executor 取卖三价)、卖出 price=None(买三价)
   - 开关关闭: 回退 trigger_price 限价
   - 非确认模式: 即使开关开启也回退 trigger_price(保持 V1 统计一致性)
   - 模拟模式: 不触达 executor 实盘下单
B. 涨跌停/停牌防护（GRID_ENABLE_PRICE_LIMIT_GUARD）
   - 涨停拦截买入、跌停拦截卖出
   - 涨停放行卖出、跌停放行买入（封板方向相反不拦截）
   - 停牌/无现价: 买卖均拦截
   - 涨跌停价获取失败: fail-open 放行
   - 守卫关闭 / 模拟模式: 不拦截
C. _check_tradable / _get_price_limits 单元测试
"""

import os
import sys
import threading
import unittest
from dataclasses import asdict
from datetime import datetime, timedelta
from unittest.mock import Mock

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

import config
from grid_database import DatabaseManager
from grid_trading_manager import GridSession, GridTradingManager, PriceTracker
from position_manager import PositionManager
from trading_executor import TradingExecutor


class _GridGuardTestBase(unittest.TestCase):
    def setUp(self):
        self.db = DatabaseManager(':memory:')
        self.db.init_grid_tables()

        self.position_manager = Mock(spec=PositionManager)
        self.position_manager.signal_lock = threading.Lock()
        self.position_manager.latest_signals = {}
        self.position_manager._increment_data_version = Mock()
        # data_manager: 提供最新价 + xtdata 涨跌停明细
        self.position_manager.data_manager = Mock()
        self.position_manager.data_manager.get_latest_data.return_value = {'lastPrice': 10.0}
        self.position_manager.data_manager.xt = Mock()
        self.position_manager.data_manager.xt.get_instrument_detail.return_value = {
            'UpStopPrice': 11.0, 'DownStopPrice': 9.0
        }
        # 卖出路径预取持仓快照
        self.position_manager.get_position.return_value = {
            'volume': 1000, 'available': 1000, 'cost_price': 10.0
        }

        self.executor = Mock(spec=TradingExecutor)
        self.executor.buy_stock.return_value = {'order_id': 'ORDER_BUY'}
        self.executor.sell_stock.return_value = {'order_id': 'ORDER_SELL'}

        self.manager = GridTradingManager(self.db, self.position_manager, self.executor)

        # 备份相关配置
        self._orig = {
            k: getattr(config, k, None) for k in (
                'ENABLE_SIMULATION_MODE', 'GRID_CONFIRM_LIVE_ORDER_BY_DEAL',
                'GRID_USE_COUNTERPARTY_PRICE', 'GRID_ENABLE_PRICE_LIMIT_GUARD',
                'GRID_PRICE_LIMIT_EPS', 'GRID_SIGNAL_MAX_AGE_SECONDS',
                'GRID_SIGNAL_MAX_PRICE_DRIFT_RATIO', 'GRID_BUY_COOLDOWN',
                'GRID_SELL_COOLDOWN', 'GRID_LEVEL_COOLDOWN',
                'GRID_COUNTERPARTY_BUY_PRICE_BUFFER_RATIO',
            )
        }
        # 默认实盘 + 确认模式 + 两项防护开启；放宽冷却与时效避免干扰
        config.ENABLE_SIMULATION_MODE = False
        config.GRID_CONFIRM_LIVE_ORDER_BY_DEAL = True
        config.GRID_USE_COUNTERPARTY_PRICE = True
        config.GRID_ENABLE_PRICE_LIMIT_GUARD = True
        config.GRID_PRICE_LIMIT_EPS = 0.001
        config.GRID_SIGNAL_MAX_AGE_SECONDS = 0          # 关闭时效校验
        config.GRID_SIGNAL_MAX_PRICE_DRIFT_RATIO = 0    # 关闭漂移校验，专注测目标逻辑
        config.GRID_BUY_COOLDOWN = 0
        config.GRID_SELL_COOLDOWN = 0
        config.GRID_LEVEL_COOLDOWN = 0
        config.GRID_COUNTERPARTY_BUY_PRICE_BUFFER_RATIO = 0.02

    def tearDown(self):
        for k, v in self._orig.items():
            setattr(config, k, v)
        self.db.close()

    def _make_session(self, stock_code='000001.SZ', current_investment=0.0):
        session = GridSession(
            id=None,
            stock_code=stock_code,
            status='active',
            center_price=10.0,
            current_center_price=10.0,
            price_interval=0.05,
            position_ratio=0.25,
            callback_ratio=0.005,
            max_investment=10000,
            current_investment=current_investment,
            start_time=datetime.now(),
            end_time=datetime.now() + timedelta(days=7),
        )
        data = asdict(session)
        data['start_time'] = session.start_time.isoformat()
        data['end_time'] = session.end_time.isoformat()
        session.id = self.db.create_grid_session(data)
        self.manager.sessions[self.manager._normalize_code(stock_code)] = session
        self.manager.trackers[session.id] = PriceTracker(session_id=session.id, last_price=10.0)
        return session

    def _buy_signal(self, session, trigger_price=10.0):
        return {
            'stock_code': session.stock_code,
            'strategy': config.GRID_STRATEGY_NAME,
            'signal_type': 'BUY',
            'grid_level': 9.5,
            'trigger_price': trigger_price,
            'session_id': session.id,
            'timestamp': datetime.now().isoformat(),
            'signal_source': 'grid_tracker',
            'require_price_recheck': True,
            'valley_price': 9.9,
            'callback_ratio': 0.005,
        }

    def _sell_signal(self, session, trigger_price=10.0):
        return {
            'stock_code': session.stock_code,
            'strategy': config.GRID_STRATEGY_NAME,
            'signal_type': 'SELL',
            'grid_level': 10.5,
            'trigger_price': trigger_price,
            'session_id': session.id,
            'timestamp': datetime.now().isoformat(),
            'signal_source': 'grid_tracker',
            'require_price_recheck': True,
            'peak_price': 10.1,
            'callback_ratio': 0.005,
        }

    def _set_latest_price(self, price):
        self.position_manager.data_manager.get_latest_data.return_value = (
            {'lastPrice': price} if price is not None else None
        )


# ─────────────────────────── A. 对手价下单 ───────────────────────────
class TestGridCounterpartyPrice(_GridGuardTestBase):
    def test_buy_uses_counterparty_price_none(self):
        """实盘+确认模式+开关开: 买入下单 price=None(executor 取卖三价)"""
        self._set_latest_price(10.0)
        session = self._make_session()
        ok = self.manager.execute_grid_trade(self._buy_signal(session, trigger_price=10.0))
        self.assertTrue(ok)
        self.executor.buy_stock.assert_called_once()
        self.assertIsNone(self.executor.buy_stock.call_args.kwargs['price'])

    def test_sell_uses_counterparty_price_none(self):
        """实盘+确认模式+开关开: 卖出下单 price=None(executor 取买三价)"""
        self._set_latest_price(10.0)
        session = self._make_session()
        ok = self.manager.execute_grid_trade(self._sell_signal(session, trigger_price=10.0))
        self.assertTrue(ok)
        self.executor.sell_stock.assert_called_once()
        self.assertIsNone(self.executor.sell_stock.call_args.kwargs['price'])

    def test_buy_falls_back_to_trigger_when_switch_off(self):
        """开关关闭: 回退 trigger_price 限价"""
        config.GRID_USE_COUNTERPARTY_PRICE = False
        self._set_latest_price(10.0)
        session = self._make_session()
        ok = self.manager.execute_grid_trade(self._buy_signal(session, trigger_price=10.0))
        self.assertTrue(ok)
        self.assertEqual(self.executor.buy_stock.call_args.kwargs['price'], 10.0)

    def test_counterparty_disabled_when_not_confirm_mode(self):
        """非确认模式: 即使开关开启也回退 trigger_price(保持 V1 统计一致性)"""
        config.GRID_CONFIRM_LIVE_ORDER_BY_DEAL = False
        config.GRID_USE_COUNTERPARTY_PRICE = True
        self._set_latest_price(10.0)
        session = self._make_session()
        self.manager.execute_grid_trade(self._buy_signal(session, trigger_price=10.0))
        self.executor.buy_stock.assert_called_once()
        self.assertEqual(self.executor.buy_stock.call_args.kwargs['price'], 10.0)

    def test_simulation_mode_does_not_call_executor(self):
        """模拟模式: 不触达 executor 实盘下单"""
        config.ENABLE_SIMULATION_MODE = True
        self._set_latest_price(10.0)
        session = self._make_session()
        self.manager.execute_grid_trade(self._buy_signal(session, trigger_price=10.0))
        self.executor.buy_stock.assert_not_called()

    def test_counterparty_buy_reserves_by_risk_price_and_reduces_volume(self):
        """对手价买入按风险价预占，避免成交价高于触发价时突破资金上限。"""
        self._set_latest_price(10.0)
        session = self._make_session()
        session.max_investment = 2000
        session.position_ratio = 1.0

        ok = self.manager.execute_grid_trade(self._buy_signal(session, trigger_price=10.0))

        self.assertTrue(ok)
        self.executor.buy_stock.assert_called_once()
        self.assertIsNone(self.executor.buy_stock.call_args.kwargs['price'])
        self.assertEqual(self.executor.buy_stock.call_args.kwargs['volume'], 100)
        pending = self.manager.pending_grid_orders['ORDER_BUY']
        self.assertAlmostEqual(pending['reserved_price'], 10.2, places=4)
        self.assertAlmostEqual(self.manager._get_reserved_buy_amount_unlocked(session.id), 1020.0, places=2)

        self.executor.buy_stock.reset_mock()
        ok2 = self.manager.execute_grid_trade(self._buy_signal(session, trigger_price=10.0))
        self.assertFalse(ok2)
        self.executor.buy_stock.assert_not_called()


# ─────────────────────── B. 涨跌停/停牌防护(集成) ───────────────────────
class TestGridPriceLimitGuard(_GridGuardTestBase):
    def test_limit_up_blocks_buy(self):
        """涨停: 拦截买入，executor.buy_stock 不被调用"""
        self._set_latest_price(11.0)  # 现价=涨停价
        session = self._make_session()
        ok = self.manager.execute_grid_trade(self._buy_signal(session, trigger_price=11.0))
        self.assertFalse(ok)
        self.executor.buy_stock.assert_not_called()

    def test_limit_down_blocks_sell(self):
        """跌停: 拦截卖出，executor.sell_stock 不被调用"""
        self._set_latest_price(9.0)  # 现价=跌停价
        session = self._make_session()
        ok = self.manager.execute_grid_trade(self._sell_signal(session, trigger_price=9.0))
        self.assertFalse(ok)
        self.executor.sell_stock.assert_not_called()

    def test_bj_limit_up_blocks_buy_with_xtdata_limits(self):
        """北交所涨停防护使用 xtdata 明细价，不硬编码涨跌幅。"""
        self.position_manager.data_manager.xt.get_instrument_detail.return_value = {
            'UpStopPrice': 13.0, 'DownStopPrice': 7.0
        }
        self._set_latest_price(13.0)
        session = self._make_session(stock_code='920118.BJ')
        ok = self.manager.execute_grid_trade(self._buy_signal(session, trigger_price=13.0))
        self.assertFalse(ok)
        self.executor.buy_stock.assert_not_called()
        self.position_manager.data_manager.xt.get_instrument_detail.assert_called_with('920118.BJ')

    def test_bj_limit_down_blocks_sell_with_xtdata_limits(self):
        """北交所跌停防护使用 xtdata 明细价，不硬编码涨跌幅。"""
        self.position_manager.data_manager.xt.get_instrument_detail.return_value = {
            'UpStopPrice': 13.0, 'DownStopPrice': 7.0
        }
        self._set_latest_price(7.0)
        session = self._make_session(stock_code='920118.BJ')
        ok = self.manager.execute_grid_trade(self._sell_signal(session, trigger_price=7.0))
        self.assertFalse(ok)
        self.executor.sell_stock.assert_not_called()
        self.position_manager.data_manager.xt.get_instrument_detail.assert_called_with('920118.BJ')

    def test_limit_up_allows_sell(self):
        """涨停: 放行卖出(封板能卖高价)"""
        self._set_latest_price(11.0)
        session = self._make_session()
        ok = self.manager.execute_grid_trade(self._sell_signal(session, trigger_price=11.0))
        self.assertTrue(ok)
        self.executor.sell_stock.assert_called_once()

    def test_limit_down_allows_buy(self):
        """跌停: 放行买入(跌停方向不拦截买入)"""
        self._set_latest_price(9.0)
        session = self._make_session()
        ok = self.manager.execute_grid_trade(self._buy_signal(session, trigger_price=9.0))
        self.assertTrue(ok)
        self.executor.buy_stock.assert_called_once()

    def test_suspension_blocks_buy(self):
        """停牌/无现价: 拦截买入"""
        self._set_latest_price(None)
        session = self._make_session()
        ok = self.manager.execute_grid_trade(self._buy_signal(session, trigger_price=10.0))
        self.assertFalse(ok)
        self.executor.buy_stock.assert_not_called()

    def test_suspension_blocks_sell(self):
        """停牌/无现价: 拦截卖出"""
        self._set_latest_price(None)
        session = self._make_session()
        ok = self.manager.execute_grid_trade(self._sell_signal(session, trigger_price=10.0))
        self.assertFalse(ok)
        self.executor.sell_stock.assert_not_called()

    def test_fail_open_when_limits_unavailable(self):
        """涨跌停价获取失败: fail-open，正常买入"""
        self.position_manager.data_manager.xt.get_instrument_detail.return_value = None
        self._set_latest_price(10.0)
        session = self._make_session()
        ok = self.manager.execute_grid_trade(self._buy_signal(session, trigger_price=10.0))
        self.assertTrue(ok)
        self.executor.buy_stock.assert_called_once()

    def test_guard_disabled_skips_check(self):
        """守卫关闭: 涨停也不拦截买入"""
        config.GRID_ENABLE_PRICE_LIMIT_GUARD = False
        self._set_latest_price(11.0)
        session = self._make_session()
        ok = self.manager.execute_grid_trade(self._buy_signal(session, trigger_price=11.0))
        self.assertTrue(ok)
        self.executor.buy_stock.assert_called_once()

    def test_simulation_mode_skips_guard(self):
        """模拟模式: 不触发涨跌停守卫(涨停仍可模拟买入)"""
        config.ENABLE_SIMULATION_MODE = True
        self._set_latest_price(11.0)
        session = self._make_session()
        ok = self.manager.execute_grid_trade(self._buy_signal(session, trigger_price=11.0))
        self.assertTrue(ok)  # 模拟买入成功，未被守卫拦截


# ─────────────────── C. _check_tradable / _get_price_limits 单元测试 ───────────────────
class TestCheckTradableUnit(_GridGuardTestBase):
    def test_check_tradable_normal_price(self):
        ok, reason = self.manager._check_tradable('000001.SZ', 'BUY', 10.0)
        self.assertTrue(ok)
        self.assertEqual(reason, "")

    def test_check_tradable_none_price_blocks(self):
        ok, reason = self.manager._check_tradable('000001.SZ', 'BUY', None)
        self.assertFalse(ok)
        ok2, _ = self.manager._check_tradable('000001.SZ', 'SELL', 0)
        self.assertFalse(ok2)

    def test_check_tradable_limit_up_buy_blocked_sell_allowed(self):
        self.assertFalse(self.manager._check_tradable('000001.SZ', 'BUY', 11.0)[0])
        self.assertTrue(self.manager._check_tradable('000001.SZ', 'SELL', 11.0)[0])

    def test_check_tradable_limit_down_sell_blocked_buy_allowed(self):
        self.assertFalse(self.manager._check_tradable('000001.SZ', 'SELL', 9.0)[0])
        self.assertTrue(self.manager._check_tradable('000001.SZ', 'BUY', 9.0)[0])

    def test_get_price_limits_field_compat(self):
        """多字段名兼容: HighLimit/LowLimit"""
        self.position_manager.data_manager.xt.get_instrument_detail.return_value = {
            'HighLimit': 22.0, 'LowLimit': 18.0
        }
        up, down = self.manager._get_price_limits('000001.SZ')
        self.assertEqual(up, 22.0)
        self.assertEqual(down, 18.0)

    def test_get_price_limits_invalid_returns_none(self):
        self.position_manager.data_manager.xt.get_instrument_detail.return_value = "not-a-dict"
        self.assertEqual(self.manager._get_price_limits('000001.SZ'), (None, None))

    def test_get_price_limits_exception_returns_none(self):
        self.position_manager.data_manager.xt.get_instrument_detail.side_effect = RuntimeError("boom")
        self.assertEqual(self.manager._get_price_limits('000001.SZ'), (None, None))

    def test_get_price_limits_zero_values_treated_as_missing(self):
        """涨跌停价为 0(无效) 视为缺失"""
        self.position_manager.data_manager.xt.get_instrument_detail.return_value = {
            'UpStopPrice': 0, 'DownStopPrice': 0
        }
        self.assertEqual(self.manager._get_price_limits('000001.SZ'), (None, None))


if __name__ == '__main__':
    unittest.main(verbosity=2)
