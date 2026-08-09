# XtQuantManager API 手动测试操作文档

> 适用版本：v1.0（2026-04）
> 测试工具：`test_ui_a.html`（功能版）、`test_ui_b.html`（可视化版）

---

## 一、环境准备

### 1.1 启动 XtQuantManager 服务

```bash
# 激活虚拟环境
C:\Users\PC\Anaconda3\envs\python39\python.exe -m xtquant_manager.server_runner
```

服务默认监听 `http://127.0.0.1:8888`，启动成功后控制台输出：

```
INFO:     Uvicorn running on http://127.0.0.1:8888
```

### 1.2 打开测试界面

用浏览器（Chrome/Edge/Firefox）直接打开 HTML 文件：

| 文件 | 适用场景 |
|------|---------|
| `test_ui_a.html` | 日常接口测试、回归验证、cURL 导出 |
| `test_ui_b.html` | 可视化对比、健康监控、数据展示验证 |

### 1.3 配置测试界面

打开后在顶栏填写：

| 字段 | 默认值 | 说明 |
|------|--------|------|
| Base URL | `http://127.0.0.1:8888` | 服务地址，无需修改 |
| API Token | （空） | 若服务配置了 Token 则必填 |
| 账号 ID | （下拉） | 调用注册账号后自动同步 |

> **注意**：`/api/v1/health`（全局健康）免 Token 可直接访问，但不带 Token 时只返回 `total`/`healthy` 计数，不返回 `accounts` 明细；`/api/v1/health/{id}`（账号健康）需要 Token。

---

## 二、账号管理接口测试

### 2.1 注册账号（POST /api/v1/accounts）

**测试目标**：验证账号能否成功注册并建立连接。

**操作步骤**：

1. 左侧导航选择 **账号管理 → 注册账号**
2. 填写以下参数：

   ```
   账号 ID   : TEST_ACC_1
   账号类型  : STOCK
   QMT 路径  : C:/QMT/userdata_mini
   ```

3. 点击 **发送请求**

**预期结果**：

```json
HTTP 201 Created
{
  "account_id": "TEST_ACC_1",
  "connected": true,
  "message": "账号注册成功"
}
```

**异常场景**：

| 场景 | 操作 | 预期状态码 |
|------|------|-----------|
| 重复注册同一账号 | 不修改参数再次发送 | 409 Conflict |
| QMT 路径不存在 | 填写不存在的路径 | 200 + connected: false |
| Token 错误 | 顶栏填写错误 Token | 401 Unauthorized |

---

### 2.2 列出所有账号（GET /api/v1/accounts）

**操作步骤**：左侧选择 **列出账号** → 点击 **发送请求**

**预期结果**：

```json
{
  "accounts": [
    { "account_id": "TEST_ACC_1", "connected": true, "account_type": "STOCK" }
  ],
  "total": 1
}
```

**验证点**：accounts 数组长度与实际注册数量一致。

---

### 2.3 账号状态（GET /api/v1/accounts/{id}/status）

**操作步骤**：

1. 左侧选择 **账号状态**
2. 账号 ID 从下拉选择（或手动填写 `TEST_ACC_1`）
3. 点击 **发送请求**

**预期结果**（正常连接时）：

```json
{
  "account_id": "TEST_ACC_1",
  "connected": true,
  "xtdata_available": true,
  "xttrader_available": true,
  "last_ping_ok": "2026-04-07T09:30:00"
}
```

**验证点**：`connected`、`xtdata_available`、`xttrader_available` 三个字段均应为 `true`。

---

### 2.4 注销账号（DELETE /api/v1/accounts/{id}）

**操作步骤**：

1. 左侧选择 **注销账号**
2. 填写账号 ID → 点击 **发送请求**

**预期结果**：

```json
HTTP 200 OK
{ "message": "账号 TEST_ACC_1 已注销" }
```

**验证点**：注销后再调用 **列出账号**，该账号不再出现。

---

## 三、交易操作接口测试

