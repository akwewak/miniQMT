# Web 前端（web1.0 / web2.0）

miniQMT 提供**两套**Web 界面，职责明确分工：

- **web1.0** — 完整操作台（读 + 写），仅绑本机
- **web2.0** — **纯只读监控端**（monitor），可远程访问

!!! warning "web2.0 是只读监控端"
    自 2026-08-01 起，web2.0 **不再提供任何写操作**：下单、配置保存、网格启停、
    个股开关、初始化持仓等入口全部移除，前端 HTTP 适配层也只导出 `apiGet`
    （`web2.0/src/api/adapter.ts`），从源头杜绝误触发。
    所有写操作请使用 web1.0。该约束由单元测试 `src/api/readonly.test.ts` 持续守护。

---

## 双端职责对比

| 维度 | web1.0（操作台） | web2.0（只读监控端） |
|------|-----------------|---------------------|
| 前端栈 | Flask 模板渲染 (`web1.0/`) | Vue3 + Vite + TypeScript + Tailwind + Pinia (`web2.0/`) |
| 定位 | 读 + 写，完整功能 | **只读**，展示与告警 |
| 后端 | 每账号独立 Flask 进程 (`web_server.py`) | Flask 直连 **或** xtquant_manager 网关 |
| 默认端口 | `:5000`、`:5001`、… | 直连沿用 Flask 端口；网关 `:8888` |
| 绑定地址 | `127.0.0.1` — **只绑本机** | 网关模式 `0.0.0.0`，可远程 |
| 实时推送 | ✅ SSE | 直连 ✅ SSE；网关 ❌（轮询兜底，不影响数据更新） |
| PWA 离线 | ❌ | ✅ 可安装到桌面 |
| 多账号切换 | ❌（每实例一个账号） | ✅ |

---

## web2.0 能力清单（全部只读）

| 能力 | Flask 直连 | 网关模式 | 说明 |
|------|-----------|---------|------|
| 持仓列表（16 列） | ✅ | ✅ | 含基准成本、浮盈金额、个股止盈状态 |
| **委托队列（在途优先）** | ✅ | ✅ | `/api/orders`，感知"已报未成交"挂单 |
| 成交记录（按天分组 + 筛选） | ✅ | ✅ | 支持代码/名称、买卖方向、策略筛选 |
| 账户资产 / QMT 连接状态 | ✅ | ✅ | 连接状态持续轮询（15s） |
| 网格会话列表 | ✅ | ✅ | 状态、盈亏、自动/暂停（只读徽章） |
| **网格真实账本** | ✅ | ✅ | 批次 / FIFO 配对 / 汇总；网关侧为只读 SQL |
| 网格悬停速览卡 | ✅ | ✅ | 悬停不发请求，复用已加载会话数据 |
| 参数展示 | ✅ | ✅ | 只读；读不到显示 `--`，不用默认值冒充 |
| 运行开关状态（含三级开关总览） | ✅ | ✅ 反向探测 Flask | 探测不到时标为「未知」，见下方「三态状态」 |
| MACD 建议 + 迷你 K 线 | ✅ | ✅ | 悬停弹出 |
| 数据新鲜度指示 | ✅ | ✅ | 见下方「数据新鲜度」 |
| 🔒 任何写操作 | ❌ | ❌ | 一律使用 web1.0 |

### 三态状态（开 / 关 / 未知）

顶栏的运行开关是**只读徽章**，有三种状态：

| 状态 | 含义 |
|------|------|
| 开 / 关 | 后端返回的真实值 |
| **未知** | 后端未提供该状态 |

大部分开关持久化在账号 SQLite 的 `system_config` 表里，网关直接读即可。
但 `ENABLE_AUTO_OPERATION`（全局总闸）和 `ENABLE_SIMULATION_MODE` 按设计**不持久化**
（见 `config_manager.apply_configs_to_runtime` 的注释：总闸每次启动需手动确认），
只存在于主进程内存中。

**网关通过反向探测获取它们**：收到 `/api/status` 时调用该账号 Flask 的
`/api/status`（端口 = `5000 + 账号在 account_config.json 中的索引`，
带 5 秒缓存、1 秒超时），拿到真实的内存态开关。

