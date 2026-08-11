# QMT order_id 匹配调试与加固

本文记录 2026-08-11 对 `25105132 / 000799 / 100股` 的实盘窄接口验证结果，以及主程序中 `seq -> order_id` 匹配的加固原则。后续排查“异步下单后拿不到真实委托号”“卖出重复下单”“委托无法撤单”等问题时，优先按本文流程复现。

## 背景

miniQMT 默认使用 `order_stock_async()` 下单。该接口同步返回的是请求序号 `seq`，真实券商委托号 `order_id` 要等 QMT 异步回调 `on_order_stock_async_response()` 到达后才能建立映射。

2026-08-11 09:30 前后，自动止盈止损开启后出现运行告警，核心风险集中在“提交 QMT 卖出订单后未可靠匹配真实 `order_id`”。如果程序把“已提交但未确认 order_id”的订单当作失败继续重试，就可能造成同股同方向重复卖出委托。

## 实盘确认的 QMT 行为

本次通过主程序 Flask Web 窄接口 `/api/debug/order-probe-000799` 验证，避免绕开主程序连接、callback、订阅和账号绑定逻辑。

| 场景 | 实盘结果 |
|------|----------|
| 午间休盘高价限价卖出后撤单 | `order_stock_async()` 返回 `seq=55`，异步回报返回 `order_id=940572674`，委托状态 `50` 后撤单，最终 `54=已撤`，成交量 `0` |
| 开盘后真实成交 | `order_stock_async()` 返回 `seq=1277`，异步回报返回 `order_id=940572675`，成交回报 `traded_id=76160104000056806542`，终态 `56=已成`，成交价 `41.54`，成交量 `100` |
| 重启后再次高价限价卖出撤单 | `seq=36 -> order_id=940572677`，撤单 `cancel_seq=44`，最终 `54=已撤`，成交量 `0` |

由此确认：

- `order_stock_async()` 的返回值是 `seq`，不能当成撤单或成交确认使用的 `order_id`。
- `on_order_stock_async_response()` 是最快、最准确的 `seq -> order_id` 来源。
- `query_stock_orders()` 能查到当日委托，含已撤 `54`、已成 `56`、已报 `50`。
- `query_stock_trades()` 能查到真实成交，成交回报与委托查询中的 `order_id` 一致。
- QMT 会截断或改写 `order_remark`，例如 `web_probe_sell-fill_1786425835` 回报为 `web_probe_sell-fill_178`。
- `price_type=5, price=0.0` 提交后，QMT 委托列表中的 `price` 会落成实际委托价，例如 `41.54`。

## 主程序加固原则

### 映射优先级

`_get_real_order_id()` 的解析顺序必须是：

1. 先等 `order_id_map` 中的 `seq -> order_id` 回调映射。
2. 回调超时后，再按股票、方向、数量、策略、时间窗口查询当日委托和成交反查。
3. 若唯一命中，回填 `order_id_map`，后续撤单、成交确认和日志都使用真实 `order_id`。
4. 若多候选或查询失败，保守返回 `None`，并由执行器进入 unknown 冷却，禁止重复发单。

### 字段匹配口径

- 股票代码统一按 6 位裸代码匹配，兼容 `000799` 与 `000799.SZ`。
- 方向字段兼容 `23/24`、`23.0/24.0`、中文买卖方向。
- 数量优先匹配委托数量；只有成交列表没有委托数量时，才用成交数量做部分成交兜底。
- `order_remark` 不作为硬过滤条件，只记录不一致原因。
- `strategy_name` 精确匹配优先；若 QMT 截断较长策略名，允许长前缀匹配；多候选仍保守失败。
- 仅 `price_type=11` 固定价委托用价格辅助过滤。`price_type=5` 等非固定价委托不使用提交前价格过滤，因为 QMT 会写入实际委托价。
- 报单时间兼容 Unix 秒、`HHMMSS`、`YYYYMMDDHHMMSS`、字符串时间；匹配窗口由配置控制。

### unknown 委托保护

当 QMT 返回正 `seq`，但主程序未能及时拿到真实 `order_id` 时：

- 该订单视为“券商侧可能已接收”，不能继续重试下单。
- 按同股票、同方向进入 `ASYNC_ORDER_UNKNOWN_COOLDOWN_SECONDS` 冷却。
- 如果迟到 callback 后续补上 `seq -> order_id`，应解除冷却，并补齐最小 `order_cache`；若有策略信号上下文，也补入 `pending_orders`，让成交/撤单回调能继续闭环。

