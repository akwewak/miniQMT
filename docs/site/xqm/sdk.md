# Python SDK 参考

## 安装与导入

```python
from xtquant_manager.client import XtQuantClient, ClientConfig, XtDataAdapter
```

## XtQuantClient

```python
client = XtQuantClient(config=ClientConfig(
    base_url="http://127.0.0.1:8888",
    account_id="55009640",
    api_token="",          # 本机无 Token 时留空；远程访问必须填写服务端 Token
    timeout=5.0,
    max_retries=2,
    verify_ssl=True,       # HTTPS 时是否验证证书
))
```

### 连接与状态

```python
client.connect()                    # 验证服务可达，返回 (self, self) 或抛出异常
client.close()                      # 释放 HTTP 连接池
client.is_connected() -> bool       # 检查账号是否连接
client.health() -> dict             # 返回账号健康状态 dict
client.get_account_status() -> dict # 返回账号详细状态
client.get_metrics() -> dict        # 返回账号调用指标
```

### 持仓与资产

与 `easy_qmt_trader` 接口兼容：

```python
client.position() -> pd.DataFrame        # 所有持仓，列名与 QMT 一致
client.balance() -> pd.DataFrame         # 账户资金
client.query_stock_asset() -> dict       # 资产 dict
client.query_stock_orders() -> pd.DataFrame   # 当日委托
client.query_stock_trades() -> pd.DataFrame   # 当日成交
```

### 交易

```python
client.order_stock(
    stock_code: str,         # "000001.SZ"
    order_type: int,         # 23=限价买, 24=限价卖
    order_volume: int,       # 股数
    price_type: int = 11,    # 11=限价, 5=市价
    price: float = 0.0,
    strategy_name: str = "",
    order_remark: str = "",
) -> int                     # order_id >= 0，失败返回 -1

client.buy(security, order_type, amount, price=0.0) -> int
client.sell(security, order_type, amount, price=0.0) -> int
client.cancel_order_stock(order_id: int) -> int  # 0=提交成功
```

### 行情

```python
client.get_full_tick(stock_codes: list) -> dict
client.get_market_data_ex(
    fields: list,
    stock_list: list,
    period: str,
    start_time: str,
    end_time: str,
) -> dict
client.download_history_data(
    stock_code: str,
    period: str,
    start_time: str,
    end_time: str,
) -> bool
```

---

## XtDataAdapter

兼容 `xtquant.xtdata` 接口，可直接替换原有 xtdata 调用：

```python
xtdata = XtDataAdapter(client)

# 与 xtquant.xtdata 接口兼容
xtdata.connect() -> bool
xtdata.get_full_tick(stock_codes: list) -> dict
xtdata.get_market_data_ex(fields, stock_list, period, start_time, end_time) -> dict
xtdata.download_history_data(stock_code, period, start_time, end_time)
```

---

## 错误处理

```python
from xtquant_manager.exceptions import (
    AccountNotFoundError,
    XtQuantCallError,
    XtQuantTimeoutError,
)

try:
    positions = client.position()
except AccountNotFoundError:
    print("账号未注册")
except XtQuantTimeoutError:
    print("调用超时，稍后重试")
except XtQuantCallError as e:
    print(f"调用失败: {e}")
```
