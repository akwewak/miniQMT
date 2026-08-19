# 安全配置

## 本机开发（无认证）

```json
{"host": "127.0.0.1", "port": 8888, "api_token": ""}
```

`api_token` 为空时，仅**本机**（TCP 对端为 `127.0.0.1`/`::1`）可免 Token 访问；
非本机访问一律拒绝。绑定 `0.0.0.0` 对外提供服务时**必须**配置 Token。

### Token 来源优先级

v3.8.9 起，独立网关启动时按以下顺序解析 Token：

```text
XQM_API_TOKEN > QMT_API_TOKEN > xtquant_manager_config.json/api_token
```

推荐做法：

- web1.0 与网关共用凭证：只设置 `QMT_API_TOKEN`
- 网关使用独立凭证：同时设置 `QMT_API_TOKEN` 与 `XQM_API_TOKEN`，以后者作为网关 Token
- 避免在 `xtquant_manager_config.json` 写真实 Token；JSON 中的 `api_token` 只作为本地兜底

`/api/v1/health` 免 Token 可达，可直接用作存活探针，但未携带有效 Token 时
只返回 `total` / `healthy` 计数，`accounts` 为空对象 `{}`（账号 ID 属敏感信息，
是遍历其他账号数据的入口）。带 Token 才返回完整账号明细。
`/api/v1/health/{id}` 需要 Token。

---

## 端点鉴权一览

除下表所列例外，**所有** `/api/v1/*` 与 `/api/*`（Flask 兼容）端点均需
`X-API-Token` 请求头。

| 端点 | 是否需要 Token | 说明 |
|------|:--------------:|------|
| `/api/v1/health` | 否（降级返回） | 存活探针；无 Token 时不返回 `accounts` 明细 |
| `/` 及静态资源 | 否 | web2.0 前端托管 |
| 其余全部端点 | **是** | 含持仓、成交、资产、配置、网格账本、止盈止损开关 |

只读端点同样需要 Token：`/api/positions`、`/api/trade-records`、
`/api/grid/ledger/{id}` 等会返回持仓成本、盈亏与成交明细，属财务隐私数据。

> 早期版本为便于"互联网只读访问"而放开了这批兼容端点，等同于将财务数据公开，
> 现已全部收归 Token 保护。web2.0 前端已内置 Token 通路，用户在「连接设置」
> 中填入 Token 即可，无需改代码。

---

## 反向代理与 X-Forwarded-For

`X-Forwarded-For` 由客户端完全可控，而来源 IP 会用于「本机免 Token 放行」、
IP 白名单与速率限制三处判定。因此网关**默认不信任**该请求头
（`trust_proxy: false`）——否则攻击者只需发送 `X-Forwarded-For: 127.0.0.1`
即可冒充本机，一次绕过全部三道防线。

仅当网关确实部署在受信任的反向代理（Nginx / Caddy / Cloudflare Tunnel）之后，
且该代理会覆写此头时，才可开启：

```json
{"trust_proxy": true}
```

⚠️ 开启后务必确保网关端口不能被绕过代理直接访问，否则等同于关闭认证。

---

## 局域网（Token + IP 白名单）

```json
{
  "host": "192.168.1.100",
  "port": 8888,
  "api_token": "at-least-32-char-random-string",
  "allowed_ips": ["192.168.1.0/24"],
  "rate_limit": 120
}
```

生成随机 Token：

```bash
python -c "import secrets; print(secrets.token_hex(32))"
```

---

## HTTPS（自签证书）

```bash
# 生成证书（包含 SAN for IP）
python xtquant_manager/utils/gen_cert.py --ip 192.168.1.100 --out certs/
```

```json
{
  "ssl_certfile": "certs/server.crt",
  "ssl_keyfile":  "certs/server.key"
}
```

客户端跳过证书验证（自签证书）：

```python
client = XtQuantClient(config=ClientConfig(
    base_url="https://192.168.1.100:8888",
    verify_ssl=False,
))
```

---

## HMAC 签名（公网/高安全）

```json
{"enable_hmac": true, "hmac_secret": "very-long-random-secret"}
```

Python 客户端生成签名请求头：

```python
from xtquant_manager.security import generate_hmac_headers

headers = generate_hmac_headers(
    method="GET",
    path="/api/v1/health",
    secret="very-long-random-secret",
)
```

---

## 安全级别对比

| 场景 | Token | IP 白名单 | HTTPS | HMAC | trust_proxy |
|------|:-----:|:--------:|:-----:|:----:|:-----------:|
| 本机开发 | — | — | — | — | ✗ |
| 局域网（受控内网） | ✓ | ✓ | — | — | ✗ |
| 局域网（严格） | ✓ | ✓ | ✓ | — | ✗ |
| 公网（经受信反代） | ✓ | ✓ | ✓ | ✓ | ✓ |

`trust_proxy` 列的 ✗ 表示保持默认 `false`；仅在网关位于受信任反向代理之后
且端口无法被绕过直连时才置 `true`。

---

## 隐私安全最佳实践

### 不硬编码凭证

所有 Token、密码、账号 ID 一律使用环境变量或配置文件，绝不写入源代码：

```python
# ✅ 正确：环境变量
token = os.environ.get("PUSHPLUS_TOKEN", "")

# ❌ 错误：硬编码
token = "65a7ae6c776c4881899e36aace47d491"
```

### 敏感文件保护

| 文件 | 保护方式 |
|------|---------|
| `account_config.json` | `.gitignore` 已排除，不提交到 Git |
| `xtquant_manager_config.json` | 包含 `api_token`，`.gitignore` 已排除，不提交到 Git |
| `web2.0/dist/` | 构建产物含编译后的前端代码，已加入 `.gitignore` |
| `web2.0/node_modules/` | 第三方依赖，已加入 `.gitignore` |

### 构建产物隐私

`web2.0/dist/` 中的 JavaScript bundle 会内联所有 `VITE_*` 环境变量。
不要将真实 Token 写入 `.env.production` 中提交。
改为在 UI 连接设置面板中运行时配置（保存到 localStorage）。

### 文档示例

文档中的示例账号 ID 统一使用虚构 ID（如 `55009640`），不使用真实账号。
