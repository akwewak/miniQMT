# test/test_xtquant_manager/test_standalone.py
"""
StandaloneApplication 测试。

测试策略：
- 注入 mock 替换 XtQuantServer 和 XtQuantManager，不启动真实 uvicorn
- 验证生命周期：启动 → 注册账号 → 心跳 → 信号关闭
- 不测试信号处理本身（跨平台/线程不可靠），而是直接调用 stop()
"""
import os
import sys
import threading
import time
import unittest
from unittest.mock import MagicMock, patch

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(__file__))))

from xtquant_manager.standalone_config import StandaloneConfig, AccountEntry
from xtquant_manager.standalone import StandaloneApplication


class TestStandaloneApplicationLifecycle(unittest.TestCase):

    def _make_app(self, accounts=None, heartbeat_interval=9999.0):
        cfg = StandaloneConfig(
            host="127.0.0.1",
            port=8888,
            heartbeat_interval=heartbeat_interval,
            watchdog_interval=60.0,
            watchdog_restart_cooldown=30.0,
            accounts=accounts or [],
        )
        return StandaloneApplication(cfg)

    @patch("xtquant_manager.standalone.XtQuantServer")
    @patch("xtquant_manager.standalone.XtQuantManager")
    @patch("xtquant_manager.standalone.ServerWatchdog")
    def test_start_starts_server_and_watchdog(
        self, MockWatchdog, MockManager, MockServer
    ):
        """run() 应启动 server 和 watchdog"""
        mock_server_instance = MagicMock()
        mock_server_instance.is_running.return_value = True
        mock_server_instance.config = MagicMock()
        mock_server_instance.config.use_tls = False
        MockServer.return_value = mock_server_instance

        mock_watchdog_instance = MagicMock()
        mock_watchdog_instance.get_status.return_value = {"restart_count": 0}
        MockWatchdog.return_value = mock_watchdog_instance

        mock_manager_instance = MagicMock()
        mock_manager_instance.list_accounts.return_value = []
        MockManager.get_instance.return_value = mock_manager_instance

        app = self._make_app()
        t = threading.Thread(target=app.run, daemon=True)
        t.start()
        time.sleep(0.1)
        app.stop()
        t.join(timeout=3.0)

        mock_server_instance.start.assert_called_once_with(blocking=False)
        mock_watchdog_instance.start.assert_called_once()

    @patch("xtquant_manager.standalone.XtQuantServer")
    @patch("xtquant_manager.standalone.XtQuantManager")
    @patch("xtquant_manager.standalone.ServerWatchdog")
    def test_registers_accounts_on_start(
        self, MockWatchdog, MockManager, MockServer
    ):
        """run() 应注册配置中的账号"""
        mock_server_instance = MagicMock()
        mock_server_instance.is_running.return_value = True
        mock_server_instance.config = MagicMock()
        mock_server_instance.config.use_tls = False
        MockServer.return_value = mock_server_instance

        mock_watchdog_instance = MagicMock()
        mock_watchdog_instance.get_status.return_value = {"restart_count": 0}
        MockWatchdog.return_value = mock_watchdog_instance

        mock_manager_instance = MagicMock()
        mock_manager_instance.list_accounts.return_value = ["TEST_ACC_1"]
        MockManager.get_instance.return_value = mock_manager_instance

        accounts = [
            AccountEntry(account_id="TEST_ACC_1", qmt_path="C:/mock/path"),
        ]
        app = self._make_app(accounts=accounts)
        t = threading.Thread(target=app.run, daemon=True)
        t.start()
        time.sleep(0.1)
        app.stop()
        t.join(timeout=3.0)

        mock_manager_instance.register_account.assert_called_once()
        call_args = mock_manager_instance.register_account.call_args
        registered_config = call_args[0][0]
        self.assertEqual(registered_config.account_id, "TEST_ACC_1")

    @patch("xtquant_manager.standalone.XtQuantServer")
    @patch("xtquant_manager.standalone.XtQuantManager")
    @patch("xtquant_manager.standalone.ServerWatchdog")
    def test_stop_shuts_down_all_components(
        self, MockWatchdog, MockManager, MockServer
    ):
        """stop() 应依次停止 watchdog、server、manager（顺序：watchdog → server → manager）"""
        mock_server_instance = MagicMock()
        mock_server_instance.is_running.return_value = True
        mock_server_instance.config = MagicMock()
        mock_server_instance.config.use_tls = False
        MockServer.return_value = mock_server_instance

        mock_watchdog_instance = MagicMock()
        mock_watchdog_instance.get_status.return_value = {"restart_count": 0}
        MockWatchdog.return_value = mock_watchdog_instance

        mock_manager_instance = MagicMock()
        mock_manager_instance.list_accounts.return_value = []
        MockManager.get_instance.return_value = mock_manager_instance

        # 用调用顺序列表追踪关闭顺序
        call_order = []
        mock_watchdog_instance.stop.side_effect = lambda **kwargs: call_order.append('watchdog')
        mock_server_instance.stop.side_effect = lambda **kwargs: call_order.append('server')
        mock_manager_instance.shutdown.side_effect = lambda: call_order.append('manager')

        app = self._make_app()
        t = threading.Thread(target=app.run, daemon=True)
        t.start()
        time.sleep(0.1)
        app.stop()
        t.join(timeout=3.0)

        mock_watchdog_instance.stop.assert_called()
        mock_server_instance.stop.assert_called()
        mock_manager_instance.shutdown.assert_called()

        # 验证关闭顺序：watchdog → server → manager
        self.assertEqual(call_order, ['watchdog', 'server', 'manager'],
                         f"关闭顺序错误，实际顺序: {call_order}")

    @patch("xtquant_manager.standalone.XtQuantServer")
    @patch("xtquant_manager.standalone.XtQuantManager")
    @patch("xtquant_manager.standalone.ServerWatchdog")
    def test_account_registration_failure_does_not_crash(
        self, MockWatchdog, MockManager, MockServer
    ):
        """注册账号失败时，应用不应崩溃（记录错误继续运行）"""
        mock_server_instance = MagicMock()
        mock_server_instance.is_running.return_value = True
        mock_server_instance.config = MagicMock()
        mock_server_instance.config.use_tls = False
        MockServer.return_value = mock_server_instance

        mock_watchdog_instance = MagicMock()
        mock_watchdog_instance.get_status.return_value = {"restart_count": 0}
        MockWatchdog.return_value = mock_watchdog_instance

        mock_manager_instance = MagicMock()
        mock_manager_instance.register_account.side_effect = Exception("连接失败")
        mock_manager_instance.list_accounts.return_value = []
        MockManager.get_instance.return_value = mock_manager_instance

        accounts = [AccountEntry(account_id="99999999", qmt_path="C:/bad/path")]
        app = self._make_app(accounts=accounts)
        t = threading.Thread(target=app.run, daemon=True)
        t.start()
        time.sleep(0.2)
        app.stop()
        t.join(timeout=3.0)

        # 线程应已正常退出
        self.assertFalse(t.is_alive())

    @patch("xtquant_manager.standalone.XtQuantServer")
    @patch("xtquant_manager.standalone.XtQuantManager")
    @patch("xtquant_manager.standalone.ServerWatchdog")
    def test_http_start_failure_stops_before_watchdog_and_accounts(
        self, MockWatchdog, MockManager, MockServer
    ):
        """HTTP 服务启动失败时，应立即退出，不继续启动看门狗或注册账号。"""
        mock_server_instance = MagicMock()
        mock_server_instance.start.side_effect = RuntimeError("缺少 uvicorn")
        MockServer.return_value = mock_server_instance

        mock_manager_instance = MagicMock()
        MockManager.get_instance.return_value = mock_manager_instance

        accounts = [AccountEntry(account_id="TEST_ACC_1", qmt_path="C:/mock/path")]
        app = self._make_app(accounts=accounts)

        with self.assertRaisesRegex(RuntimeError, "uvicorn"):
            app.run()

        mock_server_instance.stop.assert_called_once()
        MockWatchdog.return_value.start.assert_not_called()
        mock_manager_instance.register_account.assert_not_called()