为此，**web2.0 启动模式下 Flask 仍会启动**（只绑 `127.0.0.1`，不对外暴露）：
launcher 先探测该账号的 Flask 端口，空闲则启动、已被占用则跳过（设 `QMT_NO_FLASK=1`）
避免端口冲突。

| 场景 | 总闸显示 |
|------|---------|
| Flask 直连模式 | ✅ 真实值 |
| 网关模式（web1.0 或 web2.0 方式启动主程序） | ✅ 真实值（反向探测成功） |
| 手动设 `QMT_NO_FLASK=1` 启动 | ⚠️ 未知 |
| 账号不在 `account_config.json` 中 | ⚠️ 未知 |

!!! danger "为什么宁可显示「未知」也不猜"
    网关早期实现把这些开关**硬编码为 `True`**，导致监控界面无论后端实际状态如何
    都显示「自动ON」；`/api/config` 同样返回一组写死的默认值（35000/5.0/7.0…）。
    同理，账号不在配置列表时网关**不会**回落到默认端口 5000 —— 那会读到
    另一个账号的状态并张冠李戴。监控端显示假状态比不显示更危险。
    回归用例见 `test/test_xqm_monitor_endpoints.py`
    的 `TestStatusNoFakeState` 与 `TestFlaskReverseProbe`。

### 三级开关总览

自动止盈止损和网格交易各有一条**三级门控链**，任何一级关闭则该策略不产生新单。
web2.0 用「三级开关总览」面板（`TierSwitches.vue`，位于参数面板下方）一屏呈现整条链路，
省去逐项排查：

| 策略 | 第 1 级（全局总闸） | 第 2 级（策略开关） | 第 3 级（个体开关） |
|------|--------------------|--------------------|--------------------|
| 动态止盈止损 | `ENABLE_AUTO_OPERATION` | `ENABLE_AUTO_TRADING` | `positions.stop_profit_enabled`（**个股级**） |
| 网格交易 | `ENABLE_AUTO_OPERATION` | `ENABLE_GRID_TRADING` | `grid_trading_sessions.enabled`（**会话级**） |

面板呈现方式：

- 前两级用 ✔ / ✘ / ? 徽章（绿 / 红 / 灰），`?` 即上文的「未知」态
- 第 3 级因为是逐个体的，用聚合计数展示：
    - 动态止盈止损：`已开启 / 持仓总数`
    - 网格交易：`启用 / 暂停 / 会话总数`
- 逐个体的明细在各自列表里查看：持仓列表末列「自动止盈」列、网格会话列表的「自动/暂停」徽章

!!! note "第 3 级只读，切换请用 web1.0"
    个股止盈开关（`POST /api/holdings/stop_profit`）和网格会话开关
    （`POST /api/grid/session/<id>/enabled`）都是写操作，web2.0 只展示状态。

`ENABLE_DYNAMIC_STOP_PROFIT` 是更底层的**模块开关**（控制信号是否被检测），
仅存在于 `config.py`，web1.0 和 web2.0 都无对应 UI 控件。

### 数据新鲜度

监控界面最危险的失效方式不是"没数据"，而是"显示着 10 分钟前的数据却看不出来"。
因此每个数据块都标注自身年龄，并按阈值降级：

| 状态 | 阈值 | 表现 |
|------|------|------|
| 新鲜 | < 30s | 灰色时间标注 |
| 陈旧 | ≥ 30s | 琥珀色 |
| 失联 | ≥ 90s | 红色 + 顶部横幅告警 |

实现见 `web2.0/src/utils/freshness.ts`。

### 轮询节奏

轮询**不因任何业务开关而停止**（旧版「停止自动操作」会连带停掉数据刷新），
只随页面可见性调整频率：前台 3s 基准，后台切换到 15s，回到前台立即补一次全量刷新。

| 数据 | 前台周期 |
|------|---------|
| 系统状态 | 9s |
| **QMT 连接状态** | 15s |
| 委托队列 | 15s |
| 成交记录 | 18s |
| 持仓 + 网格会话 | 30s（SSE 可用时主要靠推送） |

!!! note "QMT 连接状态必须轮询"
    旧版只在页面初始化时查一次连接状态，QMT 掉线后顶栏指示灯会永远停在
    「QMT·OK」—— 对监控盘这是最不能坏的指示灯。

