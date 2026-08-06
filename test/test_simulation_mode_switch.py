#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
L4 — 模拟/实盘模式切换与配置测试

覆盖：
    - POST /api/config/save 的 simulationMode 运行时切换
      （重建内存库、清理/初始化 qmt_trader、不持久化）
    - SIMULATION_BALANCE 的用例间隔离（夹具自检）
    - 模拟模式下 get_account_info 的资金口径与账号身份表达

⚠️ 全程用 Flask test_client 打独立进程内的 app，
   绝不对运行中的 5000/5001 实例发请求 —— 切模拟会丢弃真实 qmt_trader。
"""

import os
import sys
import unittest
from unittest.mock import MagicMock, patch

PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, PROJECT_ROOT)

os.environ.setdefault("MINIQMT_DISABLE_DOTENV", "1")

# ---------------------------------------------------------------------------
# import web_server 之前临时替换迅投库，import 完成后立刻还原。
# 不能拖到 tearDownModule —— 回归运行器会先 __import__ 全部测试模块再跑用例，
# 期间残留的 MagicMock 会让其他模块 patch 到错误对象上（跨模块串扰）。
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
finally:
    for _name in _MOCKED_MODULE_NAMES:
        if _name in _orig_sys_modules:
            sys.modules[_name] = _orig_sys_modules[_name]
        else:
            sys.modules.pop(_name, None)


class ModeSwitchTestBase(unittest.TestCase):

    @classmethod
    def setUpClass(cls):
        cls._orig_token = config.WEB_API_TOKEN
        config.WEB_API_TOKEN = ''
        web_server.app.config['TESTING'] = True

    @classmethod
    def tearDownClass(cls):
        config.WEB_API_TOKEN = cls._orig_token

    def setUp(self):
        self._orig = {
            'balance': config.SIMULATION_BALANCE,
            'sim_mode': config.ENABLE_SIMULATION_MODE,
        }
        config.SIMULATION_BALANCE = 100000.0
        config.ENABLE_SIMULATION_MODE = True

        self.pm = PositionManager()
        self.pm.stop_sync_thread()

        mock_dm = MagicMock()
        mock_dm.conn = self.pm.data_manager.conn
        mock_dm.get_stock_name.return_value = '测试股票'
        mock_dm.get_latest_data.return_value = {'lastPrice': 10.0}
        mock_dm.ensure_subscribed = MagicMock()
        self.pm.data_manager = mock_dm

        web_server.set_position_manager(self.pm)
        self._clear_positions()
        self.client = web_server.app.test_client()

    def tearDown(self):
        web_server.set_position_manager(None)
        try:
            self.pm.stop_sync_thread()
        except Exception:
            pass
        config.SIMULATION_BALANCE = self._orig['balance']
        config.ENABLE_SIMULATION_MODE = self._orig['sim_mode']

    def _clear_positions(self):
        with self.pm.memory_conn_lock:
            self.pm.memory_conn.execute("DELETE FROM positions")
            self.pm.memory_conn.commit()

    def _save_config(self, payload):
        return self.client.post('/api/config/save', json=payload)


class TestModeSwitch(ModeSwitchTestBase):
    """L4-01 ~ L4-04: simulationMode 运行时切换"""

    def test_L4_01_simulation_to_live_rebuilds_memory_db(self):
        """L4-01 模拟→实盘：重建内存库并异步发起 QMT 连接"""
        old_conn_id = id(self.pm.memory_conn)

        with patch.object(self.pm, 'start_qmt_connect_async') as mock_connect, \
             patch('web_server.config_manager') as mock_cm:
            mock_cm.save_batch_configs.return_value = (0, 0)
            resp = self._save_config({'simulationMode': False})

        self.assertEqual(resp.status_code, 200)
        self.assertFalse(config.ENABLE_SIMULATION_MODE)
        self.assertNotEqual(id(self.pm.memory_conn), old_conn_id,
                            "切换模式应重建内存数据库连接")
        mock_connect.assert_called_once()

    def test_L4_02_live_to_simulation_clears_qmt_trader(self):
        """L4-02 实盘→模拟：清理 qmt_trader，标记未连接"""
        config.ENABLE_SIMULATION_MODE = False
        self.pm.qmt_trader = MagicMock()
        self.pm.qmt_connected = True

        with patch('web_server.config_manager') as mock_cm:
            mock_cm.save_batch_configs.return_value = (0, 0)
            resp = self._save_config({'simulationMode': True})

        self.assertEqual(resp.status_code, 200)
        self.assertTrue(config.ENABLE_SIMULATION_MODE)
        self.assertIsNone(self.pm.qmt_trader, "切模拟应释放实盘交易接口")
        self.assertFalse(self.pm.qmt_connected)

    def test_L4_03_same_value_does_not_rebuild(self):
        """L4-03 值未变化时短路，不重建内存库"""
        old_conn_id = id(self.pm.memory_conn)

        with patch.object(self.pm, 'start_qmt_connect_async') as mock_connect, \
             patch('web_server.config_manager') as mock_cm:
            mock_cm.save_batch_configs.return_value = (0, 0)
            resp = self._save_config({'simulationMode': True})   # 当前已是 True

        self.assertEqual(resp.status_code, 200)
        self.assertEqual(id(self.pm.memory_conn), old_conn_id,
                         "同值切换不应重建连接")
        mock_connect.assert_not_called()

    def test_L4_04_simulation_mode_not_persisted(self):
        """L4-04 simulationMode 只运行时生效，不写入持久化配置"""
        with patch.object(self.pm, 'start_qmt_connect_async'), \
             patch('web_server.config_manager') as mock_cm:
            mock_cm.save_batch_configs.return_value = (0, 0)
            self._save_config({'simulationMode': False})

        mock_cm.save_batch_configs.assert_called_once()
        db_configs = mock_cm.save_batch_configs.call_args[0][0]
        for forbidden in ('simulationMode', 'ENABLE_SIMULATION_MODE'):
            self.assertNotIn(forbidden, db_configs,
                             f"{forbidden} 不应被持久化")


class TestSimulationBalanceIsolation(ModeSwitchTestBase):
    """L4-05: 夹具自检 —— 证明 SIMULATION_BALANCE 逐用例隔离生效

    两个用例按方法名字典序执行：a 先消耗资金，b 断言起点已复位。
    若隔离夹具被误删，b 会失败。
    """

    def test_L4_05a_consume_balance(self):
        """L4-05a 消耗资金（不手工复位，交给 tearDown）"""
        self.assertAlmostEqual(config.SIMULATION_BALANCE, 100000.0, places=2,
                               msg="用例起点应为 100000")
        ok = self.pm.simulate_buy_position('000001.SZ', 1000, 10.0)
        self.assertTrue(ok)
        self.assertLess(config.SIMULATION_BALANCE, 100000.0,
                        "买入后余额应减少")

    def test_L4_05b_balance_restored_for_next_case(self):
        """L4-05b 上一用例的资金变动不应泄漏到本用例"""
        self.assertAlmostEqual(config.SIMULATION_BALANCE, 100000.0, places=2,
                               msg="夹具失效：余额被上一个用例污染")


class TestSimulationAccountInfo(ModeSwitchTestBase):
    """L4-06 ~ L4-09: 模拟模式账户口径"""

    def test_L4_06_available_equals_simulation_balance(self):
        """L4-06 available 取自 SIMULATION_BALANCE（非硬编码）"""
        self.pm.simulate_buy_position('000001.SZ', 1000, 10.0)

        info = self.pm.get_account_info()
        self.assertIsNotNone(info)
        self.assertAlmostEqual(info['available'], config.SIMULATION_BALANCE,
                               places=2)
        self.assertNotAlmostEqual(info['available'], 100000.0, places=2,
                                  msg="买入后 available 应已扣减，不应是初始值")

    def test_L4_07_total_asset_is_available_plus_market_value(self):
        """L4-07 total_asset = available + 持仓市值"""
        self.pm.simulate_buy_position('000001.SZ', 1000, 10.0)
        self.pm.simulate_buy_position('600036.SH', 500, 20.0)

        info = self.pm.get_account_info()
        self.assertAlmostEqual(
            info['total_asset'], info['available'] + info['market_value'],
            places=2, msg="总资产口径应为可用资金 + 持仓市值")
        # 两笔持仓市值：1000*10 + 500*20 = 20000
        self.assertAlmostEqual(info['market_value'], 20000.0, places=2)

    def test_L4_08_account_id_is_real_not_placeholder(self):
        """L4-08 模拟模式仍返回真实 account_id，不返回 'SIMULATION'"""
        info = self.pm.get_account_info()

        expected = config.ACCOUNT_CONFIG.get('account_id')
        self.assertNotEqual(info['account_id'], 'SIMULATION',
                            "多账号场景需要真实 ID 才能区分 Web 窗口")
        if expected:
            self.assertEqual(info['account_id'], expected)

    def test_L4_09_status_api_reports_simulation_mode(self):
        """L4-09 /api/status 由 settings.simulationMode 表达模拟身份"""
        resp = self.client.get('/api/status')
        self.assertEqual(resp.status_code, 200)

        data = resp.get_json()
        self.assertTrue(data['settings']['simulationMode'],
                        "模拟身份应由 settings.simulationMode 表达")


if __name__ == '__main__':
    unittest.main(verbosity=2)
