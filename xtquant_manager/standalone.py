# xtquant_manager/standalone.py
"""
StandaloneApplication — 独立无人值守运行入口

脱离 miniQMT 独立运行，提供完整的 xtquant HTTP API 服务：
- 从 JSON 配置文件加载参数（不依赖 miniQMT config.py）
- 启动 FastAPI/uvicorn HTTP 服务
- 启动 HealthMonitor 监控账号连接健康
- 启动 ServerWatchdog 监控 HTTP 服务线程，崩溃后自动重启
- 处理 SIGINT/SIGTERM 信号，触发优雅退出
- 心跳日志（可配置间隔）

用法:
    python -m xtquant_manager
    python -m xtquant_manager --config /path/to/config.json
    python -m xtquant_manager --host 0.0.0.0 --port 8888
"""
import argparse
import signal
import threading
import time
from typing import Optional

from .standalone_config import StandaloneConfig, load_standalone_config
from .server_runner import XtQuantServer, XtQuantServerConfig
from .manager import XtQuantManager
from .account import AccountConfig
from .watchdog import ServerWatchdog

try:
    from logger import get_logger
    logger = get_logger("xqm_standalone")
except Exception:
    import logging
    logger = logging.getLogger("xtquant_manager.standalone")

try:
    from maintenance import rotate_xqm_log
except Exception:
    rotate_xqm_log = None