---

## 盈亏率口径

单只持仓的 `profit_ratio` 后端已乘 100（百分比数），而汇总指标是**小数**，
且两个后端键名还不一致：

| 后端 | 汇总键名 | 单位 |
|------|---------|------|
| Flask (`utils.calculate_position_metrics`) | `profit_ratio` | 小数 |
| 网关 (`server.flask_positions`) | `total_profit_ratio` | 小数 |

前端在 `web2.0/src/utils/metrics.ts` 的 `normalizeMetrics()` 统一收口：
兼容两个键名并 ×100，出口一律是百分比数。

!!! warning "历史缺陷"
    旧版直接把小数当百分比展示，5.23% 显示成 **0.05%**；Flask 直连模式下
    因键名不匹配更是恒显示 **0.00%**。回归用例见 `src/utils/metrics.test.ts`。

---

## 页面标题与发布版本

web1.0 和 web2.0 的页面标题都使用 `%MINIQMT_RELEASE_VERSION%` 占位符，真实发布版本统一来自项目根目录的 `release_version.json`。

- web1.0：`web_server.py` 在返回 `web1.0/index.html` 时注入版本号，同时给 `script.js` 添加基于 mtime 的缓存破坏参数
- web2.0：`web2.0/vite.config.ts` 在 Vite 构建阶段注入版本号，更新 `release_version.json` 后需要重新执行 `npm run build`

`web2.0/package.json` 中的 `version` 仅表示前端包自身元数据，不作为 miniQMT 发布版本来源。

---

## 顶部控制条

Flask 直连模式下，顶部控制条包含以下控件（部分仅后端存在，前端由配置表单统一渲染）：

| 控件 | 后端字段/配置 | 作用 |
|------|---------------|------|
| 开始/停止自动操作按钮 | `ENABLE_AUTO_OPERATION`（API 兼容字段 `isMonitoring`） | 全局自动操作总开关，只运行时生效不持久化；关闭时动态止盈止损和网格交易都不再产生新单 |
| 模拟交易模式 | `ENABLE_SIMULATION_MODE` | 切换实盘/模拟模式 |
| 允许自动止盈 | `ENABLE_AUTO_TRADING`（保存配置字段 `globalAllowBuySell`） | 动态止盈止损自动执行开关，持久化 |
| 允许自动网格 | `ENABLE_GRID_TRADING`（保存配置字段 `globalAllowGridTrading`） | 网格模块自动执行开关，持久化 |
| 买 / 卖 | `ENABLE_ALLOW_BUY` / `ENABLE_ALLOW_SELL` | 手动和自动交易的方向权限 |
| 动态止盈（后端配置开关） | `ENABLE_DYNAMIC_STOP_PROFIT` | 控制动态止盈止损模块是否检测信号（此开关仅在后端 config.py 中存在，web1.0 前端无对应 UI 控件；如需切换请直接编辑配置文件） |
| 网格自动/暂停 | `grid_trading_sessions.enabled` | 单只股票网格会话开关，位于**网格配置对话框内**（非顶部控制条），暂停后保留会话但不发新网格单 |
| 自动止盈（持仓列表末列） | `positions.stop_profit_enabled` | **个股级**动态止盈止损拨动开关，暂停后该股不再检测止盈止损信号，持久化 |

!!! note "为什么 API 仍叫 isMonitoring"
    早期前端使用 `isMonitoring` 表示顶部开关状态。为兼容旧接口，字段名保留不变，但当前语义已经是全局自动操作总开关；持仓监控线程状态请看 `positionMonitorRunning`。

Web1.0 参数区中，`API Token` 与"模拟交易模式""允许自动止盈""允许自动网格"位于同一行；Token 值由前端 `localStorage` 持久化，通过 `X-API-Token` 请求头发送，后端与 `QMT_API_TOKEN` 环境变量比对验证。

Web2.0 顶部不再有任何控制控件：原先的 7 个开关/按钮已全部替换为**只读状态徽章**
（开 / 关 / 未知三态），切换请到 web1.0 完成。

### 持仓列表（web1.0）

**列定义**（共 16 列）：网格 / 代码 / 名称 / 涨幅 / 价格 / 成本 / 盈亏 / 市值 / 可用 / 总数 / 浮盈 / 冲高 / 止损 / 建仓 / 基准 / 自动止盈。

