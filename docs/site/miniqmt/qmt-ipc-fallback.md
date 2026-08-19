# 大QMT文件 IPC Fallback

大QMT文件 IPC 是 `easy_qmt_trader` 直连失效时的交易降级通道：miniQMT 策略端把订单写入 `C:\QuantIPC\{account_id}\orders\pending`，大QMT 内置 Python 脚本 `QMT_trade_executor.py` 读取后用大QMT授权执行下单，并把账户快照和成交回执写回共享目录。

## 适用场景

| 场景 | 是否适用 |
|------|----------|
| 券商收紧 miniQMT `xttrader` 权限 | 适用 |
| 大QMT客户端已登录并具备交易授权 | 适用 |
| 多账号同机隔离运行 | 适用 |
| 高频、打板、tick级抢单 | 不适用 |

## 已验证能力

实机调试确认：

- 模型交易模式会把 `get_trade_detail_data`、`passorder`、`cancel` 注入到 `globals()`。
- `ContextInfo` 主要提供行情和上下文能力，没有发现 `order_stock`、`query_stock_asset`、`cancel_order` 等交易方法。
- `xttrader + StockAccount` 可用于只读快照，并作为下单首选参数形式。
- 休盘时资产字段可能为 0，但持仓仍可返回，需要快照层做数据清洗。
- 光大金阳光 QMT 的“模型交易”入口在非交易日可能只触发一次策略回调；当前 executor 在 `init()` 中进入前台循环，持续轮询 IPC。
- 大QMT 策略容器可能在回调返回后回收后台线程，因此不能把后台 worker 当作主要保活方案。
- PowerShell 写出的 UTF-8 BOM 订单文件可正常解析；坏 JSON 会立即写 `done/error`，不再等待孤儿恢复。
- 空仓卖出等柜台拒单场景已验证：`order_stock` 直接返回无效委托号时写 `done/rejected`；委托查询返回 `order_status=57` 时也映射为 `rejected`。

## 目录约定

```text
C:\QuantIPC\
  TEST_ACC_2\
    config.json
    status\
      heartbeat.json
      account.json
    orders\
      pending\
      processing\
      done\
      done_archive\
    cancel\
```

`config.json` 由策略端创建，至少包含：

```json
{
  "account_id": "TEST_ACC_2",
  "account_type": "STOCK",
  "qmt_path": "C:/QMT1/userdata_mini",
  "ipc_secret": ""
}
```

`ipc_secret` 来自策略端环境变量 `QMT_IPC_SECRET`。为空时保持原本地信任模型；非空时，策略端写入每个订单 JSON，大 QMT executor 校验失败会写 `done/error`，不会连接交易 API。跨机器共享目录或多人共用 Windows 主机时建议设置强随机值。

## 快照口径

`account.json` 由大QMT端写入。当前口径：

- `source` 标识来源，优先 `xttrader`，失败时 fallback 到 `vba`。
- 过滤 `volume<=0` 的伪持仓。
- `market_price=0` 且 `market_value>0` 时按 `market_value / volume` 反推参考价。
- `total_asset<=0` 但有市值时，兜底为 `available + market_value`。

示例：

```json
{
  "timestamp": "2026-07-12 11:56:40",
  "account_id": "TEST_ACC_2",
  "source": "xttrader",
  "total_asset": 13356.0,
  "available": 0.0,
  "market_value": 13356.0,
  "positions": [
    {
      "stock": "600509.SH",
      "volume": 1800,
      "available": 1800,
      "cost": 6.914,
      "market_price": 7.42,
      "market_value": 13356.0
    }
  ]
}
```

## 订单回执口径

大QMT端处理订单时采用“先文件状态、后交易 API”的顺序，尽量把不确定性收敛在 `done/` 回执里：

- `cancel/cancel_<order_id>.json` 如果在下单前已存在，executor 直接写 `done/cancelled`，不会连接交易 API。
- `orders/pending/` 中的 JSON 使用 `utf-8-sig` 读取，兼容 PowerShell `Set-Content -Encoding UTF8` 产生的 BOM。
- 订单 JSON 无法解析时立即写 `done/error`，并清理 `processing/`，不再等默认 120 秒的残留恢复。
- `order_stock` 返回空值、负数或 0 时写 `done/rejected`。
- `query_all_orders()` 返回 QMT 废单状态 `57` 时写 `done/rejected`，避免误判为超时撤单。
- 查询委托/成交时保留 `status_msg`、`order_remark`、`strategy_name` 等字段，策略端展示和回调可继续识别原始策略标签。
- `filled` / `partial` / `partial_cancelled` 才触发成交回调；`rejected` / `cancelled` 不触发成交回调，避免废单或撤单被误落账。

