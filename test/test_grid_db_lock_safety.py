"""
网格数据库锁安全与同步重试回归测试

对应 2026-09-14 实盘故障：10:08-10:49 期间 3176 条 `database is locked`，
持仓 SQLite 同步瘫痪 41 分钟、会话 27 中心价内存/DB 劈叉、002859 建会话三连 500。

覆盖两个根因：

A组 - 嵌套事务被无条件 commit 截断（grid_database.py）
    record_grid_trade_and_update_session 用显式 BEGIN 包住多步写入，
    但被它调用的 stop_grid_session / create_grid_order 是无条件 self.conn.commit()。
    内层 commit 会把外层事务提前结束，后续步骤裸奔在自动提交模式下，
    异常时 rollback 已无事务可回滚 → 半截数据落库。

B组 - 同步重试风暴（position_manager.py）
    _sync_memory_to_db 自己吞异常不外抛，_retry_sync 靠 try/except 判成败，
    导致「重试成功」恒真、计数器每轮清零、"最多重试2次"上限从未生效，
    且每次失败 threading.Timer 派生新线程 → 线程数 18→41。

C组 - 悬空写事务对独立连接的阻塞（机制回归）
"""

import os
import sys
import threading
import time
import unittest
from unittest.mock import patch

import sqlite3

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import config
from grid_database import DatabaseManager


def _make_db(path):
    """建一个带网格表的 WAL 库，贴近生产形态。"""
    db = DatabaseManager(db_path=path)
    db.conn.execute("PRAGMA journal_mode=WAL")
    db.init_grid_tables()
    return db


def _session_payload(stock_code, center_price=10.0):
    return {
        'stock_code': stock_code,
        'center_price': center_price,
        'price_interval': 0.02,
        'position_ratio': 0.2,
        'callback_ratio': 0.003,
        'max_investment': 50000.0,
        'max_deviation': 0.15,
        'target_profit': 0.05,
        'stop_loss': -0.08,
        'start_time': '2026-09-14T09:30:00',
        'end_time': '2026-12-31T15:00:00',
        'risk_level': 'moderate',
        'template_name': '稳健型网格',
    }


def _trade_payload(session_id, stock_code, trade_type='SELL'):
    return {
        'session_id': session_id,
        'stock_code': stock_code,
        'trade_type': trade_type,
        'grid_level': 73.46,
        'trigger_price': 73.40,
        'volume': 200,
        'amount': 14680.0,
        'peak_price': 73.76,
        'valley_price': None,
        'callback_ratio': 0.0049,
        'trade_id': '1745879041',
        'trade_time': '2026-09-14T10:08:06.283750',
        'grid_center_before': 70.63,
        'grid_center_after': 73.40,
    }


