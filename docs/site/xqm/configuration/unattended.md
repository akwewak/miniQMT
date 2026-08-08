# 无人值守

配合看门狗和健康监控，在断线、崩溃时自动恢复，适合长期无人值守运行。

## 推荐配置

账号配置（`account_config.json`）：

```json
{
  "accounts": [
    {
      "account_id": "55009640",
      "qmt_path": "C:/QMT/userdata_mini",
      "reconnect_base_wait": 60.0,
      "max_reconnect_attempts": 5
    }
  ]
}
```

网关运行配置（`xtquant_manager_config.json`）：

```json
{
  "host": "127.0.0.1",
  "port": 8888,
  "health_check_interval": 30.0,
  "reconnect_cooldown": 60.0,
  "watchdog_interval": 10.0,
  "watchdog_restart_cooldown": 30.0,
  "heartbeat_interval": 1800.0
}
```

## 关键参数说明

| 参数 | 默认值 | 作用 |
|------|--------|------|
| `health_check_interval` | `30.0` | HealthMonitor 轮询间隔（秒） |
| `reconnect_cooldown` | `60.0` | 两次重连之间的最小冷却时间，防止重连风暴 |
| `watchdog_interval` | `10.0` | 服务线程存活检查间隔，崩溃后 10s 内重启 |
| `watchdog_restart_cooldown` | `30.0` | 看门狗重启冷却时间 |
| `heartbeat_interval` | `1800.0` | 心跳日志间隔（30 分钟输出一次运行状态） |
| `reconnect_base_wait` | `60.0` | 指数退避起点（第 1 次 60s，第 2 次 120s…） |
| `max_reconnect_attempts` | `5` | 超过此次数后停止指数退避，等待手动干预 |

## 断线感知三条路径（互补）

| 路径 | 感知延迟 | 机制 |
|------|---------|------|
| 事件驱动 | < 1 秒 | `on_disconnected` 回调 → 立即标记 `connected=False` |
| 累计失败 | ~ 15 秒 | 连续 3 次 API 失败 → 触发重连 |
| 主动探测 | 最长 30 秒 | HealthMonitor ping → 三级检查 |

## 使用管理脚本运行

```bat
# 启动服务（后台窗口最小化）
xtquant_manager\xqm_manager.bat start

# 实时追踪日志
xtquant_manager\xqm_manager.bat logs

# 查看服务状态 + 最近 10 行日志
xtquant_manager\xqm_manager.bat status
```

详见[服务管理脚本](../service-management.md)。

!!! tip "开机自启"
    将 `xqm_manager.bat start` 加入 Windows 任务计划程序（开机触发），实现开机自启。