首列「网格」为网格配置入口（点击打开网格配置对话框，非勾选框语义），列头已从旧版全选 checkbox 改为「网格」文本并居中。末列「自动止盈」为个股级动态止盈止损拨动开关：

- 开关状态来自 `positions.stop_profit_enabled`，切换即调用 `POST /api/holdings/stop_profit` 并持久化到 SQLite
- 关闭后该股不再检测止盈止损信号（不影响其网格会话，也不影响其他股票）
- 切换失败时开关自动回滚到原状态并提示

**字段释义**：
| 列名 | 后端字段 | 含义 |
|------|---------|------|
| 代码 | `stock_code` | 6 位股票代码 |
| 名称 | `stock_name` | 股票名称（悬停弹出 MACD 操盘建议） |
| 涨幅 | `change_percentage` | 当日涨跌幅（%） |
| 价格 | `current_price` | 实时市价 |
| 成本 | `cost_price` | 平均持仓成本 |
| 盈亏 | `profit_ratio` | 浮动盈亏比例（%） |
| 市值 | `market_value` | 持仓市值 |
| 可用 | `available` | 可卖股数 |
| 总数 | `volume` | 持仓总股数 |
| 浮盈 | `profit_triggered` | 首次止盈是否已触发（成交确认后标记） |
| 冲高 | `highest_price` | 持仓期间最高价 |
| 止损 | `stop_loss_price` | 动态止损/止盈价格（随 profit_triggered 切换算法） |
| 建仓 | `open_date` | 首次建仓日期 |
| 基准 | `base_cost_price` | 初次建仓成本（补仓摊薄后保持不变） |
| 自动止盈 | `stop_profit_enabled` | 个股级动态止盈止损开关（拨动切换） |

与旧版布局相比的改动：
- ~~全选 checkbox~~ → 文本「网格」（全选逻辑随之移除）
- 新增末列「自动止盈」iOS 风格拨动开关
- 表头文字精简并统一居中
- 消息提示改为 `position:fixed` 浮层，不再挤压页面布局
- 持仓列表与下单日志的宽度比例从 2:1 调整为 **3:1**（`lg:grid-cols-4` + `col-span-3`）

**下单日志**：单行左至右为 名称 → B/S 方向（买红卖绿加粗）→ 金额 → 策略标签 → 时间，所有列严格对齐表头。内容靠左聚拢，无多余空白。时间列由后端 `/api/trade-records` 统一格式化为 `YYYY-MM-DD HH:MM:SS`，QMT 回报的微秒精度不会透出到前端。

### 数据管理按钮语义

| 按钮 | 端点 | 实际影响 |
|------|------|---------|
| 清空买卖日志 | `POST /api/data/clear_buysell` | 仅 `DELETE FROM trade_records`，**持仓数据不受影响** |
| 初始化持股 | `POST /api/holdings/init` | 从 QMT 拉取持仓重建本地元数据，成功与否以返回体 `status` 字段判定 |

!!! warning "二次确认文案与实际行为对齐"
    「清空买卖日志」的两道 `confirm` 提示曾写作"删除所有交易记录**和持仓信息**"，与后端只删 `trade_records` 的实现不符，容易让人误以为持仓会被清掉而不敢点。文案已改为"清空全部买入/卖出日志……不会清空持仓数据"。

### 卖出委托状态
动态止盈止损卖出委托由后端 `pending_orders` 跟踪。委托超时后，如果启用了自动重挂，系统会先撤销旧委托，再以新价格重新提交；`best` 对手价模式下买三价无效时会降级到买一价、最新价、收盘价或原信号价。

这意味着 Web 中“首次止盈已触发”代表**成交确认后的状态**，不是“委托已提交”。生产排查时应同时查看交易记录、后台日志和 QMT 当日委托，避免把待成交卖单误判为已经落账。

### 网格悬停卡片口径

web1.0 持仓列表中，鼠标悬停在已启动网格交易的个股复选框上会显示网格状态卡片。卡片顶部显示**运行时长**，其余比例字段统一使用后端小数比例，由前端格式化为百分比，避免重复乘以 100。

