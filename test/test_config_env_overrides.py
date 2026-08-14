import importlib
import os
import sys
import tempfile
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


class TestConfigEnvOverrides(unittest.TestCase):
    def setUp(self):
        self._env_keys = [
            "GRID_REQUIRE_PROFIT_TRIGGERED",
            "ENABLE_BAOSTOCK_STOCK_NAME_LOOKUP",
            "ENABLE_BAOSTOCK_HISTORY_DATA",
            "XQM_PORT",
            "XTQUANT_MANAGER_URL",
            "WEB_SERVER_PORT",
            "WEB_PUBLIC_MODE",
            "MINIQMT_DISABLE_DOTENV",
        ]
        self._orig_env = {key: os.environ.get(key) for key in self._env_keys}
        os.environ["MINIQMT_DISABLE_DOTENV"] = "1"

    def tearDown(self):
        for key, value in self._orig_env.items():
            if value is None:
                os.environ.pop(key, None)
            else:
                os.environ[key] = value

        if "config" in sys.modules:
            importlib.reload(sys.modules["config"])

    def _reload_config(self):
        if "config" in sys.modules:
            return importlib.reload(sys.modules["config"])

        import config
        return config

    def test_grid_require_profit_triggered_reads_env(self):
        os.environ["GRID_REQUIRE_PROFIT_TRIGGERED"] = "true"
        config = self._reload_config()
        self.assertTrue(config.GRID_REQUIRE_PROFIT_TRIGGERED)

        os.environ["GRID_REQUIRE_PROFIT_TRIGGERED"] = "0"
        config = self._reload_config()
        self.assertFalse(config.GRID_REQUIRE_PROFIT_TRIGGERED)

    def test_baostock_switches_default_to_disabled(self):
        os.environ.pop("ENABLE_BAOSTOCK_STOCK_NAME_LOOKUP", None)
        os.environ.pop("ENABLE_BAOSTOCK_HISTORY_DATA", None)

        config = self._reload_config()

        self.assertFalse(config.ENABLE_BAOSTOCK_STOCK_NAME_LOOKUP)
        self.assertFalse(config.ENABLE_BAOSTOCK_HISTORY_DATA)

    def test_xqm_port_derives_xtquant_manager_url(self):
        os.environ["XQM_PORT"] = "8890"
        os.environ.pop("XTQUANT_MANAGER_URL", None)

        config = self._reload_config()

        self.assertEqual(config.XTQUANT_MANAGER_PORT, 8890)
        self.assertEqual(config.XTQUANT_MANAGER_URL, "http://127.0.0.1:8890")

    def test_xtquant_manager_url_env_overrides_derived_url(self):
        os.environ["XQM_PORT"] = "8890"
        os.environ["XTQUANT_MANAGER_URL"] = "http://127.0.0.1:8891"

        config = self._reload_config()

        self.assertEqual(config.XTQUANT_MANAGER_PORT, 8890)
        self.assertEqual(config.XTQUANT_MANAGER_URL, "http://127.0.0.1:8891")

    def test_web_server_port_reads_env(self):
        os.environ["WEB_SERVER_PORT"] = "5100"

        config = self._reload_config()

        self.assertEqual(config.WEB_SERVER_BASE_PORT, 5100)
        self.assertEqual(config.WEB_SERVER_PORT, 5100)

    def test_web_server_port_invalid_falls_back_to_default(self):
        os.environ["WEB_SERVER_PORT"] = "not-a-port"

        config = self._reload_config()

        self.assertEqual(config.WEB_SERVER_BASE_PORT, 5000)
        self.assertEqual(config.WEB_SERVER_PORT, 5000)

    def test_web_public_mode_reads_env(self):
        os.environ["WEB_PUBLIC_MODE"] = "true"
        config = self._reload_config()
        self.assertTrue(config.WEB_PUBLIC_MODE)

        os.environ["WEB_PUBLIC_MODE"] = "0"
        config = self._reload_config()
        self.assertFalse(config.WEB_PUBLIC_MODE)


class TestDotenvFallback(unittest.TestCase):
    """验证 _load_dotenv_fallback：环境变量为主，.env 仅补充未设置的键。"""

    def _load(self):
        import config
        return config._load_dotenv_fallback

    def _write_env(self, text):
        fd, path = tempfile.mkstemp(suffix=".env")
        os.close(fd)
        with open(path, "w", encoding="utf-8") as f:
            f.write(text)
        self.addCleanup(lambda: os.path.exists(path) and os.remove(path))
        return path

    def test_env_missing_key_is_filled_from_dotenv(self):
        load = self._load()
        key = "TEST_DOTENV_FILL_KEY"
        os.environ.pop(key, None)
        self.addCleanup(lambda: os.environ.pop(key, None))
        path = self._write_env("%s=from_dotenv\n" % key)
        load(path)
        self.assertEqual(os.environ[key], "from_dotenv")

    def test_existing_env_var_is_not_overridden(self):
        load = self._load()
        key = "TEST_DOTENV_PRIORITY_KEY"
        os.environ[key] = "from_env"
        self.addCleanup(lambda: os.environ.pop(key, None))
        path = self._write_env("%s=from_dotenv\n" % key)
        load(path)
        # 已存在的环境变量优先，.env 不覆盖
        self.assertEqual(os.environ[key], "from_env")

    def test_comments_and_blank_lines_skipped(self):
        load = self._load()
        key = "TEST_DOTENV_COMMENT_KEY"
        os.environ.pop(key, None)
        self.addCleanup(lambda: os.environ.pop(key, None))
        path = self._write_env("# comment line\n\n%s=value1\n" % key)
        load(path)
        self.assertEqual(os.environ[key], "value1")

    def test_quotes_are_stripped(self):
        load = self._load()
        key = "TEST_DOTENV_QUOTE_KEY"
        os.environ.pop(key, None)
        self.addCleanup(lambda: os.environ.pop(key, None))
        path = self._write_env('%s="quoted value"\n' % key)
        load(path)
        self.assertEqual(os.environ[key], "quoted value")

    def test_missing_file_is_noop(self):
        load = self._load()
        # 不存在的路径不应抛异常
        load(os.path.join(tempfile.gettempdir(), "definitely_missing_xyz.env"))


if __name__ == "__main__":
    unittest.main()
