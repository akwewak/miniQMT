# test/test_xtquant_manager/test_standalone_config.py
import json
import os
import sys
import tempfile
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(__file__))))

from xtquant_manager.standalone_config import (
    load_standalone_config,
    StandaloneConfig,
    AccountEntry,
)


class TestLoadStandaloneConfigDefaults(unittest.TestCase):
    """无配置文件时，返回全部默认值"""

    def test_returns_default_config_when_no_file(self):
        old_cwd = os.getcwd()
        old_env = os.environ.pop("XTQUANT_MANAGER_CONFIG", None)
        old_port = os.environ.pop("XQM_PORT", None)
        if old_env is not None:
            self.addCleanup(os.environ.__setitem__, "XTQUANT_MANAGER_CONFIG", old_env)
        if old_port is not None:
            self.addCleanup(os.environ.__setitem__, "XQM_PORT", old_port)

        with tempfile.TemporaryDirectory() as tmp:
            try:
                os.chdir(tmp)
                cfg = load_standalone_config("/nonexistent/path.json")
            finally:
                os.chdir(old_cwd)

        self.assertIsInstance(cfg, StandaloneConfig)
        self.assertEqual(cfg.host, "127.0.0.1")
        self.assertEqual(cfg.port, 8888)
        self.assertEqual(cfg.api_token, "")
        self.assertEqual(cfg.accounts, [])
        self.assertEqual(cfg.heartbeat_interval, 1800.0)
        self.assertEqual(cfg.watchdog_interval, 10.0)
        self.assertEqual(cfg.watchdog_restart_cooldown, 30.0)

    def test_loads_accounts_from_account_config_when_no_manager_file(self):
        old_cwd = os.getcwd()
        old_env = os.environ.pop("XTQUANT_MANAGER_CONFIG", None)
        old_port = os.environ.pop("XQM_PORT", None)
        if old_env is not None:
            self.addCleanup(os.environ.__setitem__, "XTQUANT_MANAGER_CONFIG", old_env)
        if old_port is not None:
            self.addCleanup(os.environ.__setitem__, "XQM_PORT", old_port)

        with tempfile.TemporaryDirectory() as tmp:
            account_path = os.path.join(tmp, "account_config.json")
            with open(account_path, "w", encoding="utf-8") as f:
                json.dump({
                    "account_id": "SOLO",
                    "qmt_path": "C:/QMT/userdata_mini",
                    "account_type": "STOCK",
                }, f)
            try:
                os.chdir(tmp)
                cfg = load_standalone_config("")
            finally:
                os.chdir(old_cwd)

        self.assertEqual(cfg.port, 8888)
        self.assertEqual(len(cfg.accounts), 1)
        self.assertEqual(cfg.accounts[0].account_id, "SOLO")


