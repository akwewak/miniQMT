"""
持仓清零清理持久化状态专项测试
===================
覆盖 2026-08-18 实盘 bug：QMT 清仓后仍返回 volume=0 残留行，
_sync_real_positions_to_memory 走更新分支导致 profit_triggered/highest_price/
open_date 等旧状态残留，清仓后再买入继承旧仓状态（新仓永不首次止盈、
动态止盈位按旧高点误算可能触发全仓误卖）。

修复：持仓数量从有到无的转变=清仓事件，直接删除内存+SQLite 记录
（_delete_position_direct，不经 get_position 防无限递归），再买入时
走新增分支全新初始化；本地无记录的 volume=0 残留行跳过插入。

用例清单：
T1 - 清仓删除：内存 volume>0 + QMT volume=0 → 内存+SQLite 记录删除
T2 - 再买入新仓语义：T1 后 QMT volume>0 → 新增分支，不继承旧止盈状态
T3 - 残留行不重建：删除后 QMT 持续返回 volume=0 行 → 不重建记录
T4 - 部分卖出不触发：volume 1000→900 → 记录保留且止盈状态继承不变
T5 - 卖出在途不误删：volume 不变 available=0（冻结）→ 不删除
T6 - 删除后重启恢复：SQLite 无残留，_sync_db_to_memory 后内存无该股
T7 - 删除路径不经 get_position：防 remove_position 式无限递归回归
T8 - SQLite 即时删除失败由 15 秒同步线程（P6 路径）兜底清除
T9 - QMT 残留行余额为 NaN/None：清洗为 0 后跳过，不重建不异常
"""

import unittest
import sqlite3
import gc
import os
import sys
import time
import threading
from datetime import datetime, date
from unittest.mock import patch, MagicMock
import pandas as pd

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

try:
    import mootdx.quotes  # noqa: F401
except ModuleNotFoundError:
    mock_mootdx = MagicMock()
    mock_mootdx_quotes = MagicMock()
    mock_mootdx_quotes.Quotes.factory.return_value = MagicMock()
    sys.modules.setdefault('mootdx', mock_mootdx)
    sys.modules.setdefault('mootdx.quotes', mock_mootdx_quotes)

import config
from logger import get_logger

logger = get_logger("test_position_clear_reset")

# --------------------------------------------------------------------------
# 辅助：创建符合 position_manager.py Schema 的内存表
# --------------------------------------------------------------------------
_CREATE_POSITIONS_SQL = """
    CREATE TABLE IF NOT EXISTS positions (
        stock_code TEXT PRIMARY KEY,
        stock_name TEXT,
        volume REAL,
        available REAL,
        cost_price REAL,
        base_cost_price REAL,
        current_price REAL,
        market_value REAL,
        profit_ratio REAL,
        last_update TIMESTAMP,
        open_date TIMESTAMP,
        profit_triggered BOOLEAN DEFAULT FALSE,
        highest_price REAL,
        stop_loss_price REAL,
        profit_breakout_triggered BOOLEAN DEFAULT FALSE,
        breakout_highest_price REAL
    )
"""


def _make_memory_conn():
    conn = sqlite3.connect(":memory:", check_same_thread=False)
    conn.row_factory = sqlite3.Row
    conn.execute(_CREATE_POSITIONS_SQL)
    conn.commit()
    return conn


def _insert_memory_position(conn, stock_code, volume, available, cost_price=10.0,
                            profit_triggered=False, highest_price=None, stop_loss_price=None,
                            base_cost_price=None, profit_breakout_triggered=False,
                            breakout_highest_price=None):
    """向内存表插入测试持仓行（含旧仓残留止盈状态）"""
    now = datetime.now().strftime('%Y-%m-%d %H:%M:%S')
    conn.execute("""
        INSERT OR REPLACE INTO positions
            (stock_code, stock_name, volume, available, cost_price, base_cost_price,
             current_price, market_value, profit_ratio, last_update, open_date,
             profit_triggered, highest_price, stop_loss_price,
             profit_breakout_triggered, breakout_highest_price)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
    """, (
        stock_code, stock_code, volume, available, cost_price,
        base_cost_price or cost_price,
        cost_price, volume * cost_price, 0.0,
        now, now,
        profit_triggered,
        highest_price or cost_price,
        stop_loss_price or cost_price * 0.93,
        profit_breakout_triggered,
        breakout_highest_price or cost_price,
    ))
    conn.commit()


