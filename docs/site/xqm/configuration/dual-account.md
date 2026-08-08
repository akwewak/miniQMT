# 双账号（多策略隔离）

两个 QMT 账号同时运行，每账号拥有独立的连接、指标和健康监控，互不干扰。

## 前提条件

- 两个 QMT 客户端实例分别登录不同账号
- 两个账号的 `userdata_mini` 目录**必须不同**（通常位于不同安装路径下）

## 账号配置（account_config.json）

```json
{
  "accounts": [
    {
      "account_id": "55009640",
      "qmt_path": "C:/QMT/userdata_mini",
      "account_type": "STOCK",
      "call_timeout": 3.0
    },
    {
      "account_id": "55009641",
      "qmt_path": "C:/QMT1/userdata_mini",
      "account_type": "STOCK",
      "call_timeout": 3.0
    }
  ]
}
```

## 网关配置（xtquant_manager_config.json）

```json
{
  "host": "127.0.0.1",
  "port": 8888,
  "api_token": "",
  "health_check_interval": 30.0,
  "reconnect_cooldown": 60.0
}
```

## 验证

```bash
# 确认两个账号均已注册并连接
curl http://127.0.0.1:8888/api/v1/accounts
# {"success":true,"data":{"accounts":["55009640","55009641"]}}

curl http://127.0.0.1:8888/api/v1/health
# {"data":{"total":2,"healthy":2,...}}
```

## 注意事项

| 要点 | 说明 |
|------|------|
| QMT 路径必须不同 | 每个账号需要独立的 `userdata_mini` 目录 |
| QMT 客户端独立登录 | 两个账号需要两个 QMT 进程分别登录 |
| `session_id` 自动分配 | 无需手动指定，Manager 自动管理避免冲突 |
| 账号 ID 大小写敏感 | `55009640` 和 `55009640 `（含空格）视为不同账号 |
| 连接失败不阻止注册 | `connected: false` 时 HealthMonitor 会持续重试 |
| 独立指标统计 | `GET /metrics/{id}` 每账号独立，互不干扰 |

更多多账号 Python 示例见[多账号实战](../guides/multi-account.md)。
