# 常见问题

## 止盈止损信号重复执行

**原因**：信号验证失败或未正确标记为已处理。

**解决**：

- 检查 `validate_trading_signal()` 和 `mark_signal_processed()` 调用链
- 查看日志中的信号验证详情
- 确认信号有效期过滤正常工作：信号入队时写入 `latest_signals[stock_code]['timestamp']`，`get_pending_signals()` 会过滤超过 300 秒的过期信号

---

## 实盘卖出拿不到真实 order_id 后重复下单

**原因**：异步下单接口先返回 `seq`，真实 `order_id` 依赖 QMT 回调写入 `order_id_map`。如果回调延迟或丢失，程序不能把 `seq` 转成真实委托号；此时绝不能继续重试发卖单，否则可能造成同股同方向重复委托。

**解决**：

- `_get_real_order_id()` 先等待 `seq -> order_id` 回调映射；超时后用股票、方向、数量、价格和下单时间窗口查询当日委托列表反查真实 `order_id`
- 反查成功后回填 `order_id_map`，后续撤单、成交确认和日志都使用真实委托号
- 反查仍失败时标记为“已提交但未知委托号”，进入同股同方向冷却，停止重复实盘发单
- 可触发实盘下单的 Web 调试窄接口不得长期保留，相关验证结论应固化为文档和回归测试

---

## 模拟交易持仓不更新

**原因**：未触发数据版本号更新。

**解决**：

```python
def simulate_buy_position(self, ...):
    # ... 执行模拟买入逻辑 ...
    self._increment_data_version()  # 必须调用
```

---

## QMT 连接断开

**检查**：

```python
# 检查连接状态
position_manager.qmt_trader.xt_trader.is_connected()

# 重新连接
position_manager.qmt_trader.connect()

# 检查路径配置
# config.py 中的 QMT_PATH 是否正确
```

---

## 持仓监控线程未运行

**排查**：

```python
# 1. 检查配置
config.ENABLE_POSITION_MONITOR  # 应为 True

# 2. 检查线程状态
import threading
print(threading.enumerate())

# 3. 查看日志
# 搜索 "启动持仓监控线程" 或 "持仓监控线程异常"
```

---

## 线程监控器未自动重启线程

**原因**：使用了错误的线程注册方式。

**正确做法**：

```python
# ✅ 正确: 使用 lambda 获取最新对象
monitor.register_thread(
    "持仓监控",
    lambda: position_manager.monitor_thread,
    restart_func,
)

# ❌ 错误: 直接传递线程对象
monitor.register_thread(
    "持仓监控",
    position_manager.monitor_thread,  # 重启后引用会变化
    restart_func,
)
```

---

## 系统退出时出现数据库错误

**原因**：关闭顺序不正确，Web 服务器在数据库关闭后仍在处理请求。

**解决**：确保 `main.py` 中的 `cleanup()` 函数按正确顺序关闭。验证时查看日志，应看到有序的关闭步骤，无 ERROR 日志。

---

## 网格交易未触发

**排查步骤**：

1. 确认 `ENABLE_GRID_TRADING = True`
2. 确认股票在股票池中（`stock_pool.json`）
3. 确认网格会话已启动（`GET /api/grid/sessions`）
4. 查看日志中的网格信号检测记录
5. 若你显式设置了 `GRID_REQUIRE_PROFIT_TRIGGERED = True`，确认该持仓已触发首次止盈；默认 `False` 时不需要这个前提
6. 若行情健康门禁保持默认开启（`MARKET_HEALTH_OBSERVE_ONLY = False`），检查 `/api/market/health` 中该股票行情评分是否低于 `MARKET_HEALTH_TRADING_MIN_SCORE`

---

## 如何查看行情源健康评分

Flask 直连模式提供轻量内存版健康快照：

```bash
curl http://localhost:5000/api/market/health
```

该评分当前默认启用严格门禁（`MARKET_HEALTH_OBSERVE_ONLY = False`），持仓监控会按评分阈值和是否允许 Mootdx 兜底来判断行情是否可用于交易信号检测。如果只想观察评分而不影响交易，可改为 `True`。