class TestStandaloneMain(unittest.TestCase):

    @patch("xtquant_manager.standalone.StandaloneApplication")
    @patch("xtquant_manager.standalone.load_standalone_config")
    def test_main_loads_config_and_runs(self, mock_load_cfg, MockApp):
        """main() 应加载配置并启动应用"""
        from xtquant_manager.standalone import main

        mock_cfg = StandaloneConfig()
        mock_load_cfg.return_value = mock_cfg

        mock_app_instance = MagicMock()
        MockApp.return_value = mock_app_instance

        main(argv=[])

        mock_load_cfg.assert_called_once_with("")
        MockApp.assert_called_once_with(mock_cfg)
        mock_app_instance.run.assert_called_once()

    @patch("xtquant_manager.standalone.StandaloneApplication")
    @patch("xtquant_manager.standalone.load_standalone_config")
    def test_main_applies_cli_overrides(self, mock_load_cfg, MockApp):
        """--host 和 --port 参数应覆盖配置文件中的值"""
        from xtquant_manager.standalone import main

        mock_cfg = StandaloneConfig(host="127.0.0.1", port=8888)
        mock_load_cfg.return_value = mock_cfg

        mock_app_instance = MagicMock()
        MockApp.return_value = mock_app_instance

        main(argv=["--host", "0.0.0.0", "--port", "9000"])

        call_args = MockApp.call_args
        passed_cfg = call_args[0][0]
        self.assertEqual(passed_cfg.host, "0.0.0.0")
        self.assertEqual(passed_cfg.port, 9000)


if __name__ == "__main__":
    unittest.main()
