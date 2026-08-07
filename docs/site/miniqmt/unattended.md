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

### 超时线程无法回收（可观测，非可修复）  [v3.8.6]

`run_with_timeout()` 超时后**无法真正终止底层线程**：`future.cancel()` 只能取消尚未开始的任务，`cancel_futures` 也不中断运行中的线程，而 Python 没有强制杀死线程的机制。若 QMT 长期无响应，每次超时都会泄漏一个线程，无人值守长跑会持续累积。

这一点不作「已修复」的假象处理，改为让它**可观测**：

```python
from timeout_utils import get_leaked_call_count
get_leaked_call_count()    # 累计泄漏的超时调用数
```

泄漏首次发生以及此后每 10 次会输出一条 `[TIMEOUT_LEAK]` WARNING。**若该数值持续增长，说明底层（通常是 QMT）调用长期卡死，需人工检查 QMT 客户端状态**——它是排查「系统看似在跑但数据不更新」的关键信号。

### 重连瞬间的状态一致性  [v3.8.6]

重连要销毁旧 `XtQuantTrader` 再建新实例，这几百毫秒是状态最易错乱的窗口，有三处收口：

- **旧 callback 失效**：`connect()` 每次都创建全新 callback，但旧 trader 仍持有旧 callback。若 `stop()` 超时（daemon 线程杀不掉），旧 trader 连同回调继续存活，其延迟触发的 `on_disconnected` 会把新连接刚设好的 `qmt_connected` 错误置回 `False` 并清零重连冷却，引发本可避免的 stop/connect 周期（每次都有再卡死的风险，可级联）。故在 **stop 之前**调用 `callback.detach()` 尽早关窗。
    - 刻意**只切连接状态类推送**（`on_disconnected` / `on_stock_order`），保留 `on_stock_trade` 转发：成交回报是真实资金变动，迟到仍有价值，且落库层按 `trade_id` 幂等去重，一并拦掉反而可能永久丢失一笔成交流水。
- **重连后强制刷新持仓**：成功分支置零 `last_position_update_time`，否则最长 `QMT_POSITION_QUERY_INTERVAL`（10 秒）内继续用断连前的持仓快照；断连期间若有外部成交，止盈止损会基于错误持仓判断。
- **QMT 自恢复探测**：QMT 进程自动重启后 `position()` 已能返回真实数据，但 `qmt_connected` 仍为 `False`。`_probe_qmt_recovered()` 用 `ping_xttrader()`（真实 `query_stock_asset` 探针）确认后直接自恢复，省去一次冗余重连。**不以「持仓查询返回空」为依据**——`position()` 断连时同样返回空 DataFrame，与「真的没有持仓」无法区分，据此自恢复会造成假健康。重连进行中 / 模拟模式 / 网关模式一律不探测。

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
