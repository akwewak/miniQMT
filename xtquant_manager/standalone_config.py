# xtquant_manager/standalone_config.py
"""
StandaloneConfig — 独立运行模式配置加载器

从 JSON 文件加载配置，不依赖 miniQMT 的 config.py。
优先级：显式路径 > 环境变量 XTQUANT_MANAGER_CONFIG > 当前目录 xtquant_manager_config.json > 默认值

配置文件格式（xtquant_manager_config.json，仅保存网关运行参数）:
api_token 可留空；Token 优先级：XQM_API_TOKEN > QMT_API_TOKEN > JSON api_token。
{
  "host": "127.0.0.1",
  "port": 8888,
  "api_token": "",
  "allowed_ips": [],
  "rate_limit": 60,
  "enable_hmac": false,
  "hmac_secret": "",
  "trust_proxy": false,
  "ssl_certfile": "",
  "ssl_keyfile": "",
  "health_check_interval": 30.0,
  "reconnect_cooldown": 60.0,
  "heartbeat_interval": 1800.0,
  "watchdog_interval": 10.0,
  "watchdog_restart_cooldown": 30.0
}

账号配置统一从 account_config.json 读取。
"""
import json
import logging
import os
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional

LOGGER = logging.getLogger("xtquant_manager.standalone_config")


@dataclass
class AccountEntry:
    """account_config.json 中的单个账号条目"""
    account_id: str
    qmt_path: str
    account_type: str = "STOCK"
    call_timeout: float = 3.0
    reconnect_base_wait: float = 60.0
    max_reconnect_attempts: int = 5


@dataclass
class StandaloneConfig:
    """独立运行配置，所有字段均有默认值"""
    # HTTP 服务
    host: str = "127.0.0.1"
    port: int = 8888
    # 安全
    api_token: str = ""
    allowed_ips: List[str] = field(default_factory=list)
    rate_limit: int = 60
    enable_hmac: bool = False
    hmac_secret: str = ""
    # 是否信任 X-Forwarded-For：仅在受信任反向代理之后开启。
    # 保持 False 时伪造该头无法冒充本机绕过 token 验证。
    trust_proxy: bool = False
    # TLS（可选）
    ssl_certfile: str = ""
    ssl_keyfile: str = ""
    # 账号健康监控
    health_check_interval: float = 30.0
    reconnect_cooldown: float = 60.0
    # 服务看门狗
    watchdog_interval: float = 10.0
    watchdog_restart_cooldown: float = 30.0
    # 止盈止损监控（默认启用，参数与 config.py 保持一致）
    enable_stop_profit: bool = True
    stop_loss_ratio: float = -0.075
    initial_take_profit_ratio: float = 0.06
    initial_take_profit_pullback_ratio: float = 0.005
    initial_take_profit_sell_ratio: float = 0.6
    stop_profit_interval: float = 3.0
    stop_profit_dedup_seconds: float = 60.0
    # 心跳日志
    heartbeat_interval: float = 1800.0
    # 账号列表（统一从 account_config.json 加载）
    accounts: List[AccountEntry] = field(default_factory=list)


def _strip_env_value(value: str) -> str:
    raw = str(value).strip()
    if len(raw) >= 2 and raw[0] == raw[-1] and raw[0] in ("'", '"'):
        raw = raw[1:-1]
    return raw


def _read_dotenv_value(name: str, dotenv_anchor: Optional[str] = None) -> str:
    candidates = []
    if dotenv_anchor:
        base_dir = os.path.dirname(os.path.abspath(dotenv_anchor))
        if base_dir:
            candidates.append(os.path.join(base_dir, ".env"))
    candidates.append(os.path.abspath(".env"))

    seen = set()
    for path in candidates:
        if path in seen:
            continue
        seen.add(path)
        if not os.path.isfile(path):
            continue
        try:
            with open(path, "r", encoding="utf-8-sig") as f:
                lines = f.read().splitlines()
        except OSError:
            continue
        for raw_line in lines:
            line = raw_line.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            key, _, value = line.partition("=")
            if key.strip() == name:
                return _strip_env_value(value)
    return ""


def _env_value(name: str, dotenv_anchor: Optional[str] = None) -> str:
    value = os.environ.get(name)
    if value is not None and str(value).strip() != "":
        return _strip_env_value(value)
    return _read_dotenv_value(name, dotenv_anchor)


def _resolve_api_token(default: str, dotenv_anchor: Optional[str] = None) -> str:
    """解析网关 API Token，优先使用环境变量，避免在 JSON 配置中保存明文。"""
    for name in ("XQM_API_TOKEN", "QMT_API_TOKEN"):
        value = _env_value(name, dotenv_anchor)
        if value:
            return value
    return default


def _env_int(name: str, default: int, min_value=None, max_value=None, dotenv_anchor: Optional[str] = None) -> int:
    value = _env_value(name, dotenv_anchor)
    if value is None or value == "":
        return default
    try:
        parsed = int(value)
    except (TypeError, ValueError):
        return default
    if min_value is not None and parsed < min_value:
        return default
    if max_value is not None and parsed > max_value:
        return default
    return parsed


def _resolve_account_config_path(manager_config_path: Optional[str] = None) -> Optional[str]:
    """查找与网关配置同目录或当前目录下的 account_config.json。"""
    candidates = []
    if manager_config_path:
        base_dir = os.path.dirname(os.path.abspath(manager_config_path))
        if base_dir:
            candidates.append(os.path.join(base_dir, "account_config.json"))
    candidates.append(os.path.abspath("account_config.json"))

    seen = set()
    for path in candidates:
        if path in seen:
            continue
        seen.add(path)
        if os.path.isfile(path):
            return path
    return None