> **重要**：交易接口会产生实际委托，**务必在模拟账号或沙箱环境中测试**。

### 3.1 下单（POST /api/v1/accounts/{id}/orders）

**操作步骤**：

1. 左侧选择 **下单**
2. 填写参数（可使用界面快速填充预设）：

   ```
   账号 ID    : TEST_ACC_1
   股票代码   : 000001.SZ
   方向       : BUY
   数量       : 100
   价格       : 10.50
   价格类型   : LATEST（最新价）
   ```

3. 点击 **发送请求**

**预期结果**：

```json
HTTP 201 Created
{
  "order_id": "20260407093015001",
  "stock_code": "000001.SZ",
  "direction": "BUY",
  "volume": 100,
  "price": 10.50,
  "status": "submitted"
}
```

**记录 order_id**，用于后续撤单测试。

**异常场景**：

| 场景 | 操作 | 预期 |
|------|------|------|
| 数量为负数 | volume = -100 | 422 Unprocessable Entity |
| 不合法股票代码 | stock_code = "invalid" | 400 Bad Request |
| 账号未注册 | 填写未注册的账号 ID | 404 Not Found |

---

### 3.2 查询当日委托（GET /api/v1/accounts/{id}/orders）

**操作步骤**：左侧选择 **当日委托** → 选择账号 → 发送

**预期结果**：包含刚才下单的委托记录，状态字段应为 `submitted` 或 `filled`。

---

### 3.3 撤单（DELETE /api/v1/accounts/{id}/orders/{order_id}）

**操作步骤**：

1. 左侧选择 **撤单**
2. 填写账号 ID 和刚才记录的 order_id
3. 点击 **发送请求**

**预期结果**：

```json
{ "message": "撤单请求已提交", "order_id": "20260407093015001" }
```

**验证点**：再次查询当日委托，该委托状态应变为 `cancelled`。

---

### 3.4 查询持仓（GET /api/v1/accounts/{id}/positions）

**操作步骤**：左侧选择 **查询持仓** → 选择账号 → 发送

**预期结果**（有持仓时）：

```json
{
  "positions": [
    {
      "stock_code": "000001.SZ",
      "volume": 1000,
      "available": 1000,
      "cost_price": 10.20,
      "current_price": 10.50,
      "market_value": 10500.00
    }
  ]
}
```

**验证点（Version B 可视化）**：切换到"可视化"标签页，持仓应以表格形式展示，含股票代码、数量、市值列。

---

### 3.5 查询资产（GET /api/v1/accounts/{id}/asset）

**操作步骤**：左侧选择 **查询资产** → 选择账号 → 发送

**预期结果**：

```json
{
  "total_asset": 1000000.00,
  "cash": 850000.00,
  "market_value": 150000.00,
  "frozen_cash": 0.00
}
```

**验证点（Version B）**：可视化标签显示键值卡片布局，四个核心字段清晰可读。

---

### 3.6 查询当日成交（GET /api/v1/accounts/{id}/trades）

**操作步骤**：左侧选择 **当日成交** → 选择账号 → 发送

**预期结果**：列出当日已成交的委托，含成交价、成交量。成交前此列表为空。

---

## 四、行情接口测试

### 4.1 实时行情 Tick（GET /api/v1/market/tick）

**操作步骤**：

1. 左侧选择 **实时行情**
2. 股票代码填写（支持多只，逗号分隔）：`000001.SZ,600036.SH`
3. 账号 ID：`TEST_ACC_1`
4. 点击 **发送请求**

**预期结果**：

```json
{
  "ticks": {
    "000001.SZ": {
      "last_price": 10.52,
      "bid_price": 10.51,
      "ask_price": 10.53,
      "volume": 123456789,
      "time": "093015"
    }
  }
}
```

**测试快速填充**：界面提供预设按钮，一键填充 `000001.SZ,600036.SH`。

---

### 4.2 历史行情（GET /api/v1/market/history）