def _insert_sqlite_legacy_position(path, stock_code, volume, cost_price=10.0,
                                   profit_triggered=True, highest_price=50.0):
    """向测试 SQLite 文件插入带旧仓止盈状态的记录（模拟残留脏数据）"""
    now = datetime.now().strftime('%Y-%m-%d %H:%M:%S')
    conn = sqlite3.connect(path, check_same_thread=False)
    conn.execute(_CREATE_POSITIONS_SQL)
    conn.execute("""
        INSERT OR REPLACE INTO positions
            (stock_code, stock_name, volume, available, cost_price, base_cost_price,
             open_date, profit_triggered, highest_price, stop_loss_price,
             profit_breakout_triggered, breakout_highest_price, last_update)
        VALUES (?, ?, ?, 0, ?, ?, ?, ?, ?, ?, ?, ?, ?)
    """, (stock_code, stock_code, volume, cost_price, cost_price,
          "2026-08-10 10:53:11", profit_triggered, highest_price, 46.5,
          True, 47.61, now))
    conn.commit()
    conn.close()


def _remove_sqlite_file(path, retries=20, delay=0.1):
    """删除测试 SQLite 文件；Windows 下短暂等待连接句柄释放。"""
    last_error = None
    suffixes = ("", "-wal", "-shm", "-journal")

    for attempt in range(retries):
        blocked = False
        for suffix in suffixes:
            target = f"{path}{suffix}"
            if not os.path.exists(target):
                continue
            try:
                os.remove(target)
            except FileNotFoundError:
                continue
            except PermissionError as exc:
                blocked = True
                last_error = exc

        if not blocked:
            return

        gc.collect()
        if attempt < retries - 1:
            time.sleep(delay)

    if last_error is not None:
        raise last_error


def _real_df(stock_code, volume, available=None, cost_price=10.0, market_value=None):
    """构造 QMT 实盘持仓单行 DataFrame（带证券名称，避免 update_position
    内部经 get_data_manager 触发真实 QMT/xtdata 初始化）"""
    return pd.DataFrame([{
        '证券代码': stock_code,
        '证券名称': stock_code,
        '股票余额': volume,
        '可用余额': available if available is not None else volume,
        '成本价': cost_price,
        '市值': market_value if market_value is not None else (volume or 0) * cost_price,
    }])


