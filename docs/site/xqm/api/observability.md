# 可观测性

全局健康检查免 Token 可达（存活探针），但**无 Token 时不返回账号明细**；
单账号健康检查与指标接口均需要 Token。

## 全局健康检查

```http
GET /api/v1/health
```

适合作为存活探针、监控系统轮询端点。

**响应（携带有效 Token）：**

```json
{
  "success": true,
  "data": {
    "accounts": {
      "55009640": {
        "connected": true,
        "reconnecting": false,
        "reconnect_attempts": 0,
        "last_ping_ok_time": 1775550307.58
      },
      "55009641": {
        "connected": true,
        "reconnecting": false,
        "reconnect_attempts": 0,
        "last_ping_ok_time": 1775550307.58
      }
    },
    "total": 2,
    "healthy": 2
  }
}
```

**响应（未携带 Token）：** 仍返回 200，但 `accounts` 为空对象——
账号 ID 是访问其他账号数据的入口，属敏感信息。存活探针只需 `total`/`healthy`。

```json
{
  "success": true,
  "data": {
    "accounts": {},
    "total": 2,
    "healthy": 2
  }
}
```

---

## 单账号健康检查

```http
GET /api/v1/health/{account_id}
```

需要 `X-API-Token` 请求头。

**响应：**

```json
{
  "success": true,
  "data": {
    "account_id": "55009640",
    "connected": true,
    "reconnecting": false,
    "reconnect_attempts": 0,
    "last_ping_ok_time": 1775550307.58,
    "connected_at": 1775550000.0,
    "xtdata_available": true,
    "xttrader_available": true
  }
}
```

---

## 全局调用指标

```http
GET /api/v1/metrics
X-API-Token: <token>
```

**响应：**

```json
{
  "success": true,
  "data": {
    "55009640": {
      "total_calls": 42,
      "success_calls": 42,
      "error_calls": 0,
      "timeout_calls": 0,
      "error_rate": 0.0,
      "avg_latency_ms": 4.0,
      "p50_latency_ms": 3.0,
      "p95_latency_ms": 16.0,
      "uptime_seconds": 3600.0,
      "ops": {
        "query_positions": {"total": 20, "success": 20, "error": 0, "timeout": 0},
        "query_asset":     {"total": 10, "success": 10, "error": 0, "timeout": 0},
        "order_stock":     {"total": 5,  "success": 5,  "error": 0, "timeout": 0},
        "get_full_tick":   {"total": 7,  "success": 7,  "error": 0, "timeout": 0}
      }
    }
  }
}
```

**指标说明：**

| 字段 | 说明 |
|------|------|
| `total_calls` | 累计调用次数 |
| `error_rate` | 最近 100 次的错误率 |
| `avg_latency_ms` | 最近 1000 次的平均延迟（毫秒） |
| `p50_latency_ms` | P50 延迟 |
| `p95_latency_ms` | P95 延迟 |
| `timeout_calls` | 超时次数 |
| `ops` | 按操作类型分组统计 |

---

## 单账号调用指标

```http
GET /api/v1/metrics/{account_id}
X-API-Token: <token>
```

返回格式与全局指标中单账号条目相同。