**操作步骤**：

1. 左侧选择 **历史行情**
2. 填写参数：

   ```
   股票代码  : 000001.SZ
   周期      : 1d
   开始日期  : 20260101
   结束日期  : 20260407
   账号 ID   : TEST_ACC_1
   ```

3. 点击 **发送请求**

**预期结果**：返回日线数据数组，含 open/high/low/close/volume 字段。

**异常场景**：

| 场景 | 操作 | 预期 |
|------|------|------|
| 开始日期 > 结束日期 | start=20261231, end=20260101 | 400 Bad Request |
| 非法周期 | period=3x | 422 Unprocessable Entity |

---

### 4.3 下载历史数据（POST /api/v1/market/download）

**操作步骤**：

1. 左侧选择 **下载数据**
2. 填写参数：

   ```
   股票代码列表  : ["000001.SZ"]
   周期          : 1d
   开始日期      : 20260101
   结束日期      : 20260407
   ```

3. 点击 **发送请求**

**预期结果**：

```json
{ "message": "数据下载任务已提交", "stocks": ["000001.SZ"], "period": "1d" }
```

---

## 五、可观测性接口测试

### 5.1 全局健康状态（GET /api/v1/health）

**特点**：此接口**免 Token 可达**，适合作为存活探针；不带 Token 时 `accounts` 为空对象，带 Token 才返回账号明细。

**操作步骤**：左侧选择 **健康状态** → 点击发送（无需填写任何参数）

**预期结果**：

```json
{
  "status": "healthy",
  "accounts": {
    "TEST_ACC_1": { "connected": true, "last_check": "2026-04-07T09:30:00" }
  },
  "uptime_seconds": 3600
}
```

**Version B 专属**：

- 切换"可视化"标签 → 显示进度条样式健康总览和各账号状态卡片
- 点击**自动刷新**按钮（5 秒间隔）持续监控连接状态

---

### 5.2 账号健康状态（GET /api/v1/health/{id}）

**操作步骤**：左侧选择 **账号健康** → 填写账号 ID → 发送

**预期结果**：

```json
{
  "account_id": "TEST_ACC_1",
  "connected": true,
  "reconnect_attempts": 0,
  "last_ping_ok": "2026-04-07T09:30:00"
}
```

---

### 5.3 全局调用指标（GET /api/v1/metrics）

**操作步骤**：左侧选择 **全局指标** → 发送

**预期结果**：

```json
{
  "total_requests": 42,
  "success_rate": 0.976,
  "avg_latency_ms": 12.3,
  "p50_latency_ms": 8.0,
  "p95_latency_ms": 45.0
}
```

**Version B 专属**：可视化标签显示成功率进度条 + 延迟分布条（avg/P50/P95 三色对比）。

---

### 5.4 账号调用指标（GET /api/v1/metrics/{id}）

**操作步骤**：左侧选择 **账号指标** → 填写账号 ID → 发送

**验证点**：与全局指标数值对比，单账号指标不超过全局总量。

---

## 六、连接稳定性专项测试

此章节测试 **2026-04 新增的 Fail-Safe 改造**功能。

### 6.1 断开重连验证

**目标**：验证 `on_disconnected` 回调触发后，HealthMonitor 能重置冷却时间并立即重连。

**操作步骤**：

1. 调用 **账号状态** 确认 `connected: true`
2. 手动关闭 QMT 客户端（或使用测试环境的断连模拟）
3. 等待约 1 秒，再次调用 **账号健康**（`GET /health/{id}`）
4. 查看 `connected` 字段

**预期**：

- `connected: false`（< 1 秒内感知）
- HealthMonitor 日志出现：`账号 {id} 断连，重置冷却计时器`
- 重启 QMT 后，约 2-3 秒内 `connected` 恢复为 `true`

---

### 6.2 连接超时验证

**目标**：验证 `connect_timeout`（默认 30 秒）超时后不挂起进程。

**操作步骤**：