def _account_items(data: Dict[str, Any]) -> List[Dict[str, Any]]:
    accounts = data.get("accounts") or []
    if not isinstance(accounts, list):
        accounts = []
    if accounts:
        return [a for a in accounts if isinstance(a, dict)]
    if data.get("account_id"):
        return [data]
    return []


def _load_accounts_from_account_config(manager_config_path: Optional[str] = None) -> List[AccountEntry]:
    path = _resolve_account_config_path(manager_config_path)
    if not path:
        LOGGER.warning("未找到 account_config.json，XtQuantManager 将不自动注册账号")
        return []

    try:
        with open(path, "r", encoding="utf-8") as f:
            data = json.load(f)
    except (OSError, json.JSONDecodeError) as e:
        LOGGER.warning(f"加载 account_config.json 失败，XtQuantManager 将不自动注册账号: {e}")
        return []

    account_fields = set(AccountEntry.__dataclass_fields__)
    accounts = []
    for item in _account_items(data):
        if not item.get("account_id") or not item.get("qmt_path"):
            continue
        accounts.append(AccountEntry(**{k: v for k, v in item.items() if k in account_fields}))

    if not accounts:
        LOGGER.warning(f"account_config.json 中没有有效账号: {path}")
    return accounts


def load_standalone_config(config_path: str = "") -> StandaloneConfig:
    """
    从 JSON 文件加载独立运行配置。

    Args:
        config_path: 配置文件路径。为空时按优先级查找：
            1. 环境变量 XTQUANT_MANAGER_CONFIG
            2. 当前目录的 xtquant_manager_config.json

    Returns:
        StandaloneConfig 实例（找不到文件时使用全部默认值）
    """
    path = _resolve_config_path(config_path)
    if not path:
        defaults = StandaloneConfig()
        defaults.port = _env_int("XQM_PORT", defaults.port, 1, 65535, config_path)
        defaults.api_token = _resolve_api_token(defaults.api_token, config_path)
        defaults.accounts = _load_accounts_from_account_config(config_path)
        return defaults

    try:
        with open(path, "r", encoding="utf-8") as f:
            data = json.load(f)
    except (OSError, json.JSONDecodeError) as e:
        LOGGER.warning(f"加载配置文件失败，使用默认配置: {e}")
        defaults = StandaloneConfig()
        defaults.port = _env_int("XQM_PORT", defaults.port, 1, 65535, path)
        defaults.api_token = _resolve_api_token(defaults.api_token, path)
        defaults.accounts = _load_accounts_from_account_config(path)
        return defaults

    return _parse_config(data, path)


def _resolve_config_path(config_path: str) -> Optional[str]:
    """按优先级解析配置文件路径"""
    if config_path:
        if os.path.isfile(config_path):
            return config_path
        LOGGER.warning(f"指定的配置文件不存在: {config_path}，将按优先级回退查找")

    env_path = os.environ.get("XTQUANT_MANAGER_CONFIG", "")
    if env_path and os.path.isfile(env_path):
        return env_path

    local_path = "xtquant_manager_config.json"
    if os.path.isfile(local_path):
        return local_path

    return None


def _parse_config(data: Dict[str, Any], manager_config_path: Optional[str] = None) -> StandaloneConfig:
    """将 JSON dict 解析为 StandaloneConfig"""
    defaults = StandaloneConfig()

    return StandaloneConfig(
        host=data.get("host", defaults.host),
        port=_env_int("XQM_PORT", data.get("port", defaults.port), 1, 65535, manager_config_path),
        api_token=_resolve_api_token(data.get("api_token", defaults.api_token), manager_config_path),
        allowed_ips=data.get("allowed_ips", defaults.allowed_ips),
        rate_limit=data.get("rate_limit", defaults.rate_limit),
        enable_hmac=data.get("enable_hmac", defaults.enable_hmac),
        hmac_secret=data.get("hmac_secret", defaults.hmac_secret),
        trust_proxy=data.get("trust_proxy", defaults.trust_proxy),
        ssl_certfile=data.get("ssl_certfile", defaults.ssl_certfile),
        ssl_keyfile=data.get("ssl_keyfile", defaults.ssl_keyfile),
        health_check_interval=data.get("health_check_interval", defaults.health_check_interval),
        reconnect_cooldown=data.get("reconnect_cooldown", defaults.reconnect_cooldown),
        watchdog_interval=data.get("watchdog_interval", defaults.watchdog_interval),
        watchdog_restart_cooldown=data.get("watchdog_restart_cooldown", defaults.watchdog_restart_cooldown),
        enable_stop_profit=data.get("enable_stop_profit", defaults.enable_stop_profit),
        stop_loss_ratio=data.get("stop_loss_ratio", defaults.stop_loss_ratio),
        initial_take_profit_ratio=data.get("initial_take_profit_ratio", defaults.initial_take_profit_ratio),
        initial_take_profit_pullback_ratio=data.get("initial_take_profit_pullback_ratio", defaults.initial_take_profit_pullback_ratio),
        initial_take_profit_sell_ratio=data.get("initial_take_profit_sell_ratio", defaults.initial_take_profit_sell_ratio),
        stop_profit_interval=data.get("stop_profit_interval", defaults.stop_profit_interval),
        stop_profit_dedup_seconds=data.get("stop_profit_dedup_seconds", defaults.stop_profit_dedup_seconds),
        heartbeat_interval=data.get("heartbeat_interval", defaults.heartbeat_interval),
        accounts=_load_accounts_from_account_config(manager_config_path),
    )
