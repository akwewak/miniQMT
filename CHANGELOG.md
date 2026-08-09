# Changelog

本文件记录 miniQMT 项目所有重要变更，格式遵循 [Keep a Changelog 1.1.0](https://keepachangelog.com/zh-CN/1.1.0/)，版本号遵循 [SemVer 2.0.0](https://semver.org/lang/zh-CN/)。

> 本文件是 **唯一的变更记录源**。文档站 `/changelog/` 页面通过 `include-markdown` 引用本文件，请在此处直接编辑。

## [Unreleased]

### Security
> 对 web1.0 / web2.0 / Flask 后端 / xtquant_manager 网关做了一轮完整网络安全审查。本批合并网关侧三项 P0 与 Flask 后端三处 Token 鉴权遗漏；前端 XSS 链另行提交。

### Security — xtquant_manager 网关
- **网关只读端点完全无鉴权，等同于把财务数据公开**：11 个 Flask 兼容端点（`/api/status`、`/api/positions`、`/api/positions-all`、`/api/accounts`、`/api/connection/status`、`/api/config`、`/api/macd/advice`、`/api/trade-records`、`/api/grid/sessions`、`/api/orders`、`/api/grid/ledger/{id}`）此前均无 `Depends(verify_token)`，任何能连上 `:8888` 的人无需任何凭证即可读取持仓成本、盈亏、历史成交与策略参数。这是刻意设计（源码注释写明"互联网只读用户没有 token 也要能拿账号列表"），但该前提在网关默认绑定 `0.0.0.0` 时不成立。现全部要求 `X-API-Token`。
- **止盈止损端点无鉴权，可被未授权关闭**：`/api/v1/stop-profit/status`（GET）、`/api/v1/stop-profit/config`（POST）、`/api/v1/stop-profit/toggle`（POST）同样缺少保护。`POST /api/v1/stop-profit/toggle?enabled=false` 可在无凭证下关闭全部账号的止损监控，`/config` 可把 `stop_loss_ratio` 改到极端值——这不是信息泄露，是可直接造成资金损失的未授权写操作。三者均已补 Token 保护。
- **伪造 `X-Forwarded-For` 可绕过全部认证**：`_get_client_ip()` 无条件信任该请求头，而 `verify_api_key()` 对 `local_ips` 免 Token 放行，且同一个可伪造的 `client_ip` 同时驱动 Token 放行、IP 白名单、速率限制三处判定。攻击者只需发送 `X-Forwarded-For: 127.0.0.1` 即可冒充本机，一次绕过三道防线并通过轮换该值绕过限流。新增 `trust_proxy` 配置项（默认 `false`，即不再读取该头），仅在网关确实位于受信任反向代理之后才应开启。
- `/api/v1/health/{account_id}` 改为需要 Token；`/api/v1/health`（全局）保留免 Token 可达以支持存活探测与前端"测试连接"（用户此时尚未配置 Token），但未携带有效 Token 时只返回 `total` / `healthy` 计数，`accounts` 明细置空——账号 ID 是遍历其他账号数据的入口，与刚收紧的 `/api/accounts` 是同一份数据，全公开会架空该保护。
- 消除 `_get_client_ip` 的重复实现：`server.py` 的副本改为委托给 `security.py`，避免两份逻辑各自演进（本次漏洞正是两处重复实现之一）。

### Security — Flask 后端（`web_server.py`）
> 在 `QMT_API_TOKEN` 已配置的前提下，补齐 Token 防线上的三处遗漏——这三处是 Flask 后端仅有的绕过 Token 直接可达的写/敏感端点。

- **两个网格模板端点漏挂鉴权**：`DELETE /api/grid/template/<name>` 与 `PUT /api/grid/template/<name>/default` 缺少 `@require_token`，是 Flask 后端仅有的两个无鉴权写端点（同文件其余 19 个 POST/PUT/DELETE 均已挂装饰器）。攻击者无需 Token 即可删除任意网格模板或篡改默认模板。现已补齐装饰器——至此 Flask 所有写端点 100% 受 Token 保护。
- **`/api/debug/status` 泄露真实券商账号 ID**：该端点无鉴权，返回 `config_account_id`、`qmt_acc_account_id`、`env_QMT_ACCOUNT_ID` 的明文真实账号 ID，以及本机文件路径。账号 ID 是可复用的身份标识，配合其他泄露面可用于针对性攻击。现已加 `@require_token` 保护，并对账号 ID 字段做脱敏（仅保留后 4 位）。本机文件路径予以保留（对本地多账号诊断有用，且非可复用凭证）。

### Fixed
- `trust_proxy` 配置在 `StandaloneConfig` → `XtQuantServerConfig` 链路上补齐透传，否则该字段在生产启动路径（`standalone.py`）下会是死配置，用户写进 `xtquant_manager_config.json` 也不生效。
- **网关手测 UI 对 `/api/v1/health/{id}` 永不发送 Token**：`test_ui_a.html` / `test_ui_b.html` 的 `doHealth()` / `doHealthAccount()` 均以 `noToken=true` 调用 `req()`（基于"健康检查无需认证"的旧假设）。该端点现已要求 Token，若不同步修改，用户在手测 UI 中会稳定收到 401 且无从排查；`/health` 总览也会因不带 Token 而拿不到 `accounts` 明细、健康卡片渲染为空。两处均已改为正常发送 Token，并同步修正端点说明与标签样式。

### Tests
- 网关：`test/live_http_xtquant_manager.py` 原用 `X-Forwarded-For` 模拟远程客户端——正是本次禁用的机制。若不处理，其 401 断言会在实际返回 200 时依然"通过"，即**测试会假装安全**。已为该用例显式传入 `trust_proxy=True` 保留模拟意图，并新增两条断言锁住新行为：远程无 Token 时 `/health` 不返回账号明细、伪造 XFF 无法绕过 Token（`trust_proxy=False` 下应 401）。回归验证：`test/test_xtquant_manager/` 222 用例、`test_xqm_flask_compat` + `test_xqm_monitor_endpoints` + `test_multi_account_isolation`、`live_http_xtquant_manager.py` 32/32，全部通过。
- Flask：web_api 组 170/170、system_integration 39/39、grid_validation 38/38 通过；实测三个端点无 Token 返回 401、带 Token 返回 200，真实账号 ID `25105132` 脱敏为 `****5132`。

### Docs
- `docs/site/xqm/guides/security.md`：删除"`/api/v1/health` 和 `/api/v1/health/{id}` 始终无需 Token"的过时描述，新增「端点鉴权一览」与「反向代理与 X-Forwarded-For」两节，安全级别对比表补 `trust_proxy` 列。
- `docs/site/xqm/api/observability.md`：改写"健康检查接口**无需认证**"，补充带 Token / 不带 Token 两种响应示例。
- `docs/site/xqm/configuration/reference.md`：补 `trust_proxy` 字段说明，修正 `api_token` 为空时的行为描述（并非"不验证"，而是仅本机可访问）。
- `docs/site/miniqmt/web-api.md`：认证段拆分 Flask / 网关两种模式的不同口径；`/api/accounts` 行去掉"无 Token"标注。
- `docs/site/miniqmt/web-frontend.md`：连接设置面板 Token 字段由"留空=不验证"改为"远程访问必填"，并说明测试连接能通不代表数据端点可用。
- `CLAUDE.md`：网关能力边界补充鉴权要求与 `trust_proxy` 约束。

### Security — web1.0 前端 XSS（`web1.0/script.js`）
> 路线 A：用转义堵死 innerHTML 注入点，不上 CSP / 不动 Tailwind / 不改 Token 存储。审查发现的 5 处拼接后端或用户可控数据的 innerHTML 全部修复。

- **`escapeHtml` 提升 + 复用**：原先完备的转义函数 `escapeLogHtml`（覆盖 `& < > " '`）被困在日志块作用域内，其余 4 处拼接点够不到。提升一份 `escapeHtml` 到 `DOMContentLoaded` 回调顶部，原 `escapeLogHtml` 改为委托，避免两份实现各自演进。
- **5 处注入点**：
    - 备选池 `<textarea>`（`stocks.join('\n')`）—— `</textarea><script>` 逃逸，已套 `escapeHtml`。
    - 网格交易明细 `trade_id` / `trade_time` / `trade_type` —— 后端字段未转义直插，已套 `escapeHtml`。
    - MACD 操盘建议 tooltip 的 `trend` / `base_position` / `grid` / `cross` / `updated` / `code` / `dif` / `dea` —— 逐字段转义。
    - 预览股票名称列表的 `name`（后端）/ `code`（用户输入）—— 转义；原仅转义单引号的 `safeCode` 改为 `^\d{6}$` 白名单。
    - 持仓行 `createStockRow` 的 `stock_name` / `open_date` —— 转义；`stock_code` 经 `^\d{6}$` 白名单降级为 `safeCode`（畸形输入 → `------`），用于所有内联事件 / `data-*` 属性 / 显示列。
- **设计取舍**：`createStockRow` 与预览列表的内联事件（`onmouseenter="showAdviceTooltip(event, '${code}')"`）采用**白名单**而非「改 `addEventListener`」——code 永远只能是纯数字，从根本上规避 HTML 属性 + JS 字符串双重上下文转义的坑，改动最小、零交互行为风险。日志块 [script.js:1564](web1.0/script.js#L1564) 同模式的 code 已走 `escapeLogHtml`，非 XSS（`&#39;` 突破不了属性），保持原样。
- **未做（有意）**：CSP（Tailwind CDN 会削弱其意义）、Tailwind 本地化、web2.0 `v-html`（审查确认无字符串注入通路）、Token 改 httpOnly cookie（架构变更，单独立项）。

### Tests — web1.0 前端
- `node --check` 语法通过。
- XSS 负向对照（注入 `<img src=x onerror=alert(1)>` 与 `');alert(2);//`）：修复后转义名称无裸 `<`、白名单 code 无可突破字符；对照（未转义）确含可执行 payload——证明测试有效而非空跑。
- 回归：见本次 `--all-with-fast` 结果。

## [3.8.6] - 2026-08-07

> 本版本聚焦**重连状态一致性与信号可靠性**：修复重连瞬间旧 callback 污染新连接、瞬时止盈信号在被消费前丢失两类隐蔽缺陷，补齐重连后的持仓刷新与 QMT 自恢复探测，并让无法回收的超时线程变得可观测。同时包含此前未发布的模拟模式补仓修复。

### Fixed
- **重连后旧 callback 污染新连接状态**：`easy_qmt_trader.connect()` 每次重连都创建全新 `MyXtQuantTraderCallback`，但 `register_callback()` 只设置新 trader 自己的 `.callback`，旧 `XtQuantTrader.callback` 仍持有旧 callback 及其 `disconnect_callbacks`（内含 `PositionManager._on_qmt_disconnect` 绑定方法）。当 `_stop_trader_with_timeout()` 超时放弃等待时（daemon 线程无法被强制终止），旧 trader 连同回调继续存活，其延迟触发的 `on_disconnected` 会把新连接刚设好的 `qmt_connected` 错误置回 `False`，并把重连冷却清零，引发一次本可避免的 stop/connect 周期——而每次 `stop()` 都有再次卡死的风险，可级联放大。新增 `MyXtQuantTraderCallback.detach()` 与 `detached` 失效标记，`connect()` 在停止旧 trader **之前**先 detach（尽早关闭窗口）。刻意只切「连接状态类」推送（`on_disconnected` / `on_stock_order`），**保留 `on_stock_trade` 转发**：成交回报是真实资金变动，迟到仍有价值，且落库层按 `trade_id` 幂等去重，一并拦截反而可能永久丢失一笔成交流水。
- **瞬时止盈信号在被消费前丢失**：持仓监控每 `MONITOR_LOOP_INTERVAL`（3 秒）检测一次并覆盖式写入 `latest_signals`，而策略线程单只股票的实际消费周期约 `10 + 持仓数 + 股票池数` 秒（`_strategy_loop` 轮内每股 `sleep(1)`）。首次止盈是「跨过即触发」的瞬时信号：价格冲到 +6% 入队后回踩到 +5.9%，下一轮 `check_trading_signals()` 返回 `None`，原实现直接 `pop` 删除，策略线程取时队列已空——**该卖 60% 的单子整个消失且不会补触发**，直到价格再次上穿。新增信号保活：已入队未消费的动态信号在保活窗口内不因「本轮无信号」被删除（`grid_` 前缀信号走独立链路，不受影响）。
- **重连成功后持仓缓存未刷新**：`_start_qmt_connect_worker()` 成功分支只置 `qmt_connected` 并重注册回调，未置零 `last_position_update_time`，导致最长 `QMT_POSITION_QUERY_INTERVAL`（10 秒）内继续使用断连前的持仓快照；若断连期间发生外部成交，止盈止损会基于错误持仓判断。
- **QMT 自行恢复后仍触发冗余重连**：QMT 进程崩溃后自动重启时 `position()` 已能返回真实数据，但 `qmt_connected` 仍为 `False`，需累计 3 次错误才触发一次完整 stop/connect——而 `stop()` 每次都有卡死风险（正是上述旧 callback 缺陷的触发前提）。新增 `PositionManager._probe_qmt_recovered()`，用 `ping_xttrader()`（真实 `query_stock_asset` 探针）确认 QMT 确已应答后自恢复。**刻意不以「持仓查询返回空」作为依据**——`position()` 在断连时同样返回空 DataFrame，与「真的没有持仓」无法区分，据此自恢复会造成假健康。重连进行中 / 模拟模式 / 网关模式一律不探测。
- **模拟模式补仓完全失效**：`strategy.execute_add_position_strategy()` 的模拟分支以 `volume=` / `price=` 调用 `position_manager.simulate_buy_position()`，而该方法签名为 `(stock_code, buy_volume, buy_price, strategy)`。关键字参数名不匹配导致每次模拟补仓都抛 `TypeError`，异常被外层 `except` 吞掉、只留一行 error 日志，因此长期未被发现。已改为 `buy_volume=` / `buy_price=`。
- **模拟分支补仓不受冷却期约束**：2 分钟冷却时间戳 `last_trade_time[cool_key]` 原先只在实盘分支写入，模拟分支 `if success: return True` 直接返回，导致模拟模式可无限次连续补仓，与实盘行为不一致。已在模拟分支补齐冷却期写入，与实盘分支对齐。

### Added
- **动态信号执行前时效兜底**：信号执行使用的是生成时的 `current_price` 快照，而 `validate_trading_signal()` 此前对止盈类信号没有价格漂移防护。若只做上述信号保活，会把「丢单」换成「以过旧价格下单」。故同时在 `validate_trading_signal()` 入口加入信号年龄检查，超龄一律拒绝并返回 `signal_expired`（网格信号有自己的 `_validate_grid_signal_before_execute`，不重复拦截）。设计参照网格侧已验证的复核范式。
- 新增配置：`ENABLE_DYNAMIC_SIGNAL_KEEPALIVE`（默认 `True`）、`DYNAMIC_SIGNAL_KEEPALIVE_SECONDS`（默认 90 秒）、`DYNAMIC_SIGNAL_MAX_AGE_SECONDS`（默认 120 秒）。三者关闭/调整即可回退到原行为。
- **超时泄漏线程可观测**：`run_with_timeout()` 的 `future.cancel()` 无法取消已开始执行的任务，`cancel_futures` 也不中断运行中线程；QMT 卡死时每次超时都会泄漏一个线程，无人值守长跑持续累积。Python 无法强制终止线程，故不作「已修复」的假象处理，改为新增 `get_leaked_call_count()` / `reset_leaked_call_count()` 并按间隔（每 10 次）告警，使问题可观测、可诊断。

### Tests
- 新增 `test/test_p1_fixes.py`（16 用例）与 `p1_fixes` 测试组：覆盖重连缓存刷新（成功置零 / 失败不置零）、QMT 自恢复探测（ping 成功 / 失败 / 异常 / 重连中 / 模拟 / 网关六种路径）、信号保活（窗口内保留 / 超窗清除 / 开关关闭回退 / 网格信号不受影响）、执行前时效兜底（过期拒绝 / 新鲜放行）、超时泄漏计数（正常不计 / 超时计入 / 多次累加）。
- `test/test_trader_callback.py` 新增 `test_i2`~`test_i6`（5 用例）：旧 callback 延迟断连不污染新连接、`detach()` 语义、detached 后仍转发真实成交、detach 必须早于 stop。
- **负向对照验证**：逐项还原为修复前行为后，P0/P1 相关用例共 9 个失败（含核心的 `test_i2_stale_callback_disconnect_does_not_clobber_new_connection` 与 `test_p1_4_fresh_signal_survives_price_retrace`），确认新增用例确实能捕获对应缺陷，而非只会变绿的空测试。
- 修复既有测试隔离缺陷：`test_i1` 在全量回归中失败（`git stash` 验证：不带本次改动同样失败）。根因是 `test_qmt_ipc_position_manager_integration` 永久替换 `sys.modules["easy_qmt_trader"]` 为 stub，导致 `patch("easy_qmt_trader.XtQuantTrader")` 打在 stub 上、真实模块仍用真 `XtQuantTrader` 而去连真实 QMT。改用 `connect.__globals__` 定位真实模块 globals，绕过 `sys.modules` 污染。
- 新增 `simulation_trading_e2e` 测试组（4 个模块、53 个用例），补齐模拟交易模式此前的测试盲区 —— `simulate_buy_position` / `simulate_sell_position` 此前无任何专项测试，`test_system_integration.py` 中名为"模拟买卖流程"的用例实际只验证 `MockQmtTrader` 自身账本，未触及 `position_manager` 模拟链路：
    - `test_simulation_position_core.py`（19 例）— 加权平均成本、买入 0.0003 / 卖出 0.0013 手续费精度、首次部分卖出的获利分摊与 `profit_triggered` 置位、双层存储隔离（模拟持仓只落内存、流水落 SQLite）、超卖 / 零量 / 负量 / `available` 不足 / 未持仓等边界拒绝（每例三重断言：返回 False、余额未变、流水未增）。
    - `test_simulation_web_execute_buy.py`（10 例）— `POST /api/actions/execute_buy` 端到端串联 `Methods.add_xt_suffix` → `manual_buy` → `buy_stock` → `simulate_buy_position`（不 mock 中间层），覆盖代码后缀格式化、`M_simu` 策略标识、`ENABLE_ALLOW_BUY` 门控、模拟模式无视交易时间、`random_pool` / `custom_stock` 选股策略。
    - `test_simulation_strategy_execution.py`（14 例）— 策略层四条模拟分支（补仓 / 止损 / 半仓止盈 / 全仓止盈），含上述两个缺陷的回归锚点，以及 `sell_ratio` 取自 `INITIAL_TAKE_PROFIT_RATIO_PERCENTAGE`（小数 0.6）的公式锚定。
    - `test_simulation_mode_switch.py`（10 例）— `simulationMode` 运行时切换（重建内存库、清理 `qmt_trader`、不持久化）、`SIMULATION_BALANCE` 逐用例隔离的夹具自检、模拟模式账户口径（`available` / `total_asset` / 返回真实 `account_id` 而非 `'SIMULATION'`）。
- 修复新增测试引入的跨模块串扰：`run_integration_regression_tests.py` 会先 `__import__` 全部测试模块、之后才开始跑用例。L2/L4 原先在模块顶层把 `sys.modules['easy_qmt_trader']` 替换为 `MagicMock` 并留待 `tearDownModule` 还原，导致 `test_trader_callback` 的 `patch("easy_qmt_trader.XtQuantTrader")` 打在 Mock 上而非真实模块。已将 mock 作用域收紧到 `try/finally`，import 完成即刻还原。
- 使用 `C:\Users\PC\Anaconda3\envs\python39\python.exe test/run_integration_regression_tests.py --all-with-fast` 完整回归：**33 组、123 模块、2361 用例，2361 通过，0 失败，0 错误，0 跳过，成功率 100%**，耗时 1013.0 秒。

### Docs
- 修正实现与文档不一致的三处口径：
    - 删除 `PositionManager.signal_timestamps` 死字段（初始化后从未被读写），并把 `CLAUDE.md` / `AGENTS.md` / `faq.md` 中「确认 `signal_timestamps` 机制正常工作」更正为真实机制（`latest_signals[...]['timestamp']` + `get_pending_signals()` 的 300 秒过期过滤）。
    - 8 处 **FIFO → LIFO** 补漏：网格账本配对实现为 `ORDER BY opened_at DESC`（最近优先），v3.8.x 曾做过一轮文档更正但有遗漏，本次补齐 `CLAUDE.md` / `AGENTS.md` / `index.md` / `testing.md` / `web-api.md` / `web-frontend.md`。展示类查询的 `ASC` 属正常时序，未改动。
    - 更正「感知断连三条路径」表述：路径 C（thread_monitor 心跳探测）实际未启用——`check_qmt_connection_health()` 已实现但 `main.py` 刻意不注册 `heartbeat_check`（QMT 断连 ≠ 线程崩溃，ping 失败会触发无意义的线程重启噪音）。
- `configuration.md` 新增动态信号保活三个开关说明；`unattended.md` 补充重连自恢复探测与超时泄漏可观测；`stop-profit-loss.md` 说明信号保活与时效兜底机制；`CLAUDE.md` 止盈配置段同步新增开关。
- `testing.md` / `CLAUDE.md` / `AGENTS.md` / `README.md` / `QUICK_START.md` 同步测试统计到本次实测结果（33 组、123 模块、2361 用例；`fast` 子集 40 模块、911 用例）。

## [3.8.5] - 2026-08-01

> 本版本聚焦**实盘稳定性修复**：消除外部成交回报引发的 xttrader 死锁、修正 Tushare 日期入参导致的静默降级、兼容交易记录混合时间格式，并修正 web1.0 两处按钮行为与文案。

### Fixed
- **外部成交导致 xttrader 死锁**：在 QMT 客户端手工下单（或其他程序用同一账号交易）时，本机收到成交回报但匹配不到本机委托，此前会在回调线程内反向调用 QMT 同步接口，与回调线程互等而永久阻塞。三处收口：
    - `_record_external_trade_after_callback()` 改为只把 `last_position_update_time` 置零，让下一轮持仓监控自行同步，不在回调里请求持仓快刷。
    - `_confirm_filled_order()` 仅在 `matched_key or order_info` 为真（确实匹配到本机委托）时才调用 `_request_immediate_position_refresh()`。
    - 回调链路写流水时通过新增的 `get_stock_name(..., allow_qmt_lookup=False)` 关闭 QMT 持仓回查，名称改由缓存/xtdata/Tushare 等非阻塞源提供；`_save_trade_record()` 新增 `allow_qmt_name_lookup` 参数并对旧签名做 `TypeError` 兼容。
- **`xt_trader.stop()` 卡死拖垮重连线程**：新增 `easy_qmt_trader._stop_trader_with_timeout()`，把 `stop()` 放进 daemon 线程并按 `QMT_STOP_TIMEOUT`（默认 5 秒）超时放弃等待继续重连。`connect()` 的四条清理路径（清理旧实例 / 连接超时 / 连接异常 / 连接失败）统一走该入口，替换原先四段裸 `try: stop()`。
- **Tushare 日期入参未归一化**：`daily` 接口要求 `YYYYMMDD`，而项目内部（含盘中补齐历史数据的调用方）传的是 `YYYY-MM-DD`，此前直接透传导致 Tushare 返回空集并静默降级到 Mootdx。新增 `DataManager._format_tushare_date()` 统一转换，无法识别时回落到默认区间（近 365 天 / 今天）。
- **交易记录混合时间格式导致接口 500**：`trade_records.trade_time` 在库中可能混合 QMT 回报的微秒精度（`2026-07-31 09:31:50.610000`）、系统写入的秒级（`09:30:44`）和历史 ISO 格式，原先整列走 `pd.to_datetime` 会抛错。新增 `_format_trade_time_for_response()`：依次尝试带/不带微秒的严格解析，回退 `pd.to_datetime`，全部失败才原样返回并记 WARNING。
- **web1.0「初始化持股」按钮不显示成功**：`POST /api/holdings/init` 返回体缺 `status` 字段，前端据此判定失败。后端补齐 `status`（由 `success` 推导），并同步收紧测试断言。
- **web1.0「清空买卖日志」文案与实现不符**：二次确认提示原写作"删除所有交易记录**和持仓信息**"，而后端只执行 `DELETE FROM trade_records`。文案改为"清空全部买入/卖出日志……不会清空持仓数据"。

### Added
- 新增配置 `QMT_STOP_TIMEOUT = 5.0`（QMT 交易接口停止超时，秒）。

### Tests
- 新增/扩展用例：`test_trader_callback.py`（外部成交不触发回调内持仓回查、`stop()` 超时不阻塞重连）、`test_tushare_adapter.py`（日期格式归一化）、`test_web_api_complete.py`（混合时间格式、`holdings/init` 返回 `status`）。
- 使用 `C:\Users\PC\Anaconda3\envs\python39\python.exe test/run_integration_regression_tests.py --all-with-fast` 完整回归：**31 组、108 模块、2014 用例，2014 通过，0 失败，0 错误，0 跳过，成功率 100%**，耗时 871.99 秒。

### Docs
- `architecture.md` 新增「外部成交补账」小节，明确回调线程内不得回查 QMT 的约束及三处收口点。
- `unattended.md` 超时保护章节新增「xttrader 连接与清理超时」，说明 `_stop_trader_with_timeout()` 机制与死锁背景。
- `configuration.md` 新增「xttrader 直连参数」表（`USE_SYNC_ORDER_API` / `QMT_CONNECT_TIMEOUT` / `QMT_STOP_TIMEOUT`），Tushare 章节补充日期入参自动归一化说明。
- `web-api.md` 补充交易时间格式兼容说明、`clear_buysell` 只删交易记录的语义、`holdings/init` 返回 `status`。
- `web-frontend.md` 新增「数据管理按钮语义」表与文案对齐提示。
- `CLAUDE.md` 常见问题新增第 7 条「外部成交后系统卡死 / 重连线程僵住」。
- 同步更新 `testing.md` / `CLAUDE.md` / `README.md` 的测试统计到 v3.8.5 实测结果。

## [3.8.4] - 2026-07-28

> 本版本将**动态止盈止损开关下沉到个股层面**：全局开关之下新增每只股票的独立闸门，可在 web1.0 持仓列表用拨动开关随时暂停/恢复单只股票；同时优化 web1.0 持仓列表与下单日志的排版可读性。

### Added
- **个股级动态止盈止损开关**：`positions` 表新增 `stop_profit_enabled` 字段（默认 `1`=开启，向后兼容）。与全局 `ENABLE_DYNAMIC_STOP_PROFIT` / `ENABLE_AUTO_TRADING` 为 **AND** 关系——全局关则全关，全局开时可单独暂停某只股票；被关闭的个股跳过信号检测并清理其残留动态信号，不影响网格信号与其他股票。
- **写入入口** `PositionManager.set_stop_profit_enabled()`：仿 `GridTradingManager.set_session_enabled` 的开关范式，只更新单列 + `_increment_data_version()`，不触碰 `update_position` 核心路径。
- **新增端点** `POST /api/holdings/stop_profit`（参数 `stock_code`、`enabled`，需 Token）。
- **web1.0 持仓列表末列「自动止盈」拨动开关**：纯 CSS iOS 风格滑动开关（不引入任何库），切换即持久化，失败自动回滚并提示。
- **网关模式同步支持**：`xtquant_manager/stop_profit.py` 每轮检测前读取账号 `data_<账号>/trading.db` 的开关表并跳过被关闭的个股；库/列/行缺失一律按"开启"处理，保证向后兼容。

### Changed
- **web1.0 持仓列表**：首列表头由全选 checkbox 改为「网格」文本并居中（随之移除已失效的全选逻辑）；表头文字精简为涨幅/成本/盈亏/可用/浮盈/冲高/止损/建仓/基准/自动止盈并统一居中。
- **web1.0 下单日志**：移除恒空的 `log-col-side` 列；B/S 改为买红卖绿加粗（原先挂 `strategyClass`，网格/外部策略返回空串导致方向不着色）；列宽收紧、金额列弹性右对齐并补齐表头时间列占位，表头与记录严格对齐。
- **web1.0 布局比例**：持仓列表与下单日志由 2:1 调整为 3:1，持仓列表获得更多宽度。
- **消息提示改为 fixed 浮层**：`#messageArea` 脱离文档流，消息出现/消失不再挤压页面造成布局抖动（原先插入 DOM 会把下方内容整体推下再弹回）。

### Tests
- 新增 16 个用例：门控 7（个股开关关闭不入队/重开恢复/清理残留/不误删网格信号/默认开启/持久化+版本自增/不存在持仓）、Web API 4、网关 5。
- 使用 `C:\Users\PC\Anaconda3\envs\python39\python.exe test/run_integration_regression_tests.py --all-with-fast` 完整回归：31 组、108 模块、2004 用例，2004 通过，0 失败，0 错误，成功率 100%，耗时 672.75 秒。

### Docs
- 更新 `CLAUDE.md`（门控规则、持久化字段表、API 列表）。
- 更新止盈止损文档：门控表新增个股开关行，新增「个股级开关」小节（AND 语义、Web 操作、网关行为），字段表补充 `stop_profit_enabled` 及旧库自动迁移说明。
- 更新 Web 前端文档：系统性与代码实现对齐——补全完整 16 列表头释义与字段对照表、修正顶部控制条描述（`ENABLE_DYNAMIC_STOP_PROFIT` 为后端配置开关无前端 UI、网格自动/暂停位于对话框内、补充 Token localStorage 来源、web2.0 从"3 个开关"更正为 7 个控件）、网关能力边界修正（下单 UI 仅在直连下显示、SSE 直连可用）、网格悬停卡片新增"运行时长"字段、启动菜单补全 21 个完整选项。
- 更新 Web API 文档：系统状态表新增 `GET /api/macd/advice`（MACD 操盘建议），修正 `POST /api/v1/stop-profit/config`（原误标为 GET），v1 摘要表补充 Token 标注。

## [3.8.3] - 2026-07-25

> 本版本新增 **MACD 操盘建议悬浮窗**：web1.0 / web2.0 悬停账号(深证成指)或持仓个股名称，弹出"底仓 / 网格"参考建议及迷你全景图。

### Added
- **MACD 操盘建议后端**：新增 `macd_advisor.py`(决策矩阵纯函数 `classify` + 逐日序列构建 `_build_series` + 5 分钟缓存)与只读端点 `GET /api/macd/advice`。决策方向看 DEA、0 轴位置看 DIF；复用 `data_manager.update_stock_data` / `indicator_calculator` / `get_indicators_history`。
- **悬浮迷你全景图**：悬浮窗下半部渲染日 K 线 + MA8/MA34 均线 + MACD(DIF/DEA/柱/0轴) + 底部"底仓/网格"区间色带(左侧图例、段内简化文字)。web1.0 原生 SVG(`renderMacdChartSVG`)、web2.0 共享 TS 渲染器 `web2.0/src/utils/macdChart.ts`，两端输出逐字节一致。
- 悬浮窗右上角新增"操作建议"胶囊标签(仿网格卡片风格)。

### Tests
- 新增 `test/test_macd_advisor.py`(25 用例，覆盖决策四象限、DIF 轴、序列构建、MA8/MA34)。
- 使用 `C:\Users\PC\Anaconda3\envs\python39\python.exe test\run_integration_regression_tests.py --all-with-fast` 完整回归：31 组、1963 用例，1963 通过，0 失败，0 错误，成功率 100%。

## [3.8.2] - 2026-07-24

### Changed
- **网格真实盈亏账本改为 LIFO 最近优先配对**：`grid_lots` 普通卖出优先匹配最近买入批次；`grid_lot_matches` 中先卖后买的底仓回补优先匹配最近未回补卖出，使策略绩效口径贴近“上涨卖出、回落买回”的网格闭环。

### Tests
- 使用 `C:\Users\PC\Anaconda3\envs\python39\python.exe test\run_integration_regression_tests.py --all-with-fast` 完整回归：31 组、107 模块、1963 用例，1963 通过，0 失败，0 错误，成功率 100%。

### Docs
- 更新 README、架构文档和在线网格/数据库文档中的真实账本口径说明，从 FIFO 调整为 LIFO 最近优先。

## [3.8.1] - 2026-07-15

> 本版本聚焦**实盘成交确认闭环与 Web 网格状态口径修正**：动态止盈止损、补仓和网格交易均以成交确认为准写入普通成交流水；web1.0 网格悬停卡片统一真实盈亏和中心价偏离展示口径。

### Changed
- **成交确认后写 `trade_records`**：实盘动态止盈止损、补仓和网格委托不再在委托提交阶段写普通成交流水，统一等成交回报或对账兜底确认后落库，避免 Web 交易记录出现未成交委托。
- **网格悬停卡片口径统一**：web1.0 已启动网格个股的悬停卡片统一读取后端 `pnl_snapshot` 真实盈亏，小数比例由前端统一格式化为百分比，避免重复乘以 100。
- **中心价偏离口径明确化**：`/api/grid/session/<stock_code>` 返回中心漂移偏离、市价偏离和有效偏离三类字段；悬停卡片“中心价偏离”仅展示当前网格中心价相对初始中心价的漂移，并标注上移/下移。

### Fixed
- 修复网格悬停卡片中“盈亏率”可能把后端百分比和小数比例混用导致显示错误的问题。
- 修复“中心价偏离”展示混入当前市价偏离的问题；自动退出仍使用 `max(drift_deviation, market_deviation)` 作为有效偏离。

### Tests
- 新增/扩展 `test/test_web_api_complete.py`，覆盖 `/api/grid/session/<stock_code>` tooltip 字段的小数比例、真实盈亏快照和偏离度字段。
- 新增 `test/test_web1_grid_dialog_static.py`，静态验证 web1.0 悬停卡片不再重复缩放后端比例，且中心价偏离按后端中心漂移字段展示。
- 完整集成回归：`C:\Users\PC\Anaconda3\envs\python39\python.exe test/run_integration_regression_tests.py --all-with-fast`，31 组、107 模块、1933 用例，1933 通过、0 失败、0 错误、0 跳过，成功率 100%，耗时 633.95 秒。

### Docs
- 更新 README、Web 前端文档和 Web API 文档，说明网格悬停卡片的数据来源、比例格式、中心价偏离和成交确认后写流水语义。
- 更新网格交易文档，补充偏离度双口径、有效偏离退出规则，以及三种 xttrader 通道下成交兜底确认后写 `trade_records` 的约束。
- 更新测试框架文档到 v3.8.1 完整回归结果。

## [3.8.0] - 2026-07-13

> 本版本聚焦**大QMT RPC 交易通道 P5 下单联调闭环与配置体验优化**：price_type 调用方可控透传、.env fallback 生产可用、控制台 XtTrader 通道总控菜单（三通道一键切换）。

### Added
- **miniqmt.bat XtTrader 通道总控菜单 `[p]`**：三通道（miniQMT 直连 / 大QMT 文件IPC / 大QMT RPC）可视状态显示与一键切换，支持 RPC Redis 连接配置（host/port/db/password）、下单安全开关切换，同时自动处理通道互斥。
- **.env fallback 机制**：`config.py` 顶部新增 `_load_dotenv_fallback()`，import 时把项目根 `.env` 补进未设置的环境变量。优先级：Windows 用户级/系统环境变量 > .env。零新依赖，自写解析器（KEY=value / # 注释 / 剥引号 / utf-8-sig）。
- **`.env.example` 全面改写**：对齐完整 `.env` 结构（QMT路径/Web API Token/Tushare/IPC/RPC/数据源），所有敏感值替换为占位符，添加分组注释与配置优先级说明。
- **测试隔离开关 `MINIQMT_DISABLE_DOTENV`**：`test/conftest.py` + `test/run_integration_regression_tests.py` 顶部设开关，防止本地 `.env`（含真实 token）污染回归测试基线。
- **大QMT RPC Redis 部署文档** `docs/site/miniqmt/qmt-rpc-redis-setup.md`：Memurai 安装、密码配置、L1/L2 连通性验证、跨机补充，已挂 mkdocs 导航。

### Changed
- **`QmtRpcTrader._send()` price_type 透传**：`_send()` / `buy()` / `sell()` / `order_stock()` 接受调用方显式指定 `price_type` 并透传到 vendored → passorder；不指定时按价格自动推断（price=0 → LATEST_PRICE，否则 → FIX_PRICE）。
- **`_launcher.py` 菜单重构**：原 `[o]` IPC 配置保持不变，新增 `[p]` XtTrader 通道总控（含 `cmd_xttrader_config` + 状态辅助函数），主菜单底部实时打印当前通道简述与 RPC 详情。选择范围从 `a-o` 扩展到 `a-p`。
- **联调 checklist 更新**：`qmt-trader/大QMT-RPC联调checklist.md` 下单闭环全部勾选，新增 strategy_name 匹配和 price_type 透传排障条目。

### Fixed
- 首次启用 .env fallback 后全量回归 54 个 failure（本地 `.env` 含真实 token 导致 web_api 401 + 数据源路由漂移）→ `MINIQMT_DISABLE_DOTENV` 修复，1912/1912 全绿。
- `QmtRpcTrader._send()` 原忽略 `price_type` 参数自行推断 → 改为透传（调用方指定时生效）。

### Tests
- `test/test_qmt_rpc_trader.py`：13 → 67 用例。新增连接生命周期、断连回调、Redis 推送事件模拟、卖单路径、资金校验（check_stock_is_av_buy/sell）、健康诊断、order_id_map 截断、市价 vs 限价 price_type、空持仓、空 available 字段降级。
- `test/test_config_env_overrides.py`：新增 `TestDotenvFallback` 5 用例（补缺/优先级/引用剥离/注释跳过/缺失文件 no-op）。
- 全量集成回归 `--all-with-fast`：31 组、1912 用例、1912 通过、0 失败、0 错误，成功率 100%。
- P5 真实联调验证（Redis Memurai + 大QMT BIGQMT_REDIS_DRYRUN，账号 25105132）：L0 redis 库 → L1 Redis 直连 → L2 RPC ping/rpc_alive → 资产/持仓查询返回真实数据（可用46.6万/持仓300105一只）→ 下单闭环（strategy_name 匹配后查到委托、sysid 回填、撤单成功）。非交易时段废单 status=57（预期），完整链路 passorder→sysid→查询→撤单已验证。联调脚本：`test/live_qmt_rpc_readonly_check.py` / `test/live_qmt_rpc_strategy_check.py`。

### Docs
- 更新 CLAUDE.md：v3.7.0+ 配置开关、三通道概述、.env fallback 机制、QmtRpcTrader 模块职责、qmt-trader/ 子模块说明。
- 更新 `docs/site/miniqmt/configuration.md`：mermaid 图新增 RPC 通道、四通道表格、RPC 参数完整列表（12 项）。
- 更新 `docs/site/miniqmt/index.md`：核心特性新增 xttrader 降级通道和 .env fallback，下一步链接新增 RPC Redis 部署文档。
- 更新 `docs/site/miniqmt/architecture.md`：模块职责新增 qmt-trader/ 子模块说明。
- 更新 `release_version.json` → v3.8.0。

## [3.7.0] - 2026-07-13

> 本版本聚焦**大QMT RPC 交易后端（QmtRpcTrader）P5 只读联调与 price_type 透传修复**。

### Added
- **大QMT RPC 交易后端 `QmtRpcTrader`**：第四种交易通道，基于 vendored xtquant_big_convert，通过 Redis/ZMQ RPC 驱动大QMT策略进程执行交易。`_create_qmt_trader()` 四选一工厂，`ENABLE_QMT_RPC_FALLBACK` / `QMT_RPC_TRANSPORT` / `QMT_RPC_REDIS_*` / `QMT_RPC_ALLOW_ORDER` 等配置项。（v3.6.0 引入代码，v3.7.0 完成 P5 只读联调验证）
- **RPC 只读联调验证**：L0(redis库)/L1(Redis直连)/L2(RPC链路) 三阶自检，ping → query_stock_asset/position/orders/trades 返回真实数据，联调脚本留存 `test/live_qmt_rpc_readonly_check.py`。

### Fixed
- **`_send()` price_type 参数忽略**：`buy/sell/order_stock` 接口接受 `price_type` 参数但 `_send()` 不转发 → 修复为调用方指定时透传，不指定时按价格自动推断（price=0→LATEST_PRICE，否则→FIX_PRICE）。

### Docs
- `qmt-trader/大QMT-RPC联调checklist.md`：新增 strategy_name 匹配排障、price_type 透传说明。

## [3.6.0] - 2026-07-10

> 本版本聚焦**实盘委托生命周期与无人值守生产安全**：首次止盈状态改为成交回报确认后落地，动态止盈止损信号在已有在途委托时阻断，撤单重挂价格增加多级兜底；同时发布大QMT文件IPC交易通道、xtdata tick 推送缓存和行情健康严格门禁。

### Added
- **大QMT文件IPC交易通道**：新增 `qmt-trader/qmt_ipc_trader.py`、`qmt_trade_client.py`、`QMT_trade_executor.py` 和部署手册，支持在 miniQMT xttrader 直连受限时，通过大QMT内置 Python 脚本执行下单/撤单/成交回报轮询；多账号自动隔离到 `{QMT_IPC_ROOT}/{account_id}/`。
- **控制台配置入口**：`miniqmt.bat` / `scripts/_launcher.py` 增加 Tushare Pro 与大QMT IPC Trader 快捷配置、连通性检查和心跳检查。

### Changed
- **首次止盈实盘确认语义**：`take_profit_half` 实盘委托提交成功后不再立即标记 `profit_triggered=True`，改为成交回报确认后更新内存与 SQLite，避免委托未成交时误进入动态止盈阶段。
- **在途委托防重保护**：动态止盈止损入队和最终信号校验都会检查本地 `pending_orders` 与 QMT 活跃委托；同一股票已有在途卖单时阻断新止盈/止损信号，防止重复卖出。
- **撤单重挂价格兜底**：`PENDING_ORDER_REORDER_PRICE_MODE="best"` 下买三价为 `0` 或缺失时，按买一价、最新价、收盘价、原信号价逐级降级；`sell_stock(price=0)` 也会自动改为获取有效买盘/最新价。
- **行情源健康门禁默认启用**：`MARKET_HEALTH_OBSERVE_ONLY` 默认改为 `False`，持仓监控会按健康评分和数据源策略判断行情是否可参与交易信号检测。
- **xtdata tick 推送缓存**：优化实时行情读取路径，减少重复 tick 请求并提升持仓监控循环稳定性。
- **动态止盈止损信号门控**：监控线程仅在 `ENABLE_DYNAMIC_STOP_PROFIT` 与 `ENABLE_AUTO_TRADING` 同时开启时才检测并写入动态止盈止损信号，关闭自动止盈时清理残留动态信号，避免日志刷屏。

### Fixed
- **撤单后重挂跟踪丢失**：修复旧委托撤销成功后先重挂再清理，导致新委托跟踪记录被误删的问题。
- **自动止盈关闭后的日志刷屏**：修复持仓持续满足止盈条件时，监控线程每 3 秒反复入队、策略线程反复清理的循环。

### Security
- **账号信息脱敏**：将 IPC、XtQuantManager 示例文档、测试样例和 Web 占位提示中的真实资金账号统一替换为 `TEST_ACC_1` / `TEST_ACC_2`，避免发布包泄露生产证券账号。

### Tests
- 使用 `C:\Users\PC\Anaconda3\envs\python39\python.exe test/run_integration_regression_tests.py --all` 完成全量集成回归：28 组、70 模块、1039 用例，1039 通过，0 失败，0 错误，成功率 100%。
- 新增/扩展 `test_trader_callback` 与 `test_order_rejection`，覆盖成交后标记首次止盈、在途委托阻断、撤单重挂跟踪保留、买三价为 0 时价格降级、卖出价为 0 时自动兜底。

### Docs
- 更新配置参考、止盈止损策略、Web 前端/Web API、测试框架、README 与开发指南，说明 v3.6.0 的委托确认语义、行情健康默认门禁和最新回归统计。

## [3.5.0] - 2026-07-09

> 本版本聚焦**网格交易实盘落账准确性**：部分成交聚合落账避免QMT拆单导致重复记录，买卖量基数统一确保网格对称运行。同时新增 Tushare 数据源适配。

### Added
- **Tushare 数据源适配**：新增 tushare 股票行情数据接口适配，作为 xtdata/Mootdx/baostock 之外的数据来源扩展（`test/test_tushare_adapter.py` + `test/smoke_tushare.py`）。

### Changed
- **网格部分成交聚合落账**：`handle_deal_callback` 改为部分成交阶段只累积填充量不落账（不写 `grid_trades`/`trade_records`，不重建网格），全部成交后一次性聚合写入（1条 `grid_trades` 加权均价 + 1条 `trade_records` + 1次 `_rebuild_grid`），避免 QMT 拆单（如 1300 股拆成 12 笔）导致重复落账和统计失真。DB失败时回滚 pending 累积量，保留 pending 等待补偿确认重试。
- **网格买卖量基数统一**：有持仓时买入量与卖出量使用同一基数 `current_volume × position_ratio`，确保每档买卖操作量对称；无持仓时回退为基于金额计算；买入量始终受 `max_investment` 硬上限约束。`execute_grid_trade` 中 BUY 信号也预取持仓快照（原仅 SELL）。
- 聚合落账用 `order_id` 作为 `trade_id`，避免多笔部分成交使用无意义的券商 `trade_id`。

### Tests
- `test_grid_live_order_confirmation` — 部分成交聚合语义已同步更新
- `test_grid_bugfix_c1` — DB失败+回滚逻辑更新
- `test_grid_mece_regression` — 部分成交统计预期更新
- `test_grid_trade_buy` / `test_grid_trade_sell` — 聚合 trade_id 更新
- `test_max_investment_strict` — 买入量基于持仓的预期值更新
- 新增 `test_tushare_adapter` / `smoke_tushare` — tushare 适配器单元测试与冒烟
- 集成回归测试新增 tushare 适配器模块到 fast 组

### Docs
- 更新 `docs/site/miniqmt/grid-trading.md` 部分成交聚合与买卖量统一文档

## [3.4.0] - 2026-07-04

> 本版本聚焦**无人值守长稳运行与自动操作开关解耦**：新增数据库维护与日志轮转，将自动交易拆为「总开关 → 策略分开关 → 单只会话开关」三层结构，并把发布版本号收敛到单一来源统一管理。

### Added
- **自动操作三层开关**：新增全局总开关 `ENABLE_AUTO_OPERATION`（默认 `False`，运行时开关、不持久化），与 `ENABLE_AUTO_TRADING`（动态止盈止损分开关）、`ENABLE_GRID_TRADING`（网格分开关）解耦，形成「总开关 → 策略分开关 → 单只网格会话 `grid_trading_sessions.enabled`」结构；关闭总开关时所有自动策略停止产生新单，监控线程仍持续检测信号。web1.0 / web2.0 自动操作控制同步调整。
- **数据库维护任务**（[maintenance.py](https://github.com/weihong-su/miniQMT/blob/main/maintenance.py)，`ENABLE_DB_MAINTENANCE=True`）：独立线程每日非交易时段（`DB_MAINTENANCE_TIME="00:10:00"`）清理过期追加型历史数据，删除行数达阈值（`DB_MAINTENANCE_VACUUM_MIN_DELETED_ROWS=1000`）后执行 `VACUUM` 回收空间；`DB_MAINTENANCE_REQUIRE_NON_TRADE_TIME=True` 确保不影响盘中交易。
- **日志轮转**：XtQuantManager 批处理重定向日志按大小轮转（`XQM_LOG_MAX_SIZE=10MB` × `XQM_LOG_BACKUP_COUNT=5`），随维护任务触发；主日志沿用 `RotatingFileHandler`。
- **发布版本号单一来源**：新增 `release_version.json` 作为唯一版本号出处，web1.0 / web2.0 页面标题、[web_server.py](https://github.com/weihong-su/miniQMT/blob/main/web_server.py)、`web2.0/vite.config.ts` 均通过 `%MINIQMT_RELEASE_VERSION%` 占位符注入，避免版本号分散硬编码。
- **baostock API Key 支持**：新版 baostock(0.9.x) 收紧访问后，登录前经 `set_API_key` 传入 `BAOSTOCK_API_KEY`（环境变量，默认空则匿名访问）。

### Changed
- **baostock 接入规范化**：依赖约束由 `==0.9.1` 放宽为 `>=0.9.1`；新增登录超时 `BAOSTOCK_LOGIN_TIMEOUT=5s`、连续失败冷却 `BAOSTOCK_RETRY_COOLDOWN=300s`、失败阈值 `BAOSTOCK_MAX_CONSECUTIVE_FAILURES=3`；`ENABLE_BAOSTOCK_STOCK_NAME_LOOKUP` / `ENABLE_BAOSTOCK_HISTORY_DATA` 默认关闭，历史行情默认改走 Mootdx，避免无人值守时外部接口反复报错。
- **web1.0 下单日志**：改为定时刷新并优化视觉样式与可读性。
- **Web 页面标题**：统一附带发布版本号（如「交易监控面板 - miniQMT v3.4.0」）。

### Fixed
- 完善行情源健康检测验证逻辑，减少误判。
- 优化止损委托阻断处理，避免异常委托状态阻塞后续止损。
- 网格实盘成交记录延迟到成交回报到达后再登记，避免委托未成交即入账。
- 修复 MkDocs strict 模式构建告警。

### Docs
- 无人值守文档新增「数据库维护与日志轮转」章节；配置参考补充自动操作三层开关、baostock 接入、数据库维护与保留天数、日志轮转参数。

### Database
- 数据库维护任务按保留策略清理追加型历史表：`trade_records`（`TRADE_RECORD_RETENTION_DAYS=1095`，3 年）、`grid_trading_sessions`（`GRID_SESSION_RETENTION_DAYS=365`，仅非 active）、`premarket_sync_history`（365）、`config_history`（365）、autobuy `decision_log`（`AUTOBUY_DECISION_LOG_RETENTION_DAYS=90`）。

## [3.3.0] - 2026-06-27

### Added
- 新增自动买入模块文档：说明 `miniqmt_autobuy` 独立进程、候选池筛选、大盘指数门禁、防重风控、调度与复盘库。
- 新增行情源健康评分文档：说明轻量内存版评分、不落库、观察模式、配置项和 `/api/market/health` 快照接口。

### Changed
- 同步 README、AGENTS、CLAUDE 和在线文档到当前代码：补充 `miniqmt.bat` 自动买入菜单 `[j]`-`[m]`、`--all-with-fast` 回归测试参数、当前测试分组规模、网格真实账本详情接口 `/api/grid/ledger/<session_id>`。
- 更新 Web/API 文档的网关能力边界：`/api/grid/sessions` 在 xtquant_manager 网关模式下支持只读兼容返回，网格写操作和账本详情仍需 Flask 直连。
- 更新配置与架构文档：补充历史数据同步节流/超时参数、自动买入独立配置文件和独立进程定位。
- 同步网格启动条件：`GRID_REQUIRE_PROFIT_TRIGGERED` 当前默认值为 `False`，持仓个股默认不再要求先触发首次止盈即可启动网格；设为 `True` 时仍作为保守安全阀。
- 更新测试统计口径：当前配置 29 个测试组（含 `fast`）、89 个模块引用、64 个唯一测试模块；最近 `--all` 回归为 28 组、65 个模块引用、961 个用例 100% 通过。

## [3.2.0] - 2026-06-13

> 本版本聚焦**网格交易实盘化**：以「成交回报为准」重构订单闭环，新增对手价下单、涨跌停/停牌防护、启动对账与真实盈亏账本，使网格策略可安全用于实盘。

### Added
- **实盘委托成交确认**（`GRID_CONFIRM_LIVE_ORDER_BY_DEAL`，默认 `True`）：实盘下单后先登记待确认委托（`grid_orders` 表），等成交回报 `handle_deal_callback` 到达再落账并重建网格；支持部分成交累计、`trade_id` 幂等去重、单事务落账
- **对手价下单**（`GRID_USE_COUNTERPARTY_PRICE`，默认 `True`）：买取卖三价 / 卖取买三价提高成交概率；`GRID_COUNTERPARTY_BUY_PRICE_BUFFER_RATIO`（2%）按风险价预占资金防止突破 `max_investment`
- **涨跌停 / 停牌防护**（`GRID_ENABLE_PRICE_LIMIT_GUARD`，默认 `True`）：下单前 `_check_tradable` 检查盘口，封板/停牌跳过本次交易，涨跌停价获取失败 fail-open；容差 `GRID_PRICE_LIMIT_EPS`
- **信号执行前复核**：信号有效期（`GRID_SIGNAL_MAX_AGE_SECONDS`，60s）+ 价格漂移（`GRID_SIGNAL_MAX_PRICE_DRIFT_RATIO`，1%）双重校验，丢弃陈旧/失真信号
- **启动对账（startup reconcile）**：系统重启从 `grid_orders` 恢复未完成委托，查询券商当日成交/委托补记差异、关闭终态委托
- **对手方资金/持仓预留**：下单计划扣除待成交委托占用，防止锁外窗口期重复下单超额
- **真实盈亏账本**：新增 `grid_lots`（买入批次）+ `grid_lot_matches`（初版 FIFO 卖出配对，当前已在 Unreleased 改为 LIFO 最近优先）表；`get_pnl_snapshot` 统一盈亏视图按数据可用性分级（`ledger_true_pnl` / `memory_true_pnl` / `cash_flow_legacy` / `fallback_market_value_ratio`），含已实现/未实现盈亏与降级标记
- **网格盈亏前端面板**：web1.0 / web2.0 新增 `GridStatusPanel`，展示利润来源、降级提示，Web API 网格端点返回 `pnl_snapshot`
- **清仓残留持仓告警限频**（`CLEARED_POSITION_WARNING_INTERVAL`，默认 1800s）：券商盘后仍返回已清仓行时降噪，超频降为 DEBUG

### Changed
- `miniqmt.bat` 调整 Python 虚拟环境优先顺序
- 精简部分报错信息（`easy_qmt_trader`）
- 加固股票名称解析（`data_manager` / `position_manager` / `xtquant_manager.client`），提升名称缺失/异常时的健壮性

### Fixed
- 防止陈旧的首次止盈半仓回撤误触发（`guard stale half take-profit pullbacks`）
- 避免盘后已清仓持仓的成本价告警刷屏

### Database
- 新增表：`grid_orders`、`grid_lots`、`grid_lot_matches`
- `grid_trading_sessions` 新增字段：`risk_level`、`template_name`、`total_buy_volume`、`total_sell_volume`（均带自动迁移）
- `grid_orders` 新增字段：`reserved_price`（带自动迁移）

### Docs
- 网格交易文档新增「实盘交易机制」章节；配置参考补充网格实盘参数；数据库文档更正表名 `grid_sessions` → `grid_trading_sessions` 并补全订单/账本表

## [3.1.0] - 2026-05-30

### Added
- **web2.0 启动模式选择**: `miniqmt.bat` 菜单 [7]/[8]/[9] 启动前可选 `web1.0` (Flask :5000 起) 或 `web2.0` (xtquant_manager :8888)，偏好持久化到 `data/.web_mode`
- **xtquant_manager 内嵌 web2.0**: 网关启动后 `http://localhost:8888/` 直接托管 `web2.0/dist/`（静态文件 + SPA fallback），菜单 [g] 打开浏览器
- **Flask 兼容 API 端点**（`xtquant_manager/server.py`）使 web2.0 前端无需改造即可在网关模式下运行：
  - `GET /api/status` `/api/positions` `/api/positions-all` `/api/connection/status` `/api/config` `/api/trade-records`
  - `GET /api/accounts` — 无 Token 公开列出账号 ID，互联网只读用户也能正确发现多账号（无 token 时不再退化为只显示第一个账号）
  - 字段映射对齐 Flask 顶层格式，QMT 实时数据 + SQLite 持久化元数据合并，账号隔离基于 `X-Account-Id` 请求头
- **网关模式动态止盈状态查询**: `/api/v1/stop-profit/status` `/config` `/toggle`，复用 `position_manager` 算法
- **网关模式只读防护**: web2.0 在 `isGatewayMode()` 时禁用自动操作总开关/动态止盈控制/参数保存/模拟买入/初始化按钮，显示「🔒 网关模式 · 只读监控+下单」徽章
- **连接设置面板**: 顶部齿轮 ⚙ 进入，支持「网关模式 / 直连模式」切换、网关地址 + API Token 配置、测试连接（8s 超时 + 非 JSON 检测 + 详细错误）、HTTPS Mixed Content 警告、保存后自动 `discoverAccounts()` 刷新账号下拉
- **iPhone / 移动端适配**: 持仓表格 `overflow-x-auto` 横向滚动 + `min-w-[800px]` 保表头不挤压；HeaderBar 按 `sm:` 断点响应式堆叠；竖向单列布局 + 止盈列改图标
- **Vercel 一键远程部署**: 根目录新增 `vercel.json` 指定 web2.0 构建命令与输出目录，配合 Cloudflare Tunnel 实现「Vercel 前端 + Windows QMT 后端」远程部署
- **绑定地址与客户端地址分离**：`XQM_DEFAULT_HOST=0.0.0.0` (绑定) + `XQM_CLIENT_HOST=127.0.0.1` (客户端目标)；启动菜单同时显示「本机 URL」+「局域网 URL」方便从其他设备访问

### Changed
- **web2.0 交易日志**: 网关模式从「QMT 当日成交/委托」改为优先读 SQLite `trade_records` 表（与 web1.0 同源，含名称/时间/策略/历史买卖），SQLite 无记录时回退 QMT
- **web2.0 持仓字段补齐**: 改用 SQLite 持久化数据替代 xtdata/公式估算，网关模式下持仓名称、建仓日期、止损价能正确显示
- **web2.0 盈亏颜色按 A 股习惯**: 红涨绿跌（与原默认的绿涨红跌相反）
- **web2.0 监控/止盈按钮文案**: 「开始监控/停止监控」「开启动态止盈/禁用动态止盈」（替代 ON/OFF）
- **web2.0 配置面板布局**: 4 列网格 + 标签右对齐 + 紧凑输入框；买入操作整合到 HeaderBar 第 3 行（移除独立 BuyPanel 卡片）
- **web1.0 默认只绑本机**: `WEB_SERVER_HOST=127.0.0.1`，web2.0/xtquant_manager 负责对外（避免 web1.0 误暴露完整写操作 API 到公网）
- **`xtquant_manager` 健康检查日志降噪**: 减少非异常情况下的常规健康检查输出

### Fixed
- **web2.0 网关模式涨跌幅恒为 0**: 持仓裸代码缺少市场后缀（`.SZ`/`.SH`），网关请求 tick 失败，补齐后缀
- **web1.0 持仓不刷新**: SSE `onmessage` 因 `wasSimulationMode` 未定义崩溃，导致后续推送被中断
- **web2.0 连接设置变更后账号下拉未刷新**: 切换网关 URL/Token 后自动调用 `discoverAccounts()` 同步真实账号列表
- **web2.0 互联网用户只能看到第一个账号**: 无 Token 时无法访问 `/api/v1/accounts`，新增公开 `/api/accounts` Flask 兼容端点
- **web2.0 盈亏比例显示错误**: `fmtPercent` 多乘 100（小数→百分比转换），与 web1.0 对齐
- **web2.0 持仓价格精度**: 统一 2 位小数（原 3 位），与 A 股报价精度一致
- **launcher 0.0.0.0 不能作客户端目标**: 健康检查、菜单 UI 打开统一改用 `127.0.0.1`

### Docs
- 新增「Web 前端（web1.0 / web2.0）」章节：双模式架构、网关能力边界、连接设置、启动菜单、Vercel 远程部署 — 见文档站
- `web-api.md` 标注哪些端点在 xtquant_manager 网关模式下可用
- `CLAUDE.md` 同步 Web 双模式架构说明（commit 7035354d）

## [3.0.0] - 2026-05-24

### Added
- **XtQuantManager 动态止盈止损**: 网关模式下独立运行的止盈止损后台监控 (`xtquant_manager/stop_profit.py`)
  - 直接复用 `position_manager.py` 中已验证的止损/首次止盈/动态止盈算法
  - 信号去重（60s 窗口）+ 自动下单（实盘 xttrader 接口）
  - API 端点：`/api/v1/stop-profit/status`、`/config`、`/toggle`
- **web2.0 Vue3 前端**: 全新的持仓管理 Web 界面 (`web2.0/`)
  - Vue3 + Vite + TypeScript + Tailwind CSS + Pinia 状态管理
  - PWA 支持 (vite-plugin-pwa)，可安装到桌面离线使用
  - 双后端兼容：Flask (web1.0 API) + xtquant_manager (v1 API)
  - 多账户切换、连接设置面板、SSE 实时推送 + 智能轮询
  - 止盈止损开关（与 web1.0 `firstProfitSellEnabled` 对齐）
  - Vercel 一键部署支持 (见 `web2.0/VERCEL_DEPLOY.md`)
- **miniqmt.bat 新增 XtQuantManager 菜单**: [d] 启动 [e] 停止 [f] 状态 [g] UI [h] 重启 [i] 日志
- 统一文档体系：MkDocs + mkdocstrings（docstring 自动抽取）+ include-markdown（CHANGELOG 引用）+ 本地热重载 `start_docs.bat`
- 文档构建依赖独立到 `utils/requirements-docs.txt`，不污染运行环境
- GitHub Actions 部署工作流加 `if: false` 守门，未来开启只需删除一行

### Changed
- `docs/site/` 作为唯一 markdown 源，根目录 `CHANGELOG.md` 作为变更日志唯一真源
- web2.0 配置百分比字段统一精度到 2 位小数，金额字段整数显示
- 界面全面视觉升级：渐变背景、毛玻璃顶栏、分层阴影卡片、动画模态框、盈亏色条

### Security
- **隐私安全加固**: `Methods.py` 硬编码 Pushplus Token 改为 `PUSHPLUS_TOKEN` 环境变量
- `web2.0/src/api/accounts.ts` 默认账户去真实 ID，改为空占位符
- `.gitignore` 新增 `web2.0/dist/` 和 `web2.0/node_modules/`
- 文档示例中的真实账号 ID 替换为 `55009640` 等虚构 ID

---

## [2.0.0-Beta] - 2026-03-28

### Added
- 完整回归测试框架：23 组 × 67 模块 × 1170 个测试用例，全部通过（100%）
- 网格交易全区间覆盖测试（114 个用例，A–K 11 个套件）
- XtQuantManager HTTP 网关：多账号注册 + 健康检查 + Fail-Safe 重连
- 非 XtQuantManager 场景的 QMT 重连机制（事件 / 循环 / 主动探测三条路径）
- 盘前 9:25 自动重新初始化 xtquant 接口

### Fixed
- baostock 登录无超时保护导致监控线程阻塞约 168 秒
- 止盈触发标志写入后 positions_cache 未失效导致 10 秒窗口内重复信号
- `qmt_connected` 初始化后永不更新（永久假健康）
- `easy_qmt_trader` 缺少 `reconnect_xttrader()` 方法
- 线程监控未注册 `heartbeat_check`，无法感知 API 断连

### Changed
- 线程注册统一使用 `lambda` 获取最新对象引用，避免重启后引用失效

---

## [1.0.0] - 2026-02-03

### Added
- 首个稳定版本
- 双层存储架构（内存数据库 + SQLite 持久化）
- 信号检测与执行分离设计
- 动态止盈止损策略（最高浮盈 5%/10%/15%/20%/30% 五档）
- 网格交易完整实现
- Web 前端实时监控界面（Flask + SSE）
- 多线程协同 + 线程自愈机制
- 模拟交易模式（无需 QMT 即可验证策略）
- 回归测试框架基础设施

[Unreleased]: https://github.com/weihong-su/miniQMT/compare/v3.8.6...HEAD
[3.8.6]: https://github.com/weihong-su/miniQMT/compare/v3.8.5...v3.8.6
[3.8.5]: https://github.com/weihong-su/miniQMT/compare/v3.8.4...v3.8.5
[3.8.4]: https://github.com/weihong-su/miniQMT/compare/v3.8.2...v3.8.4
[3.8.2]: https://github.com/weihong-su/miniQMT/compare/v3.8.1...v3.8.2
[3.8.1]: https://github.com/weihong-su/miniQMT/compare/v3.8.0...v3.8.1
[3.8.0]: https://github.com/weihong-su/miniQMT/compare/v3.7.0...v3.8.0
[3.7.0]: https://github.com/weihong-su/miniQMT/compare/v3.6.0...v3.7.0
[3.6.0]: https://github.com/weihong-su/miniQMT/compare/v3.5.0...v3.6.0
[3.5.0]: https://github.com/weihong-su/miniQMT/compare/v3.4.0...v3.5.0
[3.4.0]: https://github.com/weihong-su/miniQMT/compare/v3.3.0...v3.4.0
[3.3.0]: https://github.com/weihong-su/miniQMT/compare/v3.2.0...v3.3.0
[3.2.0]: https://github.com/weihong-su/miniQMT/compare/v3.1.0...v3.2.0
[3.1.0]: https://github.com/weihong-su/miniQMT/compare/v3.0.0...v3.1.0
[3.0.0]: https://github.com/weihong-su/miniQMT/compare/V2.0.0-Beta...v3.0.0
[2.0.0-Beta]: https://github.com/weihong-su/miniQMT/compare/V1.0.0...V2.0.0-Beta
[1.0.0]: https://github.com/weihong-su/miniQMT/releases/tag/V1.0.0