class TestPositionClearReset(unittest.TestCase):
    """持仓清零删除记录 + 残留行防重建的行为验证"""

    TEST_DB = "data/test_position_clear_reset.db"

    @classmethod
    def setUpClass(cls):
        os.makedirs("data", exist_ok=True)
        # 测试使用独立 DB，与生产隔离（_delete_position_direct 的 SQLite
        # 即时删除经 config.DB_PATH 连接）
        cls._orig_db_path = config.DB_PATH
        config.DB_PATH = cls.TEST_DB

    @classmethod
    def tearDownClass(cls):
        config.DB_PATH = cls._orig_db_path
        try:
            _remove_sqlite_file(cls.TEST_DB)
        except Exception:
            pass

    def setUp(self):
        _remove_sqlite_file(self.TEST_DB)
        self.memory_conn = _make_memory_conn()

    def tearDown(self):
        self.memory_conn.close()
        _remove_sqlite_file(self.TEST_DB)

    # ------------------------------------------------------------------
    # 桩对象构造
    # ------------------------------------------------------------------
    def _make_sync_pm(self, last_price=10.5, conn=None):
        """
        构造可运行 _sync_real_positions_to_memory 的最小 PositionManager 桩。
        属性集合参考 test_dual_layer_storage.B2/B3 已验证的桩。
        """
        from position_manager import PositionManager

        pm = object.__new__(PositionManager)
        pm.memory_conn = self.memory_conn
        pm.memory_conn_lock = threading.Lock()
        pm.conn = conn  # _sync_db_to_memory 读取的 SQLite 连接（T6 使用）
        pm.sync_lock = threading.Lock()
        pm.signal_lock = threading.Lock()
        pm.version_lock = threading.Lock()
        pm._deleting_stocks = set()
        pm.data_version = 0
        pm.data_changed = False
        pm.latest_signals = {}
        pm.pending_orders = {}
        pm.data_manager = MagicMock()
        pm.data_manager.get_latest_data.return_value = {'lastPrice': last_price}
        pm._update_stock_positions_file = MagicMock()
        return pm

    def _sqlite_row(self, stock_code, columns="volume"):
        conn = sqlite3.connect(self.TEST_DB)
        try:
            row = conn.execute(
                f"SELECT {columns} FROM positions WHERE stock_code=?",
                (stock_code,)).fetchone()
            return row
        finally:
            conn.close()

    def _sync_real(self, pm, df):
        from position_manager import PositionManager
        with patch.object(config, 'ENABLE_SIMULATION_MODE', False):
            PositionManager._sync_real_positions_to_memory(pm, df)

    # ------------------------------------------------------------------
    # T1: 清仓删除 — 内存 volume>0 且 QMT 返回 volume=0 → 内存+SQLite 双删
    # ------------------------------------------------------------------
    def test_T1_clear_position_deletes_memory_and_sqlite(self):
        _insert_memory_position(self.memory_conn, "301218.SZ", volume=100, available=100,
                                cost_price=43.01, profit_triggered=True,
                                highest_price=50.0, stop_loss_price=45.0)
        _insert_sqlite_legacy_position(self.TEST_DB, "301218.SZ", volume=100,
                                       cost_price=43.01)

        pm = self._make_sync_pm()
        self._sync_real(pm, _real_df("301218.SZ", volume=0))

        mem_row = self.memory_conn.execute(
            "SELECT volume FROM positions WHERE stock_code=?", ("301218.SZ",)).fetchone()
        self.assertIsNone(mem_row, "清仓后内存记录应已删除")

        self.assertIsNone(self._sqlite_row("301218.SZ"),
                          "清仓后 SQLite 记录应已即时删除（防重启恢复脏状态）")

    # ------------------------------------------------------------------
    # T2: 清仓再买入按新仓语义初始化（2026-08-18 实盘场景复现）
    # ------------------------------------------------------------------
    def test_T2_rebuy_after_clear_initializes_as_new_position(self):
        _insert_memory_position(self.memory_conn, "301218.SZ", volume=100, available=100,
                                cost_price=43.01, profit_triggered=True,
                                highest_price=50.0, stop_loss_price=45.0)
        _insert_sqlite_legacy_position(self.TEST_DB, "301218.SZ", volume=100,
                                       cost_price=43.01)

        pm = self._make_sync_pm(last_price=46.3)
        # 清仓
        self._sync_real(pm, _real_df("301218.SZ", volume=0))
        # 再买入 1000 股
        self._sync_real(pm, _real_df("301218.SZ", volume=1000, cost_price=46.3))

        row = self.memory_conn.execute(
            "SELECT profit_triggered, highest_price, open_date FROM positions "
            "WHERE stock_code=?", ("301218.SZ",)).fetchone()
        self.assertIsNotNone(row, "再买入后应有新仓记录")
        self.assertFalse(bool(row[0]),
                         f"新仓 profit_triggered 应为 False，实际 {row[0]}（旧仓状态不得继承）")
        self.assertLess(abs(float(row[1]) - 46.3), 0.01,
                        f"新仓 highest_price 应从当前价 {46.3} 起步，实际 {row[1]}（不得继承旧高点 50.0）")
        open_date = datetime.strptime(row[2], '%Y-%m-%d %H:%M:%S').date()
        self.assertEqual(open_date, date.today(),
                         f"新仓 open_date 应为当前日期，实际 {row[2]}（不得继承旧仓 2026-08-10）")

    # ------------------------------------------------------------------
    # T3: QMT 持续返回 volume=0 残留行 → 不重建脏记录
    # ------------------------------------------------------------------
    def test_T3_residual_zero_volume_row_not_recreated(self):
        _insert_memory_position(self.memory_conn, "301218.SZ", volume=100, available=100,
                                cost_price=43.01, profit_triggered=True, highest_price=50.0)
        _insert_sqlite_legacy_position(self.TEST_DB, "301218.SZ", volume=100, cost_price=43.01)

        pm = self._make_sync_pm()
        # 首轮：清仓删除
        self._sync_real(pm, _real_df("301218.SZ", volume=0))
        # 后续多轮：QMT 仍返回 volume=0 残留行
        for _ in range(3):
            self._sync_real(pm, _real_df("301218.SZ", volume=0))

        mem_row = self.memory_conn.execute(
            "SELECT volume FROM positions WHERE stock_code=?", ("301218.SZ",)).fetchone()
        self.assertIsNone(mem_row, "残留行不应重建内存记录")
        self.assertIsNone(self._sqlite_row("301218.SZ"), "残留行不应重建 SQLite 记录")

    # ------------------------------------------------------------------
    # T4: 部分卖出（volume 1000→900）不触发删除，止盈状态继承（既有行为）
    # ------------------------------------------------------------------
    def test_T4_partial_sell_keeps_position_and_state(self):
        _insert_memory_position(self.memory_conn, "301218.SZ", volume=1000, available=1000,
                                cost_price=43.0, profit_triggered=True, highest_price=50.0)

        pm = self._make_sync_pm()
        self._sync_real(pm, _real_df("301218.SZ", volume=900, cost_price=43.0))

        row = self.memory_conn.execute(
            "SELECT volume, profit_triggered, highest_price FROM positions "
            "WHERE stock_code=?", ("301218.SZ",)).fetchone()
        self.assertIsNotNone(row, "部分卖出的持仓记录必须保留")
        self.assertEqual(int(row[0]), 900)
        self.assertTrue(bool(row[1]), "部分卖出时 profit_triggered 应继承不变")
        self.assertGreaterEqual(float(row[2]), 50.0 - 0.01, "highest_price 不应被重置")

    # ------------------------------------------------------------------
    # T5: 卖出在途（volume 不变、available=0 冻结）不误删
    # ------------------------------------------------------------------
    def test_T5_frozen_position_not_deleted(self):
        _insert_memory_position(self.memory_conn, "301218.SZ", volume=1000, available=1000,
                                cost_price=43.0, profit_triggered=False, highest_price=44.0)

        pm = self._make_sync_pm()
        self._sync_real(pm, _real_df("301218.SZ", volume=1000, available=0, cost_price=43.0))

        row = self.memory_conn.execute(
            "SELECT volume FROM positions WHERE stock_code=?", ("301218.SZ",)).fetchone()
        self.assertIsNotNone(row, "卖出在途（冻结）持仓不得删除")
        self.assertEqual(int(row[0]), 1000)

    # ------------------------------------------------------------------
    # T6: 删除后重启恢复 — SQLite 无残留，_sync_db_to_memory 后内存无该股
    # ------------------------------------------------------------------
    def test_T6_restart_recovery_no_stale_state(self):
        _insert_memory_position(self.memory_conn, "301218.SZ", volume=100, available=100,
                                cost_price=43.01, profit_triggered=True, highest_price=50.0)
        _insert_sqlite_legacy_position(self.TEST_DB, "301218.SZ", volume=100, cost_price=43.01)

        pm = self._make_sync_pm()
        self._sync_real(pm, _real_df("301218.SZ", volume=0))
        self.assertIsNone(self._sqlite_row("301218.SZ"), "前置：SQLite 记录已删")

        # 模拟重启：SQLite → 内存 全量恢复
        from position_manager import PositionManager
        restart_conn = sqlite3.connect(self.TEST_DB, check_same_thread=False)
        restart_memory = _make_memory_conn()
        restart_pm = object.__new__(PositionManager)
        restart_pm.memory_conn = restart_memory
        restart_pm.conn = restart_conn
        try:
            PositionManager._sync_db_to_memory(restart_pm)
            row = restart_memory.execute(
                "SELECT volume FROM positions WHERE stock_code=?", ("301218.SZ",)).fetchone()
            self.assertIsNone(row, "重启后不得恢复已清仓股票的旧状态记录")
        finally:
            restart_conn.close()
            restart_memory.close()

    # ------------------------------------------------------------------
    # T7: 删除路径不经 get_position（防 remove_position 式无限递归回归）
    # ------------------------------------------------------------------
    def test_T7_delete_path_does_not_call_get_position(self):
        _insert_memory_position(self.memory_conn, "301218.SZ", volume=100, available=100,
                                cost_price=43.01, profit_triggered=True, highest_price=50.0)

        pm = self._make_sync_pm()
        # 若实现误用 remove_position：其内部 get_position → get_all_positions →
        # 间隔未更新再次进入 _sync_real_positions_to_memory → 无限递归。
        # 这里让任何 get_position 调用直接失败，锁定递归链第一环。
        pm.get_position = MagicMock(
            side_effect=AssertionError("删除路径不得调用 get_position（会引发无限递归）"))

        self._sync_real(pm, _real_df("301218.SZ", volume=0))

        pm.get_position.assert_not_called()
        mem_row = self.memory_conn.execute(
            "SELECT volume FROM positions WHERE stock_code=?", ("301218.SZ",)).fetchone()
        self.assertIsNone(mem_row, "记录应已删除（_delete_position_direct 路径）")

    # ------------------------------------------------------------------
    # T8: SQLite 即时删除失败 → 内存已删，15 秒同步线程 P6 路径兜底清除
    # ------------------------------------------------------------------
    def test_T8_sqlite_delete_failure_fallback_to_p6(self):
        _insert_memory_position(self.memory_conn, "301218.SZ", volume=100, available=100,
                                cost_price=43.01, profit_triggered=True, highest_price=50.0)
        _insert_sqlite_legacy_position(self.TEST_DB, "301218.SZ", volume=100, cost_price=43.01)

        pm = self._make_sync_pm()
        # 模拟 SQLite 即时删除连接失败（如 database is locked）
        with patch('sqlite3.connect', side_effect=RuntimeError("mock sqlite locked")):
            self._sync_real(pm, _real_df("301218.SZ", volume=0))

        mem_row = self.memory_conn.execute(
            "SELECT volume FROM positions WHERE stock_code=?", ("301218.SZ",)).fetchone()
        self.assertIsNone(mem_row, "内存记录应已删除（与 SQLite 删除失败无关）")
        self.assertIsNotNone(self._sqlite_row("301218.SZ"),
                             "前置：SQLite 残留待兜底清理")

        # P6 兜底：_sync_memory_to_db 发现"内存无 SQLite 有" → 删除
        with patch.object(config, 'ENABLE_SIMULATION_MODE', False), \
             patch('config.is_trade_time', return_value=True):
            pm._sync_memory_to_db()

        self.assertIsNone(self._sqlite_row("301218.SZ"),
                          "P6 路径应兜底清除 SQLite 残留记录")

    # ------------------------------------------------------------------
    # T9: QMT 残留行余额为 NaN/None → 清洗为 0 后跳过，不重建不异常
    # ------------------------------------------------------------------
    def test_T9_nan_and_none_volume_residual_rows(self):
        pm = self._make_sync_pm()

        # 本地无记录 + NaN 余额行
        df_nan = pd.DataFrame([{
            '证券代码': '301218.SZ',
            '证券名称': '301218.SZ',
            '股票余额': float('nan'),
            '可用余额': float('nan'),
            '成本价': 43.01,
            '市值': 0.0,
        }])
        self._sync_real(pm, df_nan)
        row = self.memory_conn.execute(
            "SELECT volume FROM positions WHERE stock_code=?", ("301218.SZ",)).fetchone()
        self.assertIsNone(row, "NaN 残留行不应重建记录")

        # 本地无记录 + None 余额行
        df_none = pd.DataFrame([{
            '证券代码': '301218.SZ',
            '证券名称': '301218.SZ',
            '股票余额': None,
            '可用余额': None,
            '成本价': 43.01,
            '市值': 0.0,
        }])
        self._sync_real(pm, df_none)
        row = self.memory_conn.execute(
            "SELECT volume FROM positions WHERE stock_code=?", ("301218.SZ",)).fetchone()
        self.assertIsNone(row, "None 残留行不应重建记录")

        # 本地有记录 + NaN 余额行 → 按清仓处理删除
        _insert_memory_position(self.memory_conn, "301218.SZ", volume=100, available=100,
                                cost_price=43.01, profit_triggered=True, highest_price=50.0)
        self._sync_real(pm, df_nan)
        row = self.memory_conn.execute(
            "SELECT volume FROM positions WHERE stock_code=?", ("301218.SZ",)).fetchone()
        self.assertIsNone(row, "NaN 余额行在有记录时应按清仓删除")


if __name__ == '__main__':
    unittest.main(verbosity=2)