1. 注册一个 **QMT 路径存在但 QMT 未启动**的账号
2. 观察注册接口的响应时间

**预期**：

- 不超过 30 秒后返回响应
- `connected: false`，不挂起
- 无资源泄漏（可通过多次注册/注销循环验证）

---

### 6.3 重连可中断验证

**目标**：验证重连等待期间调用 disconnect() 能立即中断。

**操作步骤**：

1. 断开 QMT（触发重连等待）
2. 立即调用 **注销账号**（DELETE）
3. 观察响应时间

**预期**：注销响应时间 < 1 秒（不等待重连超时结束）。

---

## 七、界面功能说明

### Version A（test_ui_a.html）特有功能

| 功能 | 位置 | 说明 |
|------|------|------|
| 历史记录 | 右侧 History 标签 | 保存最近 50 次请求，含状态码、耗时 |
| cURL 导出 | 右侧 Raw cURL 标签 | 可复制完整 curl 命令在终端复现 |
| 健康状态圆点 | 顶栏右侧 | 绿色=健康，红色=异常，灰色=未检测 |
| 快速填充 | 下单/Tick 表单 | 预设测试参数一键填入 |

### Version B（test_ui_b.html）特有功能

| 功能 | 位置 | 说明 |
|------|------|------|
| 可视化渲染 | 右侧"可视化"标签 | 按响应类型自动选择图卡/表格/进度条 |
| 自动刷新 | 右侧面板顶部 | 5 秒轮询 `/health`，适合长期监控 |
| 搜索过滤 | 左侧导航栏顶部 | 输入关键字过滤接口名称 |
| 响应时间着色 | 右侧响应标签 | 绿(<100ms) / 黄(100-500ms) / 红(>500ms) |
| 复制 cURL | 右侧面板按钮 | 一键复制，带动效反馈 |

---

## 八、常见问题排查

### Q1：发送请求后提示"Network Error"

- 确认服务已启动（`http://127.0.0.1:8888`）
- 检查 Base URL 是否填写正确
- 检查是否有防火墙拦截

### Q2：所有接口返回 401

- 服务启动时配置了 `api_token`，需在顶栏 **API Token** 字段填写相同值
- `GET /api/v1/health` 免 Token 可用于验证服务是否存活（不带 Token 时不返回 `accounts` 明细）；`GET /api/v1/health/{id}` 及其余端点均需 Token

### Q3：注册账号返回 connected: false

- QMT 客户端是否已启动并登录
- `qmt_path` 是否指向正确的 `userdata_mini` 目录
- 查看服务端日志获取详细错误信息

### Q4：账号下拉为空

- 先调用 **注册账号** 或 **列出账号** 接口，下拉会自动同步
- Version A：顶栏账号下拉在成功调用列出账号后刷新
- Version B：侧边栏账号 ID 输入框支持手动输入

### Q5：Version B 可视化标签显示"无可视化数据"

- 部分接口响应格式不在可视化渲染范围内（如 download、cancel）
- 切换到 Response 标签查看原始 JSON

---

## 九、测试检查清单

### 冒烟测试（约 5 分钟）

- [ ] 服务启动，访问 `/health` 返回 200
- [ ] 注册账号成功（201），`connected: true`
- [ ] 列出账号，数量正确
- [ ] 查询资产，返回合法数值
- [ ] 查询持仓，格式正确

### 完整回归测试

- [ ] 账号管理全部 4 个接口（注册/注销/列表/状态）
- [ ] 交易操作全部 6 个接口（下单/撤单/持仓/资产/委托/成交）
- [ ] 行情接口全部 3 个接口（tick/历史/下载）
- [ ] 可观测性全部 4 个接口（health/health-id/metrics/metrics-id）
- [ ] 异常场景：401/404/409/422 各至少触发一次
- [ ] 连接稳定性：断连感知 < 1 秒
- [ ] 重连可中断：disconnect() 响应 < 1 秒

---

*文档生成日期：2026-04-07*