# ============================================================
# A组：嵌套事务原子性
# ============================================================
class TestNestedTransactionAtomicity(unittest.TestCase):
    """外层显式事务不得被内层写方法的 commit 截断。"""

    def setUp(self):
        import tempfile
        self.tmpdir = tempfile.mkdtemp()
        self.db_path = os.path.join(self.tmpdir, 'grid.db')
        self.db = _make_db(self.db_path)

    def tearDown(self):
        try:
            self.db.conn.close()
        except Exception:
            pass

    def test_a1_stop_grid_session_does_not_break_outer_transaction(self):
        """A1: 外层事务中调用 stop_grid_session，不应提前提交外层事务。"""
        sid = self.db.create_grid_session(_session_payload('301085.SZ'))

        cur = self.db.conn.cursor()
        cur.execute("BEGIN")
        self.db.update_grid_session(sid, {'current_center_price': 73.40})
        # 内层写方法：修复前会无条件 commit，把外层事务截断
        self.db.stop_grid_session(sid, 'replaced')

        self.assertTrue(
            self.db.conn.in_transaction,
            "stop_grid_session 提前提交了外层事务（嵌套事务被截断）"
        )
        self.db.conn.rollback()

        # 外层回滚后，两项修改都应消失
        row = self.db.conn.execute(
            "SELECT status, current_center_price FROM grid_trading_sessions WHERE id=?",
            (sid,)).fetchone()
        self.assertEqual(row['status'], 'active', "回滚后 status 仍被改写 → 内层commit已落库")
        self.assertAlmostEqual(row['current_center_price'], 10.0, places=4,
                               msg="回滚后中心价仍被改写 → 事务原子性破损")

    def test_a2_create_grid_order_does_not_break_outer_transaction(self):
        """A2: create_grid_order 在外层事务内不得提交。"""
        sid = self.db.create_grid_session(_session_payload('002859.SZ'))

        cur = self.db.conn.cursor()
        cur.execute("BEGIN")
        self.db.create_grid_order({
            'order_id': '1745879042',
            'session_id': sid,
            'stock_code': '002859.SZ',
            'side': 'BUY',
            'status': 'submitted',
            'requested_volume': 1200,
            'expected_price': 66.19,
            'submitted_at': '2026-09-14T10:48:01',
        })
        self.assertTrue(
            self.db.conn.in_transaction,
            "create_grid_order 提前提交了外层事务"
        )
        self.db.conn.rollback()

        n = self.db.conn.execute(
            "SELECT COUNT(*) c FROM grid_orders WHERE order_id=?", ('1745879042',)
        ).fetchone()['c']
        self.assertEqual(n, 0, "回滚后委托记录仍在 → 内层commit已落库")

    def test_a3_full_rollback_on_ledger_failure(self):
        """A3: 落账中途失败时，成交明细/会话汇总必须整体回滚，不留半截数据。

        这是 A 组的业务后果：修复前内层 commit 已把前半段固化，
        rollback 只能回滚最后一小段。
        """
        sid = self.db.create_grid_session(_session_payload('301085.SZ', 70.63))
        trade = _trade_payload(sid, '301085.SZ')

        # 让账本步骤抛错，模拟中途失败
        with patch.object(self.db, '_apply_grid_ledger', side_effect=RuntimeError('boom')):
            with self.assertRaises(RuntimeError):
                self.db.record_grid_trade_and_update_session(
                    trade,
                    {'trade_count': 3, 'sell_count': 2, 'total_sell_amount': 14680.0},
                )

        trades = self.db.conn.execute(
            "SELECT COUNT(*) c FROM grid_trades WHERE session_id=?", (sid,)
        ).fetchone()['c']
        self.assertEqual(trades, 0, "失败后成交明细仍落库 → 事务未整体回滚")

        row = self.db.conn.execute(
            "SELECT trade_count FROM grid_trading_sessions WHERE id=?", (sid,)
        ).fetchone()
        self.assertEqual(row['trade_count'], 0, "失败后会话汇总被改写 → 事务未整体回滚")

    def test_a4_no_dangling_transaction_after_success(self):
        """A4: 正常落账后不得残留未提交事务（悬空事务会长期持写锁）。"""
        sid = self.db.create_grid_session(_session_payload('301085.SZ', 70.63))
        self.db.record_grid_trade_and_update_session(
            _trade_payload(sid, '301085.SZ'),
            {'trade_count': 1, 'sell_count': 1, 'total_sell_amount': 14680.0},
        )
        self.assertFalse(
            self.db.conn.in_transaction,
            "落账完成后仍持有未提交事务 → 会持续阻塞其它连接"
        )

    def test_a5_independent_connection_can_write_after_grid_trade(self):
        """A5: 网格落账后，独立连接（持仓同步线程口径）必须能立刻写入。

        直接复现故障现象：_sync_memory_to_db 用独立连接写同一个库。
        """
        sid = self.db.create_grid_session(_session_payload('301085.SZ', 70.63))
        self.db.record_grid_trade_and_update_session(
            _trade_payload(sid, '301085.SZ'),
            {'trade_count': 1, 'sell_count': 1, 'total_sell_amount': 14680.0},
        )

        other = sqlite3.connect(self.db_path, timeout=1.0)
        other.execute("PRAGMA busy_timeout = 1000")
        try:
            t0 = time.time()
            other.execute(
                "UPDATE grid_trading_sessions SET current_center_price=? WHERE id=?",
                (73.40, sid))
            other.commit()
            self.assertLess(time.time() - t0, 1.0, "独立连接写入被阻塞")
        finally:
            other.close()


# ============================================================
# B组：同步重试不再风暴
# ============================================================
class _FakePM:
    """只暴露重试逻辑所需属性的 PositionManager 桩。"""

    def __init__(self, fail_times):
        self.fail_times = fail_times
        self.calls = 0
        self._sync_retry_count = 0
        self.sync_stop_flag = False
        self.timers = []

    def _sync_memory_to_db(self):
        self.calls += 1
        if self.calls <= self.fail_times:
            raise sqlite3.OperationalError('database is locked')