## 相关配置

| 配置 | 默认值 | 说明 |
|------|--------|------|
| `USE_SYNC_ORDER_API` | `False` | 默认用异步下单，返回 `seq` |
| `ASYNC_ORDER_ID_WAIT_TIMEOUT_SECONDS` | `2.0` | 等待 callback 映射的时间 |
| `ASYNC_ORDER_QUERY_FALLBACK_TIMEOUT_SECONDS` | `30.0` | callback 未到时，查询委托/成交反查的最长时间 |
| `ASYNC_ORDER_QUERY_MATCH_PRE_WINDOW_SECONDS` | `5.0` | 允许匹配下单前小窗口，兼容本机与 QMT 时间差 |
| `ASYNC_ORDER_QUERY_MATCH_POST_WINDOW_SECONDS` | `30.0` | 允许匹配下单后小窗口，避免误配历史委托 |
| `ASYNC_ORDER_UNKNOWN_COOLDOWN_SECONDS` | `300` | 正 `seq` 未确认时，同股同方向暂停重复提交 |
| `QMT_ORDER_ID_MAP_TTL_SECONDS` | `86400` | `seq -> order_id` 映射保留时间 |
| `QMT_ORDER_ID_MAP_MAX_ENTRIES` | `4096` | `order_id_map` 最大键数量，`int/str` 双键计入 |

## Web 窄接口验证

窄接口仅用于实盘诊断，固定限制为 `25105132 / 000799 / 100股`，并要求：

- `ENABLE_SIMULATION_MODE=False`
- `ENABLE_DEBUG_LIVE_SELL_TEST_API=True`
- `QMT_API_TOKEN` 非空
- 主程序已启动并连接 QMT

只读检查：

```powershell
C:\Users\PC\anaconda3\envs\python39\python.exe scripts\probe_order_id_matching.py --base-url http://127.0.0.1:50000 --mode preflight
```

高价限价卖出后撤单：

```powershell
C:\Users\PC\anaconda3\envs\python39\python.exe scripts\probe_order_id_matching.py --base-url http://127.0.0.1:50000 --mode sell-cancel --confirm SELL_CANCEL_100_000799_25105132 --use-suggested-price
```

真实成交验证必须额外确认，会真实卖出 100 股：

```powershell
C:\Users\PC\anaconda3\envs\python39\python.exe scripts\probe_order_id_matching.py --base-url http://127.0.0.1:50000 --mode sell-fill --confirm SELL_FILL_100_000799_25105132 --allow-fill
```

每次运行会写入：

```text
logs/qmt_order_probe/webapi_YYYYMMDD_HHMMSS_<mode>_000799_25105132.jsonl
```

重点查看事件：

- `submit.sell_return`：QMT 同步返回的 `seq`
- `callback.async_order_response`：真实 `order_id`
- `resolve.order_id`：最终解析来源，通常应为 `order_id_map`
- `callback.stock_order`：委托状态变化，`50=已报`、`54=已撤`、`56=已成`
- `callback.cancel_response`：撤单响应，`cancel_result=0` 表示成功
- `callback.stock_trade`：成交回报
- `snapshot.before.000799` / `snapshot.after.000799`：目标股票委托、成交、持仓快照

## 9:30 问题场景的覆盖结论

本次加固覆盖 2026-08-11 09:30 前后暴露的核心问题：卖出委托已经提交到 QMT，但主程序无法可靠把 `seq` 匹配为真实 `order_id`，进而产生告警或重复下单风险。

现在的闭环是：

1. 主程序下单前确认 trade push 可用。
2. 下单后优先等待 callback 映射。
3. callback 未到时主动查当日委托和成交反查。
4. 仍不确定时停止重试，标记 unknown 冷却。
5. 迟到映射到达后解除 unknown，并补齐订单缓存。
6. 成交以 `on_stock_trade` / `query_stock_trades` 为准，撤单以委托终态 `54` 和撤单回报为准。

因此，针对“自动止盈止损触发卖出后拿不到真实 `order_id`”这一类问题，当前代码已具备防重复、可反查、可撤单、可成交确认的保护链路。