class TestLoadStandaloneConfigFromFile(unittest.TestCase):
    """从 JSON 文件与 account_config.json 加载配置"""

    def setUp(self):
        self._tmpdir = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmpdir.cleanup)
        self._old_cwd = os.getcwd()
        os.chdir(self._tmpdir.name)
        self.addCleanup(os.chdir, self._old_cwd)
        self._orig_env = {
            "XTQUANT_MANAGER_CONFIG": os.environ.get("XTQUANT_MANAGER_CONFIG"),
            "XQM_PORT": os.environ.get("XQM_PORT"),
        }
        for key in self._orig_env:
            os.environ.pop(key, None)

    def _write_config(self, data: dict) -> str:
        f = tempfile.NamedTemporaryFile(
            mode="w", suffix=".json", delete=False, encoding="utf-8", dir=self._tmpdir.name
        )
        json.dump(data, f)
        f.close()
        return f.name

    def _write_account_config(self, data: dict) -> str:
        path = os.path.join(self._tmpdir.name, "account_config.json")
        with open(path, "w", encoding="utf-8") as f:
            json.dump(data, f)
        return path

    def tearDown(self):
        for key, value in self._orig_env.items():
            if value is None:
                os.environ.pop(key, None)
            else:
                os.environ[key] = value

    def test_loads_basic_fields(self):
        path = self._write_config({
            "host": "0.0.0.0",
            "port": 9999,
            "api_token": "secret123",
            "rate_limit": 120,
        })
        self.addCleanup(os.unlink, path)
        cfg = load_standalone_config(path)
        self.assertEqual(cfg.host, "0.0.0.0")
        self.assertEqual(cfg.port, 9999)
        self.assertEqual(cfg.api_token, "secret123")
        self.assertEqual(cfg.rate_limit, 120)

    def test_loads_accounts_from_account_config(self):
        path = self._write_config({
            "accounts": [
                {
                    "account_id": "OLD_ACC",
                    "qmt_path": "C:/old/userdata_mini",
                },
            ]
        })
        self.addCleanup(os.unlink, path)
        self._write_account_config({
            "accounts": [
                {
                    "account_id": "TEST_ACC_1",
                    "qmt_path": "C:/test/userdata_mini",
                    "account_type": "STOCK",
                    "call_timeout": 5.0,
                },
                {
                    "account_id": "TEST_ACC_2",
                    "qmt_path": "C:/test/userdata_mini2",
                },
            ]
        })
        cfg = load_standalone_config(path)
        self.assertEqual(len(cfg.accounts), 2)
        self.assertEqual(cfg.accounts[0].account_id, "TEST_ACC_1")
        self.assertEqual(cfg.accounts[0].call_timeout, 5.0)
        self.assertEqual(cfg.accounts[1].account_id, "TEST_ACC_2")
        self.assertEqual(cfg.accounts[1].account_type, "STOCK")  # 默认值

    def test_ignores_accounts_in_manager_config_without_account_config(self):
        path = self._write_config({
            "accounts": [
                {
                    "account_id": "OLD_ACC",
                    "qmt_path": "C:/old/userdata_mini",
                },
            ]
        })
        self.addCleanup(os.unlink, path)

        cfg = load_standalone_config(path)

        self.assertEqual(cfg.accounts, [])

    def test_single_account_format_compat(self):
        path = self._write_config({})
        self.addCleanup(os.unlink, path)
        self._write_account_config({
            "account_id": "SOLO",
            "qmt_path": "C:/solo/userdata_mini",
            "account_type": "STOCK",
            "call_timeout": 4.0,
        })

        cfg = load_standalone_config(path)

        self.assertEqual(len(cfg.accounts), 1)
        self.assertEqual(cfg.accounts[0].account_id, "SOLO")
        self.assertEqual(cfg.accounts[0].qmt_path, "C:/solo/userdata_mini")
        self.assertEqual(cfg.accounts[0].call_timeout, 4.0)

    def test_loads_watchdog_and_heartbeat_fields(self):
        path = self._write_config({
            "watchdog_interval": 15.0,
            "watchdog_restart_cooldown": 60.0,
            "heartbeat_interval": 300.0,
        })
        self.addCleanup(os.unlink, path)
        cfg = load_standalone_config(path)
        self.assertEqual(cfg.watchdog_interval, 15.0)
        self.assertEqual(cfg.watchdog_restart_cooldown, 60.0)
        self.assertEqual(cfg.heartbeat_interval, 300.0)

    def test_env_var_takes_priority(self):
        path = self._write_config({"port": 7777})
        self.addCleanup(os.unlink, path)
        os.environ["XTQUANT_MANAGER_CONFIG"] = path
        cfg = load_standalone_config("")  # 不传路径，依赖环境变量
        self.assertEqual(cfg.port, 7777)

    def test_xqm_port_env_overrides_json_port(self):
        path = self._write_config({"port": 7777})
        self.addCleanup(os.unlink, path)
        os.environ["XQM_PORT"] = "8890"

        cfg = load_standalone_config(path)

        self.assertEqual(cfg.port, 8890)

    def test_loads_security_fields(self):
        path = self._write_config({
            "allowed_ips": ["192.168.1.1", "10.0.0.1"],
            "enable_hmac": True,
            "hmac_secret": "mysecret",
            "ssl_certfile": "/path/to/cert.pem",
            "ssl_keyfile": "/path/to/key.pem",
        })
        self.addCleanup(os.unlink, path)
        cfg = load_standalone_config(path)
        self.assertEqual(cfg.allowed_ips, ["192.168.1.1", "10.0.0.1"])
        self.assertTrue(cfg.enable_hmac)
        self.assertEqual(cfg.hmac_secret, "mysecret")
        self.assertEqual(cfg.ssl_certfile, "/path/to/cert.pem")

    def test_invalid_json_returns_default(self):
        """JSON 格式损坏时，应返回默认配置（不抛异常）"""
        f = tempfile.NamedTemporaryFile(
            mode="w", suffix=".json", delete=False, encoding="utf-8"
        )
        f.write("{ not valid json }")
        f.close()
        self.addCleanup(os.unlink, f.name)
        cfg = load_standalone_config(f.name)
        self.assertIsInstance(cfg, StandaloneConfig)
        self.assertEqual(cfg.host, "127.0.0.1")  # 默认值

    def test_explicit_path_overrides_env_var(self):
        """显式路径应优先于环境变量 XTQUANT_MANAGER_CONFIG"""
        path_explicit = self._write_config({"port": 1111})
        path_env = self._write_config({"port": 2222})
        self.addCleanup(os.unlink, path_explicit)
        self.addCleanup(os.unlink, path_env)
        os.environ["XTQUANT_MANAGER_CONFIG"] = path_env
        cfg = load_standalone_config(path_explicit)  # 显式路径应胜出
        self.assertEqual(cfg.port, 1111)


if __name__ == "__main__":
    unittest.main()