class TestSyncRetryStorm(unittest.TestCase):
    """重试上限必须真实生效，且不得无限派生 Timer 线程。"""

    def setUp(self):
        from position_manager import PositionManager
        self.PM = PositionManager

    def _bind(self, pm):
        from position_manager import PositionManager
        pm._retry_sync = PositionManager._retry_sync.__get__(pm, _FakePM)
        pm._schedule_sync_retry = PositionManager._schedule_sync_retry.__get__(pm, _FakePM)
        return pm

    def test_b1_retry_stops_at_limit_when_always_failing(self):
        """B1: 持续失败时，重试次数必须在上限处停止，不得无限循环。"""
        pm = self._bind(_FakePM(fail_times=10 ** 6))
        started = []

        def fake_timer(delay, fn):
            class T:
                def start(_self):
                    started.append(fn)

                def setDaemon(_self, v):
                    pass
            return T()

        with patch('position_manager.threading.Timer', side_effect=fake_timer):
            pm._schedule_sync_retry()
            # 手动驱动排队的重试，最多驱动 20 轮
            rounds = 0
            while started and rounds < 20:
                fn = started.pop(0)
                fn()
                rounds += 1

        self.assertLessEqual(
            rounds, 3,
            f"持续失败仍排了 {rounds} 轮重试 → 重试上限未生效（故障时刷了1586轮）"
        )

    def test_b2_counter_not_reset_on_silent_failure(self):
        """B2: _sync_memory_to_db 静默失败（吞异常）时，计数器不得被误判为成功而清零。

        这是刷屏的核心：修复前 _retry_sync 靠 except 判成败，
        而 _sync_memory_to_db 自己 except 掉了异常 → 永远"成功"。
        """
        pm = self._bind(_FakePM(fail_times=0))

        # 模拟静默失败：不抛异常，但内部标记失败
        def silent_fail():
            pm.calls += 1
            pm._sync_last_error = sqlite3.OperationalError('database is locked')

        pm._sync_memory_to_db = silent_fail
        pm._sync_retry_count = 2
        pm._sync_last_error = None

        with patch('position_manager.threading.Timer'):
            pm._retry_sync()

        self.assertNotEqual(
            pm._sync_retry_count, 0,
            "静默失败被误判为成功并清零计数器 → 重试上限永远打不满"
        )

    def test_b3_counter_resets_on_real_success(self):
        """B3: 真正成功后计数器必须归零，不影响后续正常重试。"""
        pm = self._bind(_FakePM(fail_times=0))
        pm._sync_retry_count = 2
        pm._sync_last_error = None

        with patch('position_manager.threading.Timer'):
            pm._retry_sync()

        self.assertEqual(pm._sync_retry_count, 0, "成功后计数器未归零")

    def test_b4_timer_threads_bounded(self):
        """B4: 连续多轮失败，累计派生的 Timer 数量必须有界。

        故障现场：41 分钟内线程数 18→41，句柄 1035→1170。
        """
        pm = self._bind(_FakePM(fail_times=10 ** 6))
        created = []

        def fake_timer(delay, fn):
            created.append(fn)

            class T:
                def start(_self):
                    pass

                def setDaemon(_self, v):
                    pass
            return T()

        with patch('position_manager.threading.Timer', side_effect=fake_timer):
            # 模拟同步线程连续 50 轮失败
            for _ in range(50):
                pm._schedule_sync_retry()

        self.assertLessEqual(
            len(created), 50,
            f"50轮失败派生了 {len(created)} 个 Timer → 存在放大"
        )


    def test_b5_real_chain_bounded_under_persistent_lock(self):
        """B5: 真实 _sync_memory_to_db + 真实写锁占用，整条重试链必须有界。

        端到端复现故障场景：一条连接悬空写事务长期持锁，
        同步线程用独立连接反复失败。修复前这里会无限重试并堆积 Timer。
        """
        import tempfile
        import pandas as pd  # noqa: F401  (position_manager 依赖)
        from position_manager import PositionManager

        tmpdir = tempfile.mkdtemp()
        db_path = os.path.join(tmpdir, 'lock.db')

        seed = sqlite3.connect(db_path)
        seed.execute("PRAGMA journal_mode=WAL")
        seed.execute("""CREATE TABLE positions(
            stock_code TEXT PRIMARY KEY, stock_name TEXT, volume REAL, available REAL,
            cost_price REAL, base_cost_price REAL, open_date TEXT, profit_triggered INTEGER,
            highest_price REAL, stop_loss_price REAL, profit_breakout_triggered INTEGER,
            breakout_highest_price REAL, last_update TEXT)""")
        seed.commit()
        seed.close()

        memory_conn = sqlite3.connect(':memory:', check_same_thread=False)
        memory_conn.execute("""CREATE TABLE positions(
            stock_code TEXT PRIMARY KEY, stock_name TEXT, volume REAL, available REAL,
            cost_price REAL, base_cost_price REAL, open_date TEXT, profit_triggered INTEGER,
            highest_price REAL, stop_loss_price REAL, profit_breakout_triggered INTEGER,
            breakout_highest_price REAL, last_update TEXT)""")
        memory_conn.execute(
            "INSERT INTO positions VALUES ('301085.SZ','亚康股份',1000,1000,73.57,73.57,"
            "'2026-09-10',0,75.8,68.42,0,0,'2026-09-14 10:08:08')")
        memory_conn.commit()

        class FakePM:
            pass

        pm = FakePM()
        pm.memory_conn = memory_conn
        pm.memory_conn_lock = threading.Lock()
        pm._sync_retry_count = 0
        pm._sync_last_error = None
        for name in ('_sync_memory_to_db', '_schedule_sync_retry', '_retry_sync'):
            setattr(pm, name, getattr(PositionManager, name).__get__(pm, FakePM))

        # 悬空写事务，长期占住写锁
        holder = sqlite3.connect(db_path, check_same_thread=False)
        holder.execute("PRAGMA busy_timeout = 60000")
        holder.execute("INSERT INTO positions(stock_code, volume) VALUES ('000001.SZ', 1)")
        self.assertTrue(holder.in_transaction)

        base_threads = threading.active_count()
        try:
            with patch.object(config, 'DB_PATH', db_path), \
                 patch.object(config, 'ENABLE_SIMULATION_MODE', False), \
                 patch.object(config, 'POSITION_SYNC_RETRY_DELAY', 0.2), \
                 patch.object(config, 'POSITION_SYNC_BUSY_TIMEOUT_MS', 200), \
                 patch.object(config, 'is_trade_time', return_value=True):
                pm._sync_memory_to_db()
                # 等足够长：若重试无界，此处会持续派生 Timer
                time.sleep(0.2 * (config.POSITION_SYNC_MAX_RETRY + 4) + 1.5)

                self.assertLessEqual(
                    pm._sync_retry_count, config.POSITION_SYNC_MAX_RETRY,
                    f"重试计数 {pm._sync_retry_count} 超过上限 "
                    f"{config.POSITION_SYNC_MAX_RETRY} → 重试风暴未根治"
                )
                self.assertLessEqual(
                    threading.active_count() - base_threads, 1,
                    "Timer 线程堆积 → 线程泄漏未根治"
                )
        finally:
            holder.rollback()
            holder.close()
            memory_conn.close()


