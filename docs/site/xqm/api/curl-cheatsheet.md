# curl 速查表

```bash
BASE="http://127.0.0.1:8888/api/v1"
TOKEN="your-token"   # 无 Token 时删除所有 -H "X-API-Token" 行
```

## 可观测性

```bash
# 全局健康（免 Token 可达；不带 Token 时只返回 total/healthy 计数，无 accounts 明细）
curl $BASE/health

# 全局健康（带 Token，返回完整账号明细）
curl -H "X-API-Token: $TOKEN" $BASE/health

# 单账号健康（需 Token）
curl -H "X-API-Token: $TOKEN" $BASE/health/55009640
```

## 账号管理

```bash
# 注册账号
curl -X POST $BASE/accounts \
  -H "Content-Type: application/json" \
  -H "X-API-Token: $TOKEN" \
  -d '{"account_id":"55009640","qmt_path":"C:/QMT/userdata_mini","account_type":"STOCK"}'

# 列出账号
curl -H "X-API-Token: $TOKEN" $BASE/accounts

# 账号状态
curl -H "X-API-Token: $TOKEN" $BASE/accounts/55009640/status

# 注销账号
curl -X DELETE -H "X-API-Token: $TOKEN" $BASE/accounts/55009640
```

## 交易操作

```bash
# 查询持仓
curl -H "X-API-Token: $TOKEN" $BASE/accounts/55009640/positions

# 查询资产
curl -H "X-API-Token: $TOKEN" $BASE/accounts/55009640/asset

# 当日委托
curl -H "X-API-Token: $TOKEN" $BASE/accounts/55009640/orders

# 当日成交
curl -H "X-API-Token: $TOKEN" $BASE/accounts/55009640/trades

# 限价买入 000001.SZ 100 股，价格 10.50
curl -X POST $BASE/accounts/55009640/orders \
  -H "Content-Type: application/json" \
  -H "X-API-Token: $TOKEN" \
  -d '{"stock_code":"000001.SZ","order_type":23,"order_volume":100,"price_type":11,"price":10.50}'

# 撤单
curl -X DELETE -H "X-API-Token: $TOKEN" $BASE/accounts/55009640/orders/2014314497
```

## 行情

```bash
# 实时 Tick（多只）
curl "$BASE/market/tick?stock_codes=000001.SZ,600036.SH&account_id=55009640" \
  -H "X-API-Token: $TOKEN"

# 历史行情（日线）
curl "$BASE/market/history?stock_code=000001.SZ&account_id=55009640&period=1d&start_time=20260101" \
  -H "X-API-Token: $TOKEN"

# 下载历史数据
curl -X POST $BASE/market/download \
  -H "Content-Type: application/json" \
  -H "X-API-Token: $TOKEN" \
  -d '{"account_id":"55009640","stock_code":"000001.SZ","period":"1d","start_time":"20260101","end_time":"20260411"}'
```

## 指标

```bash
# 全局指标
curl -H "X-API-Token: $TOKEN" $BASE/metrics

# 单账号指标
curl -H "X-API-Token: $TOKEN" $BASE/metrics/55009640
```

### 止盈止损

```bash
# 查看止盈止损监控状态（需 Token）
curl -H "X-API-Token: $TOKEN" $BASE/stop-profit/status

# 暂停止盈止损（需 Token）
curl -X POST -H "X-API-Token: $TOKEN" "$BASE/stop-profit/toggle?enabled=false"

# 启用止盈止损（需 Token）
curl -X POST -H "X-API-Token: $TOKEN" "$BASE/stop-profit/toggle?enabled=true"

# 更新止盈止损参数（需 Token）
curl -X POST $BASE/stop-profit/config \
  -H "Content-Type: application/json" \
  -H "X-API-Token: $TOKEN" \
  -d '{"stop_loss_ratio": -0.08, "initial_take_profit_ratio": 0.07}'
```