| 字段 | 数据来源 | 口径 |
|------|----------|------|
| 运行时长 | 会话创建时间差 | 从 `created_at` 差值计算（天/时/分） |
| 网格盈亏 | `stats.pnl_snapshot.profit_ratio` | FIFO 账本真实盈亏率；账本不可用时使用 `get_pnl_snapshot()` 的降级口径 |
| 已实现/未实现 | `stats.pnl_snapshot.realized_pnl` / `unrealized_pnl` | 已配对卖出收益 + 未平网格库存浮动盈亏 |
| 交易次数 | `stats.trade_count` / `buy_count` / `sell_count` | 已成交确认并落账后的网格交易次数 |
| 资金使用 | `stats.current_investment` / `config.max_investment` | 当前未平网格投入占最大投入额度比例 |
| 中心价偏离 | `stats.deviation_ratio` + `stats.center_deviation_ratio` | 当前网格中心价相对初始中心价的漂移幅度；显示为正数并标注”上移/下移” |

!!! note "中心价偏离不是当前市价偏离"
    网格风控内部同时计算两种偏离：`drift_deviation = abs(current_center_price - center_price) / center_price` 和 `market_deviation = abs(current_price - current_center_price) / current_center_price`，退出判断取二者最大值。悬停卡片中的“中心价偏离”只展示前者，即网格中心价漂移；当前市价偏离作为后端字段保留，不混入该展示项。

---

## 连接设置面板

顶部 ⚙ 齿轮按钮打开「连接设置」面板：

```
┌──────────────────────────────────────────────┐
│ 当前: HTTPS (安全) — 后端也必须 HTTPS         │
├──────────────────────────────────────────────┤
│ 后端模式：  [ 网关模式 ]  [ 直连模式 ]        │
├──────────────────────────────────────────────┤
│ 网关地址：  http://127.0.0.1:8888             │
│ API Token： •••••••••••• (留空=不验证)        │
├──────────────────────────────────────────────┤
│ 连通性测试：[ 测试连接 ]                      │
│   ✓ 连接成功 — 2 个账号, 2 个在线             │
└──────────────────────────────────────────────┘
```

### 字段说明

| 字段 | 网关模式 | 直连模式 |
|------|---------|---------|
| 地址 | 网关地址（所有账户共用），如 `http://127.0.0.1:8888` | Flask 地址（每账户独立），在账户下拉菜单的 ✎ 中编辑 |
| Token | xtquant_manager 的 `api_token` | Flask 的 `QMT_API_TOKEN` 环境变量值 |
| 测试连接 | `GET /api/v1/health` — 显示账号总数与在线数 | `GET /api/status` — 显示账户 ID |

### 自动化行为

- **保存后自动发现账号**：保存连接配置后调用 `discoverAccounts()`，从网关同步真实账号 ID 到下拉列表（无需手动新增）
- **HTTPS Mixed Content 警告**：HTTPS 页面访问 HTTP 后端会被浏览器阻止，面板自动给出警告
- **无 Token 远程警告**：远程连接而不设 Token 时提示安全风险
- **8s 超时 + 非 JSON 检测**：测试连接遇到反代/Nginx 错误页时给出明确诊断

---

## 启动菜单（miniqmt.bat）

`miniqmt.bat`（或 `python scripts/_launcher.py menu`）打开交互式控制台菜单，完整选项如下：

```
部署/环境：
  [0] 首次部署向导        [1] 检查 Python 环境与核心依赖
  [2] 安装/更新依赖       [3] 检查配置文件
  [4] 拉取最新代码 (git pull)

查看：
  [5] 查看所有账号配置    [6] 查看运行状态

启动（Flask 直连）：
  [7] 启动所有账号 (实盘，启动时选择 web1.0/web2.0)
  [8] 启动所有账号 (模拟，启动时选择 web1.0/web2.0)
  [9] 启动指定账号 (选择实盘/模拟 + web1.0/web2.0)
         web1.0 = Flask :5000 起, 仅本机访问 (配置/监控用)
         web2.0 = xtquant_manager :8888, 全网卡 (只读监控)
                  Flask 仍会启动(仅本机)供网关读取运行时开关

停止：
  [a] 停止所有账号         [b] 停止指定账号
  [c] 强制停止所有账号

XtQuantManager：
  [d] 启动 XtQuantManager 网关   [e] 停止网关
  [f] 网关状态                    [g] 打开 web2.0 UI（浏览器）
  [h] 重启网关                    [i] 查看网关日志

自动买入：
  [j] 启动自动买入服务     [k] 停止自动买入服务
  [l] 查看自动买入状态     [m] 查看自动买入日志

数据源 / 通道切换：
  [n] Tushare Pro 数据源配置
  [o] 大QMT IPC Trader 配置
  [p] XtTrader 通道总控（miniQMT 直连 / IPC-Trader / RPC-Trader）

  [q] 退出
```

