# 大QMT能力探索与调试经验

本文记录 2026-07-12 对 `QMT_trade_executor.py` 的实机调试结论，用于后续开发和排障。

## 当前确认的能力边界

| 项目 | 结论 |
|------|------|
| 推荐入口 | 模型交易 `init(ContextInfo)` 前台阻塞轮询；`handlebar(ContextInfo)` 作为 fallback；top-level 只用于本地/定时运行兜底 |
| 可用内置交易符号 | `get_trade_detail_data`、`passorder`、`cancel` 位于 `globals()` |
| `ContextInfo` 能力 | 主要是行情、画图、订阅、回测上下文；未发现 `query_stock_asset`、`order_stock`、`cancel_order` 等交易方法 |
| 只读快照首选 | `xttrader + StockAccount` |
| VBA 快照定位 | fallback；休盘或账号上下文不匹配时可能返回空 |
| 下单首选 | `xttrader.order_stock(StockAccount, ...)` |
| 市价单参数 | `price_type=LATEST_PRICE`，`price=0` |

实测日志中的关键证据：

```text
QMT symbol get_trade_detail_data callable: globals=True builtins=False ContextInfo=False
QMT symbol passorder callable: globals=True builtins=False ContextInfo=False
QMT symbol cancel callable: globals=True builtins=False ContextInfo=False
QMT symbol order_stock callable: globals=False builtins=False ContextInfo=False
```

## 快照数据经验

1. 休盘时间不能用“资产字段为 0”直接判断账户为空。
2. `query_stock_positions(StockAccount)` 可能返回真实持仓，但 `query_stock_asset` 的 `total_asset`、`cash` 仍为 0。
3. 有些持仓对象会出现 `volume=0` 的伪记录，必须过滤，否则策略端会误判存在持仓。
4. 休盘时 `market_price` 可能为 0，但 `market_value` 有值，此时应按 `market_value / volume` 反推参考价。
5. 如果 `total_asset<=0` 但有持仓市值，快照层应兜底写 `available + market_value`，避免 Web 和策略端误判资产清零。

当前快照验证样例：

```json
{
  "account_id": "TEST_ACC_2",
  "source": "xttrader",
  "total_asset": 13356.0,
  "market_value": 13356.0,
  "positions": [
    {
      "stock": "600509.SH",
      "volume": 1800,
      "market_price": 7.42,
      "market_value": 13356.0
    }
  ]
}
```

## 代码开发避坑

1. **不要在 QMT 主循环里无节制写日志**  
   `handlebar()` 触发频率可能远高于预期。日志应按时间间隔输出摘要，例如 `tick ok accounts=2 ticks=...`。

2. **所有外部交易 API 都要有超时保护**  
   `connect()`、`subscribe()`、`query_*()` 都可能卡住。调用应放入短线程并 `join(timeout)`，超时后降级或跳过本轮。

3. **不要把 `LATEST_PRICE` 当成第 7 个参数**  
   `order_stock` 参数应是 `account, stock_code, order_type, order_volume, price_type, price, strategy_name, order_remark`。市价单应设置 `price_type=LATEST_PRICE`、`price=0`。

4. **下单、撤单、查询尽量传 `StockAccount`**  
   只读查询已验证 `StockAccount` 成功；字符串账号可保留为 fallback，但不应作为首选。

5. **大QMT脚本要保持 ASCII-only**  
   QMT 策略编辑器可能按 GBK 保存，非 ASCII 源码容易触发编码问题。脚本内部注释和字符串尽量英文，中文经验沉淀到 Markdown 文档。

6. **不要重发 `processing/` 残留订单**  
   executor 中断后，残留订单可能已经送柜台。恢复策略应写 `error` 回执并清理，不能移回 `pending/` 重发。

7. **策略端要先看心跳再下单**  
   大QMT离线时，`QmtIpcTrader` 应快速失败，不应等待完整 `QMT_IPC_ORDER_TIMEOUT`。

8. **不要把“策略状态=运行中”误认为脚本会持续 tick**
   光大金阳光 QMT 的模型交易页面中，策略表格可以显示“运行中”，但在非交易日或无新 bar 时，实测可能只执行一次 `init()` / `handlebar()`。典型日志是每次手动运行只出现一次 `tick ok ... ticks=1`，随后 `heartbeat.json` 不再刷新。

