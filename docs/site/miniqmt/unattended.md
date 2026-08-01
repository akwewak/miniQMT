# 无人值守运行

## 概述

miniQMT 支持长期持续运行，通过线程健康监控实现自动恢复，配合超时保护和非交易时段优化，适合 7x24 小时无人值守部署。

---

## 线程自愈机制

`ThreadHealthMonitor`（[thread_monitor.py](https://github.com/weihong-su/miniQMT/blob/main/thread_monitor.py)）每 60 秒检查所有注册线程的存活状态。

**工作流程**：

```
每 60 秒:
  遍历所有注册线程:
    获取线程对象（通过 lambda）
    如果线程不存活:
      记录日志
      调用 restart_func()
      记录重启历史
      进入 60 秒冷却期
```

### 线程注册规范

```python
# main.py 中的正确注册方式
thread_monitor = get_thread_monitor()

thread_monitor.register_thread(
    "持仓监控",
    lambda: position_manager.monitor_thread,  # lambda 获取最新引用
    position_manager.start_position_monitor_thread,
)
```

!!! danger "常见错误"
    ```python
    # 错误: 直接传递线程对象，重启后引用失效
    monitor.register_thread(
        "持仓监控",
        position_manager.monitor_thread,  # ❌ 错误
        restart_func,
    )
    ```

---

## 超时保护

持仓监控线程中的 API 调用有超时保护（当前默认 8 秒）：

```python
try:
    future.result(timeout=config.MONITOR_CALL_TIMEOUT)  # 默认 8 秒
except TimeoutError:
    logger.warning("API 调用超时，跳过本次更新")
```

超时不阻塞主循环，下一次循环继续尝试。

### xttrader 连接与清理超时

重连路径上的 QMT 底层调用同样有超时兜底。`easy_qmt_trader._stop_trader_with_timeout()` 把 `xt_trader.stop()` 放进 daemon 线程执行，超过 `QMT_STOP_TIMEOUT`（默认 5 秒）就放弃等待并继续重连：

```python
stop_thread = threading.Thread(target=_do_stop, daemon=True, name='qmt_stop_worker')
stop_thread.start()
stop_thread.join(timeout)          # config.QMT_STOP_TIMEOUT
if stop_thread.is_alive():
    logger.warning(f'停止{label}超时({timeout}秒)，跳过等待并继续重连')
```

`connect()` 的四条清理路径（清理旧实例、连接超时、连接异常、连接失败）全部走这个统一入口。**背景**：QMT 在处理外部成交回报时，`stop()` 可能与底层回调线程互相等待而永久阻塞，此前会把整个重连线程拖死，Fail-Safe 自愈随之失效。

连接本身由 `QMT_CONNECT_TIMEOUT`（默认 30 秒）保护，超时后中止本次连接并清理残留实例，避免遗留后台线程。

---

## 非交易时段优化

```python
if not config.is_trade_time():
    time.sleep(60)  # 非交易时段每分钟检查一次
    continue
```

**效果**：非交易时段 CPU 占用从 ~30% 降至 <2%。

---

## 心跳日志

每 30 分钟输出一次系统运行状态（`ENABLE_HEARTBEAT_LOG = True`），包含：

- 各线程存活状态
- 持仓数量和总市值
- 最近的交易活动
- QMT 连接状态

---

## 盘前自动初始化

每日 9:25 自动重新初始化 xtquant 连接（`ENABLE_PREMARKET_XTQUANT_REINIT = True`），确保交易日开盘前连接就绪。

---

## 数据库维护与日志轮转

主程序启动时会根据 `ENABLE_DB_MAINTENANCE` 启动数据库维护线程。默认每天 `00:10:00` 附近执行一次，且 `DB_MAINTENANCE_REQUIRE_NON_TRADE_TIME = True` 时只在非交易时段运行，避免盘中对 SQLite 做重维护。

维护内容：

- 清理 `trade_records`、非 active 的 `grid_trading_sessions`、`premarket_sync_history`、`config_history` 等追加型历史表
- 清理自动买入复盘库 `data/autobuy.db` 中过期的 `decision_log`
- 删除行数达到 `DB_MAINTENANCE_VACUUM_MIN_DELETED_ROWS` 且 `DB_MAINTENANCE_ENABLE_VACUUM = True` 时执行 `VACUUM`
- 按 `XQM_LOG_MAX_SIZE` / `XQM_LOG_BACKUP_COUNT` 轮转 `logs/xqm_manager.log`

保留策略集中在 `config.py`：

```python
TRADE_RECORD_RETENTION_DAYS = 1095
GRID_SESSION_RETENTION_DAYS = 365
AUTOBUY_DECISION_LOG_RETENTION_DAYS = 90
PREMARKET_HISTORY_RETENTION_DAYS = 365
CONFIG_HISTORY_RETENTION_DAYS = 365
```

如需临时手动执行，可在确认非交易时段后运行：

```python
from maintenance import run_database_maintenance, rotate_xqm_log

rotate_xqm_log()
run_database_maintenance()
```

---

## 5 分钟启用清单

```python
# config.py 必改项
ENABLE_THREAD_MONITOR = True     # 线程自愈（默认已开）
ENABLE_SELL_MONITOR = True       # 卖出超时撤单（默认已开）
ENABLE_HEARTBEAT_LOG = True      # 心跳日志（默认已开）
ENABLE_DB_MAINTENANCE = True     # 数据库维护与 XtQuantManager 日志轮转（默认已开）
```

```bash
# 启动
python main.py

# 查看日志
Get-Content logs/qmt_trading.log -Wait   # PowerShell
tail -f logs/qmt_trading.log             # Git Bash
```

---

## 诊断工具

```bash
# 系统状态检查
python -m unittest test.test_system_integration -v

# QMT 连接诊断
python -m unittest test.test_qmt_connection -v
```
