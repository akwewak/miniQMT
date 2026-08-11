#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
L2 — Web API 模拟买入端到端测试

打通 POST /api/actions/execute_buy 的完整链路，不 mock 中间层：

    web_server.execute_buy
      → Methods.add_xt_suffix          代码后缀格式化（模拟模式加后缀）
      → trading_strategy.manual_buy    ENABLE_ALLOW_BUY 门控 + M_simu 策略标识
      → trading_executor.buy_stock     模拟旁路（跳过 qmt_trader / 无视交易时间）
      → position_manager.simulate_buy_position

隔离：import web_server 前把 xtquant 系模块塞成 MagicMock；
只写 data/trading_test.db 与 :memory:，不发真实 HTTP 到 5000/5001/8888。
"""

import os
import sys
import sqlite3
import unittest
from unittest.mock import MagicMock, patch

PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, PROJECT_ROOT)

os.environ.setdefault("MINIQMT_DISABLE_DOTENV", "1")

# ---------------------------------------------------------------------------
# import web_server 之前临时把迅投库替换成 MagicMock，避免首次导入时
# 触碰真实行情/交易服务；import 完成后立刻还原。
#
# ⚠️ 必须在模块顶层就还原，不能拖到 tearDownModule：
# run_integration_regression_tests.py 会先 __import__ 全部测试模块、
# 之后才开始跑用例。若在此期间把 sys.modules['easy_qmt_trader'] 留成
# MagicMock，其他模块（如 test_trader_callback 的
# `patch("easy_qmt_trader.XtQuantTrader")`）就会 patch 到 Mock 上，
# 导致跨模块串扰。
# ---------------------------------------------------------------------------
_MOCKED_MODULE_NAMES = [
    'xtquant', 'xtquant.xtdata', 'xtquant.xttrader', 'xtquant.xttype',
    'easy_qmt_trader',
]
_orig_sys_modules = {k: sys.modules[k] for k in _MOCKED_MODULE_NAMES
                     if k in sys.modules}
for _mod in _MOCKED_MODULE_NAMES:
    sys.modules[_mod] = MagicMock()

try:
    import config

    config.ENABLE_SIMULATION_MODE = True
    config.DB_PATH = "data/trading_test.db"

    import web_server
    from position_manager import PositionManager
    from trading_executor import TradingExecutor
    from strategy import TradingStrategy
finally:
    for _name in _MOCKED_MODULE_NAMES:
        if _name in _orig_sys_modules:
            sys.modules[_name] = _orig_sys_modules[_name]
        else:
            sys.modules.pop(_name, None)

BUY_FEE_RATE = 0.0003


class TestWebExecuteBuySimulation(unittest.TestCase):
    """L2-01 ~ L2-10"""

    @classmethod
    def setUpClass(cls):
        cls._orig_db_path = config.DB_PATH
        cls._orig_token = config.WEB_API_TOKEN
        # 关闭 token 校验，本用例聚焦买入链路而非鉴权
        config.WEB_API_TOKEN = ''
        web_server.app.config['TESTING'] = True

    @classmethod
    def tearDownClass(cls):
        config.DB_PATH = cls._orig_db_path
        config.WEB_API_TOKEN = cls._orig_token

    def setUp(self):
        self._orig = {
            'balance': config.SIMULATION_BALANCE,
            'sim_mode': config.ENABLE_SIMULATION_MODE,
            'allow_buy': config.ENABLE_ALLOW_BUY,
            'position_unit': config.POSITION_UNIT,
        }
        config.SIMULATION_BALANCE = 100000.0
        config.ENABLE_SIMULATION_MODE = True
        config.ENABLE_ALLOW_BUY = True
        config.POSITION_UNIT = 35000

        # 真实三件套串联，只把 data_manager 换成 Mock
        self.pm = PositionManager()
        self.pm.stop_sync_thread()

        mock_dm = MagicMock()
        mock_dm.conn = self.pm.data_manager.conn
        mock_dm.get_stock_name.return_value = '测试股票'
        mock_dm.get_latest_data.return_value = {'lastPrice': 10.0, 'lastClose': 9.8}
        mock_dm.ensure_subscribed = MagicMock()
        self.pm.data_manager = mock_dm
        self.mock_dm = mock_dm

        self.executor = TradingExecutor()
        self.executor.position_manager = self.pm
        self.executor.data_manager = mock_dm

        with patch('strategy.get_data_manager', return_value=mock_dm), \
             patch('strategy.get_indicator_calculator', return_value=MagicMock()), \
             patch('strategy.get_position_manager', return_value=self.pm), \
             patch('strategy.get_trading_executor', return_value=self.executor):
            self.strategy = TradingStrategy()

        # 注入到 web_server（trading_strategy 是模块级全局，execute_buy 直接引用）
        self._orig_ws_strategy = web_server.trading_strategy
        web_server.trading_strategy = self.strategy
        web_server.set_position_manager(self.pm)

        self._clear_tables()
        self.client = web_server.app.test_client()

    def tearDown(self):
        web_server.trading_strategy = self._orig_ws_strategy
        web_server.set_position_manager(None)
        try:
            self.pm.stop_sync_thread()
        except Exception:
            pass
        config.SIMULATION_BALANCE = self._orig['balance']
        config.ENABLE_SIMULATION_MODE = self._orig['sim_mode']
        config.ENABLE_ALLOW_BUY = self._orig['allow_buy']
        config.POSITION_UNIT = self._orig['position_unit']

    # ---------- 工具 ----------

    def _clear_tables(self):
        with self.pm.memory_conn_lock:
            self.pm.memory_conn.execute("DELETE FROM positions")
            self.pm.memory_conn.commit()
        cur = self.pm.conn.cursor()
        cur.execute("DELETE FROM trade_records")
        self.pm.conn.commit()

    def _buy(self, stocks, quantity=1, strategy='custom_stock'):
        return self.client.post('/api/actions/execute_buy', json={
            'strategy': strategy, 'quantity': quantity, 'stocks': stocks,
        })

    def _memory_codes(self):
        with self.pm.memory_conn_lock:
            cur = self.pm.memory_conn.cursor()
            cur.execute("SELECT stock_code FROM positions")
            return [r[0] for r in cur.fetchall()]

    def _position(self, stock_code):
        with self.pm.memory_conn_lock:
            cur = self.pm.memory_conn.cursor()
            cur.execute("SELECT * FROM positions WHERE stock_code=?", (stock_code,))
            row = cur.fetchone()
            if row is None:
                return None
            cols = [d[0] for d in cur.description]
        return dict(zip(cols, row))

    # ---------- 用例 ----------

    def test_L2_01_full_chain_creates_position(self):
        """L2-01 全链路走通：HTTP 请求 → 内存持仓落地"""
        resp = self._buy(['000001.SZ'])
        self.assertEqual(resp.status_code, 200)

        data = resp.get_json()
        self.assertEqual(data['status'], 'success')
        self.assertEqual(data['success_count'], 1)

        pos = self._position('000001.SZ')
        self.assertIsNotNone(pos, "持仓应落地到内存库")
        volume = int(float(pos['volume']))
        self.assertGreater(volume, 0)
        self.assertEqual(volume % 100, 0, "买入数量应为 100 的整数倍")

    def test_L2_02_code_suffix_added_in_simulation(self):
        """L2-02 模拟模式下无后缀代码经 add_xt_suffix 补全"""
        resp = self._buy(['000001'])
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(resp.get_json()['success_count'], 1)

        codes = self._memory_codes()
        self.assertIn('000001.SZ', codes,
                      f"模拟模式应补全市场后缀，实际落地: {codes}")

    def test_L2_03_random_pool_samples_quantity(self):
        """L2-03 random_pool 策略按 quantity 抽样"""
        pool = ['000001.SZ', '000002.SZ', '600036.SH', '600000.SH', '000333.SZ']
        with patch('random.sample', return_value=['000001.SZ', '600036.SH']) as m:
            resp = self._buy(pool, quantity=2, strategy='random_pool')

        self.assertEqual(resp.status_code, 200)
        data = resp.get_json()
        self.assertEqual(data['total_count'], 2)
        self.assertEqual(data['success_count'], 2)
        m.assert_called_once()
        self.assertEqual(m.call_args[0][1], 2, "抽样数量应等于 quantity")

        codes = set(self._memory_codes())
        self.assertEqual(codes, {'000001.SZ', '600036.SH'})

    def test_L2_04_custom_stock_takes_prefix_slice(self):
        """L2-04 custom_stock 策略按顺序取前 quantity 只"""
        pool = ['000001.SZ', '000002.SZ', '600036.SH', '600000.SH']
        resp = self._buy(pool, quantity=2, strategy='custom_stock')

        self.assertEqual(resp.status_code, 200)
        self.assertEqual(resp.get_json()['success_count'], 2)
        self.assertEqual(set(self._memory_codes()), {'000001.SZ', '000002.SZ'})

    def test_L2_05_strategy_tag_is_m_simu(self):
        """L2-05 模拟模式下交易记录 strategy 标识为 M_simu"""
        self._buy(['000001.SZ'])

        cur = self.pm.conn.cursor()
        cur.execute("SELECT strategy FROM trade_records WHERE stock_code='000001.SZ'")
        row = cur.fetchone()
        self.assertIsNotNone(row, "应写入交易记录")
        self.assertEqual(row[0], 'M_simu',
                         "manual_buy 在模拟模式应打 M_simu 标识")

    def test_L2_06_allow_buy_disabled_blocks(self):
        """L2-06 ENABLE_ALLOW_BUY=False 时 manual_buy 层拦截"""
        config.ENABLE_ALLOW_BUY = False
        balance_before = config.SIMULATION_BALANCE

        resp = self._buy(['000001.SZ'])

        self.assertEqual(resp.status_code, 200)
        self.assertEqual(resp.get_json()['success_count'], 0, "应全部失败")
        self.assertEqual(self._memory_codes(), [], "不应建仓")
        self.assertAlmostEqual(config.SIMULATION_BALANCE, balance_before, places=6,
                               msg="被拦截时资金不应变动")

    def test_L2_07_ignores_trade_time_in_simulation(self):
        """L2-07 模拟模式强制允许交易，无视 is_trade_time"""
        with patch.object(config, 'is_trade_time', return_value=False):
            resp = self._buy(['000001.SZ'])

        self.assertEqual(resp.status_code, 200)
        self.assertEqual(resp.get_json()['success_count'], 1,
                         "模拟模式应绕过交易时间检查")
        self.assertIsNotNone(self._position('000001.SZ'))

    def test_L2_07b_zero_ask_price_falls_back_to_latest_quote(self):
        """L2-07b xtdata 卖盘价为 0 时应降级使用最新行情"""
        with patch('xtquant.xtdata.get_full_tick', return_value={
            '000001.SZ': {'askPrice': [0, 0, 0]}
        }):
            resp = self._buy(['000001.SZ'])

        self.assertEqual(resp.status_code, 200)
        self.assertEqual(resp.get_json()['success_count'], 1)
        pos = self._position('000001.SZ')
        self.assertIsNotNone(pos, "卖盘价无效时仍应使用最新行情完成模拟建仓")
        self.assertAlmostEqual(float(pos['cost_price']), 10.0, places=2)

    def test_L2_08_zero_quantity_rejected(self):
        """L2-08 quantity<=0 返回 400（回归）"""
        resp = self._buy(['000001.SZ'], quantity=0)
        self.assertEqual(resp.status_code, 400)
        self.assertEqual(resp.get_json()['status'], 'error')

    def test_L2_09_empty_stocks_rejected(self):
        """L2-09 空股票列表返回 400（回归）"""
        resp = self._buy([], quantity=1)
        self.assertEqual(resp.status_code, 400)
        self.assertEqual(resp.get_json()['status'], 'error')

    def test_L2_10_repeat_buy_weights_cost_price(self):
        """L2-10 跨请求重复买入同股票走加权平均成本

        不假设成交价来源：buy_stock 内部是 `from xtquant import xtdata`
        （函数内 import，运行时从 sys.modules 解析），批量运行时可能被
        其他测试模块的 tearDownModule 还原成真实 xtquant。
        因此这里从实际写入的 trade_records 反推期望值，
        只校验"加权平均"这一逻辑本身。
        """
        self._buy(['000001.SZ'])
        v1 = int(float(self._position('000001.SZ')['volume']))

        self._buy(['000001.SZ'])
        second = self._position('000001.SZ')
        v2 = int(float(second['volume']))

        self.assertGreater(v2, v1, "二次买入应加仓")

        cur = self.pm.conn.cursor()
        cur.execute("SELECT price, volume FROM trade_records "
                    "WHERE stock_code='000001.SZ' AND trade_type='BUY' "
                    "ORDER BY id")
        trades = cur.fetchall()
        self.assertEqual(len(trades), 2, "应有两笔买入流水")

        total_amount = sum(float(p) * int(v) for p, v in trades)
        total_volume = sum(int(v) for _, v in trades)
        self.assertEqual(total_volume, v2, "持仓量应等于两笔买入之和")

        expected = round(total_amount / total_volume, 2)
        self.assertAlmostEqual(float(second['cost_price']), expected, places=2,
                               msg="Web 层重复买入应落到加权平均成本")


if __name__ == '__main__':
    unittest.main(verbosity=2)