# ============================================================
# C组：悬空事务阻塞机制（回归护栏）
# ============================================================
class TestDanglingTransactionBlocks(unittest.TestCase):

    def setUp(self):
        import tempfile
        self.tmpdir = tempfile.mkdtemp()
        self.db_path = os.path.join(self.tmpdir, 'wal.db')
        c = sqlite3.connect(self.db_path)
        c.execute("PRAGMA journal_mode=WAL")
        c.execute("CREATE TABLE t(x INTEGER)")
        c.commit()
        c.close()

    def test_c1_dangling_write_txn_blocks_independent_conn(self):
        """C1: 悬空写事务会让独立连接拿不到写锁（故障机制本身）。"""
        holder = sqlite3.connect(self.db_path, check_same_thread=False)
        holder.execute("PRAGMA busy_timeout = 30000")
        holder.execute("INSERT INTO t VALUES (1)")   # 隐式 BEGIN，不提交
        self.assertTrue(holder.in_transaction)

        other = sqlite3.connect(self.db_path)
        other.execute("PRAGMA busy_timeout = 300")
        try:
            with self.assertRaises(sqlite3.OperationalError):
                other.execute("INSERT INTO t VALUES (2)")
                other.commit()
        finally:
            other.close()
            holder.rollback()
            holder.close()

    def test_c2_released_after_commit(self):
        """C2: 提交后写锁立即释放。"""
        holder = sqlite3.connect(self.db_path, check_same_thread=False)
        holder.execute("INSERT INTO t VALUES (1)")
        holder.commit()

        other = sqlite3.connect(self.db_path)
        other.execute("PRAGMA busy_timeout = 1000")
        try:
            other.execute("INSERT INTO t VALUES (2)")
            other.commit()
        finally:
            other.close()
            holder.close()


if __name__ == '__main__':
    unittest.main(verbosity=2)