## 运行与日志

推荐在大QMT中使用模型交易入口部署 `QMT_trade_executor.py`。若界面里没有“定时运行”选项，直接使用“模型交易/实盘/运行”，不要勾选“启动本地 python”。正常日志应类似：

```text
[11:56:39.900] foreground loop started by init pid=12345 interval=1.000s root=C:\QuantIPC
[11:56:40.467] [TEST_ACC_2] snapshot xttrader: total=13356 positions=1 via asset=StockAccount pos=StockAccount
[11:56:40.482] tick ok accounts=2 ticks=1 worker=False
```

如果看到连续高频 `tick start/tick done`，说明运行的仍是旧脚本，应重新粘贴最新版本。

如果每次手动运行只看到一次 `tick ok accounts=... ticks=1`，之后 `heartbeat.json` 不再刷新，通常不是交易 API 卡死，而是旧版仍在依赖后台线程。请确认已更新到带 `foreground loop started by init` 的新版脚本，并重新编译、保存、运行。

如果日志里继续新增 `worker start requested by top-level` 或旧格式临时文件 `heartbeat.json.<pid>.tmp`，通常说明大QMT里仍有旧实例残留。应先停止策略，必要时重启大QMT客户端，再运行最新版脚本。

验证通过的文件状态：

- `C:\QuantIPC\{account_id}\status\heartbeat.json` 修改时间持续贴近当前时间。
- `C:\QuantIPC\{account_id}\status\account.json` 周期更新；休盘时资产字段可能为 0，但持仓市值应能正常返回或兜底。
- `tick ok accounts=... ticks=...` 中的 `ticks` 持续递增。
- 在模型交易前台循环形态下，`worker=False` 是正常状态；它表示没有额外后台 worker 参与保活。

v3.8.9 起，executor 额外启动独立心跳线程，并在等待委托终态的阻塞循环中刷新心跳。大 QMT 端可用环境变量 `QMT_IPC_HEARTBEAT_INTERVAL_SEC` 调整刷新间隔，默认 `2.0` 秒；策略端仍用 `QMT_IPC_HEARTBEAT_MAX_AGE`（默认 10 秒）判定离线。

## 风险控制

- 下单前策略端检查 `heartbeat.json`，大QMT离线时快速失败。
- 大QMT端处理 `processing/` 超龄文件时写 `error` 回执并清理，不重发订单。
- `done/` 目录按保留时间归档到 `done_archive/`，避免长期运行膨胀。
- 外部交易 API 调用都有超时保护，避免 QMT API 偶发卡死拖住主循环。
- 大QMT端写 `done/`、`status/account.json`、`status/heartbeat.json` 时使用唯一临时文件名和短重试，降低 Windows 文件锁导致的 `WinError 32` 风险。
- 大QMT端日志按日期写入，同时受 `QMT_IPC_LOG_MAX_BYTES` 和 `QMT_IPC_LOG_BACKUP_COUNT` 限制，避免长期运行写满存储介质。

## 调试顺序

1. 确认 `heartbeat.json` 持续更新。
2. 确认两个账号都生成 `account.json`，且 `source=xttrader`。
3. 确认持仓字段可信：无零股伪持仓，休盘参考价可反推。
4. 先验证预取消链路：先写 `cancel/cancel_<order_id>.json`，再写 `pending/ord_<order_id>.json`，确认 `done/cancelled` 且日志没有 `order seq=`。
5. 验证拒单链路：用空仓账号小数量卖出不可成交标的或明显会被柜台拒绝的场景，确认 `done/rejected`、`filled_volume=0`。
6. 有效委托号 + 撤单链路建议等交易时段再测：用极低成交概率限价单拿到正 `seq` 后立即写 cancel 文件，确认 `inflight cancel` 和最终回执。
7. 最后才做最小数量、有效价格的真实下单验证。
