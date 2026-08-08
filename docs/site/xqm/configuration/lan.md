# 局域网共享

交易机运行 XtQuantManager，分析机/监控机通过局域网调用。

!!! warning "安全提示"
    局域网模式务必配置 `api_token` 和 `allowed_ips`，防止未授权访问交易接口。

## 服务端配置（交易机，如 192.168.1.100）

账号配置仍保存在交易机项目根目录的 `account_config.json`：

```json
{
  "account_id": "55009640",
  "qmt_path": "C:/QMT/userdata_mini",
  "account_type": "STOCK"
}
```

网关运行参数保存在 `xtquant_manager_config.json`：

```json
{
  "host": "192.168.1.100",
  "port": 8888,
  "api_token": "your-secret-token-here",
  "allowed_ips": ["192.168.1.0/24"],
  "rate_limit": 120,
  "ssl_certfile": "certs/server.crt",
  "ssl_keyfile": "certs/server.key"
}
```

### 生成自签 TLS 证书

```bash
python xtquant_manager/utils/gen_cert.py --ip 192.168.1.100 --out certs/
```

!!! tip "不使用 HTTPS"
    若局域网为受控内网，可省略 `ssl_certfile` / `ssl_keyfile`，仅保留 Token + IP 白名单。

## 客户端配置（分析机）

```python
from xtquant_manager.client import XtQuantClient, ClientConfig

client = XtQuantClient(config=ClientConfig(
    base_url="https://192.168.1.100:8888",
    account_id="55009640",
    api_token="your-secret-token-here",
    verify_ssl=False,        # 自签证书跳过验证
    # ca_cert="certs/ca.crt" # 或指定 CA 证书验证
))

positions = client.position()
```

## curl 示例（分析机）

```bash
BASE="https://192.168.1.100:8888/api/v1"
TOKEN="your-secret-token-here"

# 跳过自签证书验证
curl -k -H "X-API-Token: $TOKEN" $BASE/health
curl -k -H "X-API-Token: $TOKEN" $BASE/accounts/55009640/positions
```
