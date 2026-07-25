"""
网格交易「固定股数」模式测试 (trade_mode='shares')

覆盖范围:
1. 固定股数模式买入: volume = fixed_volume (对齐100股), 不受 position_ratio 影响
2. 固定股数模式卖出: sell_volume = fixed_volume, 不超过可卖数量
3. 固定股数模式仍受 max_investment 硬上限兜底 (剩余额度不足则跳过买入)
4. fixed_volume 落库与恢复 (create_grid_session / dict(row))
"""

import sys
import os
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

import unittest
from unittest.mock import Mock
from datetime import datetime
from dataclasses import asdict

import config
from grid_trading_manager import GridSession, GridTradingManager, PriceTracker
from grid_database import DatabaseManager
from trading_executor import TradingExecutor
from position_manager import PositionManager


class TestGridTradeFixedShares(unittest.TestCase):
    """网格交易固定股数模式测试"""

    def setUp(self):
        self.db = DatabaseManager(":memory:")
        self.db.init_grid_tables()

        self.position_manager = Mock(spec=PositionManager)
        self.position_manager._increment_data_version = Mock()
        self.position_manager.data_manager = Mock()
        self.position_manager.data_manager.get_latest_data.return_value = {'lastPrice': 10.0}
        self.position_manager.get_position.return_value = None
        self.executor = Mock(spec=TradingExecutor)
        self.executor._save_trade_record.return_value = True

        self.manager = GridTradingManager(
            db_manager=self.db,
            position_manager=self.position_manager,
            trading_executor=self.executor
        )

        self.original_simulation_mode = config.ENABLE_SIMULATION_MODE
        config.ENABLE_SIMULATION_MODE = True

    def tearDown(self):
        config.ENABLE_SIMULATION_MODE = self.original_simulation_mode
        if hasattr(self, 'db') and self.db:
            self.db.close()

    def _create_session(self, fixed_volume, max_investment=100000, current_investment=0, position_ratio=0.25):
        session = GridSession(
            id=None,
            stock_code="000001.SZ",
            status="active",
            center_price=10.0,
            current_center_price=10.0,
            price_interval=0.05,
            position_ratio=position_ratio,
            callback_ratio=0.005,
            trade_mode="shares",
            fixed_volume=fixed_volume,
            max_investment=max_investment,
            current_investment=current_investment,
            start_time=datetime.now()
        )
        session.id = self.db.create_grid_session(asdict(session))
        self.manager.sessions["000001.SZ"] = session
        self.manager.trackers[session.id] = PriceTracker(session_id=session.id, last_price=9.5)
        return session

    def _mock_position(self, volume=1000, available=None):
        return {
            'stock_code': '000001.SZ',
            'volume': volume,
            'available': available if available is not None else volume,
            'cost_price': 10.0,
            'current_price': 10.5
        }

    def _buy_signal(self, price=9.5):
        return {'stock_code': '000001.SZ', 'signal_type': 'BUY', 'trigger_price': price,
                'grid_level': 'lower', 'valley_price': price - 0.1, 'callback_ratio': 0.005}

    def _sell_signal(self, price=10.5):
        return {'stock_code': '000001.SZ', 'signal_type': 'SELL', 'trigger_price': price,
                'grid_level': 'upper', 'peak_price': price + 0.1, 'callback_ratio': 0.005}

    def test_buy_uses_fixed_volume(self):
        """固定股数模式买入: volume = fixed_volume, 与 position_ratio 无关"""
        session = self._create_session(fixed_volume=300, position_ratio=0.90)
        result = self.manager._execute_grid_buy(session, self._buy_signal(price=9.5))
        self.assertTrue(result)
        # 固定股数=300, 与 position_ratio(0.90) 无关
        self.assertEqual(session.total_buy_volume, 300)
        self.assertAlmostEqual(session.current_investment, 300 * 9.5, places=2)

    def test_buy_fixed_volume_aligns_to_100(self):
        """固定股数非100倍数时向下对齐100"""
        session = self._create_session(fixed_volume=350)
        result = self.manager._execute_grid_buy(session, self._buy_signal(price=9.5))
        self.assertTrue(result)
        self.assertEqual(session.total_buy_volume, 300)  # 350 -> 300

    def test_buy_blocked_by_max_investment_cap(self):
        """固定股数模式仍受 max_investment 硬上限兜底: 剩余额度不足则跳过"""
        # fixed_volume=1000 股 × 9.5 = 9500, 剩余额度仅 2000 -> 应被硬上限拦截
        session = self._create_session(fixed_volume=1000, max_investment=10000, current_investment=8000)
        result = self.manager._execute_grid_buy(session, self._buy_signal(price=9.5))
        self.assertFalse(result, "超过剩余额度应被硬上限拦截")
        self.assertEqual(session.total_buy_volume, 0)

    def test_sell_uses_fixed_volume(self):
        """固定股数模式卖出: sell_volume = fixed_volume"""
        session = self._create_session(fixed_volume=300, current_investment=5000, position_ratio=0.90)
        self.position_manager.get_position.return_value = self._mock_position(volume=1000)
        result = self.manager._execute_grid_sell(session, self._sell_signal(price=10.5))
        self.assertTrue(result)
        self.assertEqual(session.total_sell_volume, 300)

    def test_sell_fixed_volume_capped_by_available(self):
        """固定股数超过可卖数量时裁剪到可卖上限(T+1)"""
        session = self._create_session(fixed_volume=1000, current_investment=5000)
        # 可卖仅 250 股 -> 裁剪为 200 (对齐100)
        self.position_manager.get_position.return_value = self._mock_position(volume=1000, available=250)
        result = self.manager._execute_grid_sell(session, self._sell_signal(price=10.5))
        self.assertTrue(result)
        self.assertEqual(session.total_sell_volume, 200)

    def test_fixed_volume_persisted_and_reloaded(self):
        """fixed_volume / trade_mode 落库并可从 dict(row) 读回"""
        self._create_session(fixed_volume=400)
        row = self.db.get_grid_session_by_stock("000001.SZ")
        self.assertIsNotNone(row)
        self.assertEqual(row['trade_mode'], 'shares')
        self.assertEqual(row['fixed_volume'], 400)


if __name__ == '__main__':
    unittest.main()