class StandaloneApplication:
    """
    独立运行应用，管理完整的无人值守生命周期。

    Usage:
        cfg = load_standalone_config("config.json")
        app = StandaloneApplication(cfg)
        app.run()    # 阻塞，直到收到停止信号
    """

    def __init__(self, config: StandaloneConfig):
        self._config = config
        self._server: Optional[XtQuantServer] = None
        self._watchdog: Optional[ServerWatchdog] = None
        self._stop_event = threading.Event()
        self._server_lock = threading.Lock()

    def run(self) -> None:
        """
        主运行循环（阻塞直到 stop() 被调用或收到终止信号）。

        启动顺序：
        1. 注册信号处理器
        2. 启动 HTTP 服务
        3. 启动看门狗
        4. 注册账号
        5. 心跳循环（阻塞）
        6. 触发优雅退出
        """
        self._setup_signal_handlers()
        logger.info(
            f"XtQuantManager 独立服务启动中... "
            f"({self._config.host}:{self._config.port})"
        )
        self._start_server()
        self._start_watchdog()
        self._register_accounts()
        self._heartbeat_loop()  # 阻塞，直到 stop_event 被设置

    def stop(self) -> None:
        """触发优雅退出"""
        self._stop_event.set()

    # ------------------------------------------------------------------
    # 启动步骤
    # ------------------------------------------------------------------

    def _setup_signal_handlers(self) -> None:
        """注册 SIGINT/SIGTERM 信号处理器"""
        for sig in (signal.SIGINT, signal.SIGTERM):
            try:
                signal.signal(sig, self._on_signal)
            except (OSError, ValueError):
                # 在非主线程中注册信号会抛 ValueError，忽略
                pass

    def _on_signal(self, signum, frame) -> None:
        logger.info(f"收到信号 {signum}，开始优雅退出...")
        self.stop()

    def _build_server_config(self) -> XtQuantServerConfig:
        cfg = self._config
        return XtQuantServerConfig(
            host=cfg.host,
            port=cfg.port,
            api_token=cfg.api_token,
            allowed_ips=cfg.allowed_ips,
            rate_limit=cfg.rate_limit,
            enable_hmac=cfg.enable_hmac,
            hmac_secret=cfg.hmac_secret,
            ssl_certfile=cfg.ssl_certfile,
            ssl_keyfile=cfg.ssl_keyfile,
            health_check_interval=cfg.health_check_interval,
            reconnect_cooldown=cfg.reconnect_cooldown,
        )

    def _start_server(self) -> None:
        """创建并启动 HTTP 服务（后台线程）"""
        with self._server_lock:
            self._server = XtQuantServer(config=self._build_server_config())
            try:
                self._server.start(blocking=False)
            except Exception as e:
                logger.error(f"HTTP 服务启动失败: {e}")
                try:
                    self._server.stop(timeout=5.0)
                except Exception:
                    pass
                self._server = None
                raise
            logger.info(
                f"HTTP 服务已启动: "
                f"{'https' if self._server.config.use_tls else 'http'}://"
                f"{self._config.host}:{self._config.port}"
            )

    def _start_watchdog(self) -> None:
        """启动服务线程看门狗"""
        self._watchdog = ServerWatchdog(
            get_server=lambda: self._server,
            restart_fn=self._restart_server,
            check_interval=self._config.watchdog_interval,
            restart_cooldown=self._config.watchdog_restart_cooldown,
        )
        self._watchdog.start()

    def _restart_server(self) -> None:
        """看门狗触发：重建并重启 HTTP 服务"""
        logger.warning("Watchdog 触发服务重启...")
        with self._server_lock:
            if self._server is not None:
                try:
                    self._server.stop(timeout=5.0)
                except Exception:
                    pass
            self._server = XtQuantServer(config=self._build_server_config())
            self._server.start(blocking=False)
            logger.info(
                f"HTTP 服务已重启: "
                f"{'https' if self._server.config.use_tls else 'http'}://"
                f"{self._config.host}:{self._config.port}"
            )

    def _register_accounts(self) -> None:
        """向 XtQuantManager 注册配置文件中的所有账号"""
        manager = XtQuantManager.get_instance()
        for acfg in self._config.accounts:
            try:
                manager.register_account(AccountConfig(
                    account_id=acfg.account_id,
                    qmt_path=acfg.qmt_path,
                    account_type=acfg.account_type,
                    call_timeout=acfg.call_timeout,
                    reconnect_base_wait=acfg.reconnect_base_wait,
                    max_reconnect_attempts=acfg.max_reconnect_attempts,
                ))
                logger.info(f"账号 {acfg.account_id[:4]}*** 注册成功")
            except Exception as e:
                logger.error(f"账号 {acfg.account_id[:4]}*** 注册失败: {e}")

    # ------------------------------------------------------------------
    # 心跳循环（主阻塞逻辑）
    # ------------------------------------------------------------------

    def _heartbeat_loop(self) -> None:
        """
        每 heartbeat_interval 秒记录一次系统状态。
        每 1 秒检查一次 stop_event，保证快速响应退出。
        """
        last_heartbeat: float = 0.0
        while not self._stop_event.wait(1.0):
            now = time.time()
            if now - last_heartbeat >= self._config.heartbeat_interval:
                self._log_heartbeat()
                last_heartbeat = now

        # stop_event 已设置，触发优雅退出
        self._shutdown()

    def _log_heartbeat(self) -> None:
        """输出系统心跳日志"""
        manager = XtQuantManager.get_instance()
        account_count = len(manager.list_accounts())
        with self._server_lock:
            server_status = (
                "运行中" if self._server and self._server.is_running() else "已停止"
            )
        watchdog_restarts = (
            self._watchdog.get_status()["restart_count"]
            if self._watchdog else 0
        )
        logger.info(
            f"[心跳] XtQuantManager 运行中 | "
            f"账号: {account_count} | "
            f"HTTP服务: {server_status} | "
            f"看门狗重启次数: {watchdog_restarts}"
        )

    # ------------------------------------------------------------------
    # 优雅退出
    # ------------------------------------------------------------------

    def _shutdown(self) -> None:
        """按正确顺序停止所有组件"""
        logger.info("开始优雅退出...")

        # 1. 停止看门狗（防止误触发重启）
        if self._watchdog is not None:
            try:
                self._watchdog.stop(timeout=5.0)
            except Exception as e:
                logger.warning(f"停止看门狗时出错: {e}")

        # 2. 停止 HTTP 服务
        with self._server_lock:
            server = self._server
        if server is not None:
            try:
                server.stop(timeout=5.0)
            except Exception as e:
                logger.warning(f"停止 HTTP 服务时出错: {e}")

        # 3. 关闭所有账号
        try:
            XtQuantManager.get_instance().shutdown()
        except Exception as e:
            logger.warning(f"关闭 XtQuantManager 时出错: {e}")

        logger.info("XtQuantManager 独立服务已完全退出")


def main(argv=None) -> None:
    """命令行入口"""
    parser = argparse.ArgumentParser(
        description="XtQuantManager 独立运行服务 — 提供 xtquant RESTful API"
    )
    parser.add_argument(
        "--config", default="",
        help="配置文件路径（默认查找 xtquant_manager_config.json 或 XTQUANT_MANAGER_CONFIG 环境变量）"
    )
    parser.add_argument("--host", default="", help="监听地址（覆盖配置文件，如 0.0.0.0）")
    parser.add_argument("--port", type=int, default=0, help="监听端口（覆盖配置文件，如 8888）")
    args = parser.parse_args(argv)

    if rotate_xqm_log:
        try:
            rotate_xqm_log()
        except Exception:
            pass

    cfg = load_standalone_config(args.config)
    if args.host:
        cfg.host = args.host
    if args.port:
        cfg.port = args.port

    app = StandaloneApplication(cfg)
    app.run()


if __name__ == "__main__":
    main()