菜单底部自动显示当前 XtTrader 通道状态（活跃通道 / 连接状态 / 路径）。

!!! note "菜单节选说明"
    以上为 `python scripts/_launcher.py menu` 的完整选项。CLAUDE.md 中的菜单概览表仅列出了高频使用的子集，请以本文档为准。

### Web 模式偏好记忆

启动菜单 [7]/[8]/[9] 会读取 `data/.web_mode` 中上次的选择：

- `1` → web1.0（Flask）— 系统在每账号端口上启动完整 Flask 服务
- `2` → web2.0（xtquant_manager）— 界面与网关由 xtquant_manager 统一托管；Flask 仍在本机启动（端口空闲时），供网关反向读取运行时开关

每次选择都会持久化，下次启动直接套用偏好。

### 绑定地址 vs 客户端地址分离

xtquant_manager 在 [_launcher.py](https://github.com/weihong-su/miniQMT/blob/main/scripts/_launcher.py) 中明确分离两个概念，避免 `0.0.0.0` 被错误用作客户端目标：

| 常量 | 值 | 用途 |
|------|----|----|
| `XQM_DEFAULT_HOST` | `0.0.0.0` | **绑定地址** — 监听全部网卡，对外可达 |
| `XQM_CLIENT_HOST` | `127.0.0.1` | **客户端地址** — 本机健康检查、浏览器打开 |

启动后菜单会同时显示「本机 URL」和「局域网 URL」：

```
✓ xtquant_manager 已启动
  Web UI:          http://127.0.0.1:8888  (本机)  |  http://192.168.1.10:8888  (局域网)
  API 文档:        http://127.0.0.1:8888/docs
```

---

## Vercel 远程部署（web2.0）

如需将 web2.0 部署到 Vercel/Netlify 等公网托管，通过 Cloudflare Tunnel 暴露 Windows 上的 xtquant_manager：

```
Vercel (静态 UI) ──HTTPS──► Cloudflare Tunnel ──► Windows xtquant_manager :8888 ──► QMT
```

完整步骤（含 Tunnel 配置、Token 安全清单、CORS 排错）参见 [web2.0/VERCEL_DEPLOY.md](https://github.com/weihong-su/miniQMT/blob/main/web2.0/VERCEL_DEPLOY.md)。

### 关键安全要点

- ⚠️ **必须设置 `api_token`**：远程暴露唯一的安全防线，用强随机字符串（≥32 位）
- ⚠️ **必须用 HTTPS 隧道**：Cloudflare Tunnel 自动 HTTPS；直接暴露 `:8888` 到公网会触发浏览器 Mixed Content 拦截
- 远程用户始终通过网关模式接入，写操作（配置/监控/初始化）只能在本机用 web1.0 完成

---

## 开发与构建

```bash
cd web2.0
npm install               # 仅首次
npm run dev               # 开发模式 (http://localhost:5173，热更新)
npm run build             # 生产构建 → dist/
```

构建产物 `web2.0/dist/` 会被 xtquant_manager 自动托管（静态文件 + SPA fallback），也可直接部署到 Vercel。

---

## 相关文档

- [Web API](web-api.md) — REST 端点完整列表（标注网关模式可用性）
- [自动买入](autobuy.md) — 自动买入独立进程、候选池筛选和调度配置
- [架构说明](architecture.md) — 双层存储、信号检测与执行分离
- [XtQuantManager 概述](../xqm/index.md) — 网关详细文档
- [web2.0/VERCEL_DEPLOY.md](https://github.com/weihong-su/miniQMT/blob/main/web2.0/VERCEL_DEPLOY.md) — Vercel 远程部署完整指南