9. **不要依赖后台线程在模型交易容器里保活**
   实测大QMT策略回调返回后可能回收脚本创建的后台线程，即使线程设置为 `daemon=False` 也不可靠。最终口径是：在检测到 `get_trade_detail_data` / `passorder` / `cancel` 等 QMT 注入符号后，`init()` 进入前台阻塞 `_foreground_loop()`，由这个前台循环持续刷新心跳、扫描订单和触发快照。top-level worker 只给本地导入、定时运行模式或特殊调试场景兜底。

10. **避免 top-level worker 与前台循环重复运行**
    曾出现 `worker start requested by top-level` 与 `foreground loop started by init` 同时存在，导致多个循环抢写 `heartbeat.json` 和重复触发快照。正式版应在 QMT 注入环境中默认关闭 top-level worker；正常日志应看到 `foreground loop started by init ...`，不应再新增 `worker start requested by top-level`。

11. **Windows 文件替换会遇到瞬时锁**
    多个旧实例或多线程同时写同一个 `heartbeat.json` 时，Windows 可能报 `WinError 32` / `Permission denied`。原子写临时文件名必须包含 `pid + thread_id + timestamp`，且 `os.replace()` 需要短重试。若日志仍出现旧格式 `heartbeat.json.<pid>.tmp`，说明大QMT里还有旧脚本实例残留，需彻底停止策略或重启大QMT客户端。

12. **优先用文件心跳判断 executor 是否真的活着**
   大QMT界面上的“运行中”只能说明策略已加载/启动，不能证明 IPC 轮询仍在工作。排障时以 `C:\QuantIPC\{account}\status\heartbeat.json` 修改时间为准；若心跳年龄超过 `QMT_IPC_HEARTBEAT_MAX_AGE`，策略端应视为离线。

13. **兼容 PowerShell 写出的 UTF-8 BOM**
   Windows PowerShell 的 `Set-Content -Encoding UTF8` 可能写入 BOM。旧版 executor 用 `encoding="utf-8"` 读取订单时会报 `Unexpected UTF-8 BOM`，导致文件先卡在 `processing/`，再由 120 秒孤儿恢复写 `done/error`。正式版读 IPC JSON 应使用 `utf-8-sig`，且坏 JSON 应立即写 `done/error`，不要等孤儿恢复。

14. **QMT 拒单不一定进入委托查询**
   空仓卖出实测 `order_stock` 直接返回 `-1`，executor 应立即写 `done/rejected`。若返回正 `seq` 后再在 `query_all_orders()` 中看到废单状态，应把 `order_status=57` 映射为 `rejected`，避免误判为 `cancelled_timeout`。

## 最新验证口径（2026-07-12）

成功运行时应同时满足：

```text
foreground loop started by init pid=... interval=1.000s root=C:\QuantIPC
tick ok accounts=2 ticks=持续递增
[account] snapshot xttrader: total=... positions=...
```

文件状态应表现为：

- `C:\QuantIPC\{account}\status\heartbeat.json` 持续刷新到当前秒级。
- `C:\QuantIPC\{account}\status\account.json` 至少每 30 秒左右尝试更新一次；休盘时个别字段可能为 0，但持仓市值可用于兜底。
- 日志不应继续新增 `worker start requested by top-level`；如果仍出现，通常是旧实例未清理干净。

低风险订单链路已验证：

- 预取消链路：先写 `cancel/cancel_<order_id>.json`，再写 `orders/pending/ord_<order_id>.json`，executor 在连接交易 API 前写 `done/cancelled`，`pending/processing/cancel` 均清空，日志无 `order seq=`。
- BOM 订单文件：PowerShell BOM 文件会被新版 `_load_json(... utf-8-sig)` 正常解析；坏 JSON 会立即写 `done/error`。
- 空仓卖出拒单：账号已脱敏，空仓卖出 `000001.SZ` 100 股，真实调用 `order_stock` 后返回 `-1`，executor 写 `done/rejected`，`filled_volume=0`。

## 后续调试建议

1. 先做只读验证：心跳、两个账号 `account.json`、`source=xttrader`、持仓字段是否可信。
2. 若看到旧临时文件名或重复 `tick ok` 计数交错，先停止策略并重启大QMT，确认只剩一个前台循环。
3. 再做低风险下单验证：优先选择不会成交的限价单，确认 `pending -> processing -> done` 与撤单链路。
4. 有效委托号 + 撤单链路建议等交易时段再测：使用极低成交概率限价单，拿到正 `seq` 后立即写 cancel 文件，确认 `inflight cancel` 和最终回执。
5. 最后才做实盘有效价格验证，并保持单账号、单订单、最小数量。
