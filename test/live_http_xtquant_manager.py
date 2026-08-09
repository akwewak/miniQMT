"""
XtQuantManager 真实 HTTP 端到端 live 测试（零真实 QMT 接触）

与 test_server.py 的区别：本脚本启动真实 uvicorn 进程内服务（真实端口绑定、
真实网络栈、真实 HealthMonitor），用 httpx 发真实 HTTP 请求，而非 FastAPI TestClient。

账号数据用 Mock 注入，模拟生产双账号场景（TEST_ACC_1 / TEST_ACC_2），
全程不连接真实 QMT，不下任何真实订单 —— 零风险。

覆盖：
- 多账号管理：/health 聚合、/accounts 列表、各账号独立 status/positions/asset
- 全部只读 API 路由真实 HTTP 往返
- 错误路径：不存在账号 404
- 安全：API token 401/200
- 可观测性：/metrics 聚合与单账号

退出码 0 = 全部通过，非 0 = 有失败。
"""
import os
import sys
import time
import threading

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import httpx

from xtquant_manager.manager import XtQuantManager
from xtquant_manager.account import AccountConfig, XtQuantAccount
from xtquant_manager.server_runner import XtQuantServer, XtQuantServerConfig
from test.test_xtquant_manager.mocks import MockXtTrader, MockXtData, MockStockAccount

ACC1 = "TEST_ACC_1"
ACC2 = "TEST_ACC_2"

_results = []


def check(name, cond, detail=""):
    _results.append((name, bool(cond), detail))
    flag = "PASS" if cond else "FAIL"
    print(f"  [{flag}] {name}" + (f"  -> {detail}" if detail else ""))


def inject_account(manager, account_id, positions=None):
    """向 manager 注入一个已连接的 mock 账号"""
    cfg = AccountConfig(account_id=account_id, qmt_path="mock")
    acct = XtQuantAccount(cfg)
    trader = MockXtTrader()
    if positions:
        for p in positions:
            trader.add_mock_position(
                stock_code=p["stock_code"],
                volume=p["volume"],
                cost_price=p.get("cost_price", 10.0),
                current_price=p.get("current_price", 10.5),
            )
    acct._xt_trader = trader
    acct._acc = MockStockAccount(account_id)
    acct._xtdata = MockXtData()
    acct._connected = True
    acct._connected_at = time.time()
    acct._last_ping_ok_time = time.time()
    manager._accounts[account_id] = acct
    return acct


def wait_port(base_url, timeout=10.0):
    """轮询直到 HTTP 服务可达"""
    deadline = time.time() + timeout
    while time.time() < deadline:
        try:
            r = httpx.get(f"{base_url}/api/v1/health", timeout=1.0)
            if r.status_code == 200:
                return True
        except Exception:
            time.sleep(0.2)
    return False


def run_open_server_tests():
    """无 token 服务：多账号管理 + 只读 API + 404"""
    print("\n=== 阶段A：真实 uvicorn 服务（无 token，端口 8899）===")
    XtQuantManager.reset_instance()
    manager = XtQuantManager.get_instance()
    inject_account(manager, ACC1, positions=[
        {"stock_code": "000001.SZ", "volume": 1000, "cost_price": 10.0, "current_price": 10.5},
    ])
    inject_account(manager, ACC2, positions=[
        {"stock_code": "600036.SH", "volume": 500, "cost_price": 35.0, "current_price": 36.0},
    ])

    server = XtQuantServer(XtQuantServerConfig(host="127.0.0.1", port=8899))
    server.start(blocking=False)
    base = "http://127.0.0.1:8899"
    try:
        if not wait_port(base):
            check("服务在 8899 启动并可达", False, "超时未就绪")
            return
        check("服务在 8899 启动并可达", True)

        # --- 多账号管理：/health 聚合（免 token 可达，仅返回计数）---
        # 该实例未配置 api_token 且客户端为本机，故 accounts 明细可见；
        # 远程无 token 时 accounts 会是空 dict（见下方带 token 实例的用例）。
        r = httpx.get(f"{base}/api/v1/health")
        d = r.json().get("data", {})
        check("GET /health 返回 200", r.status_code == 200, f"status={r.status_code}")
        check("/health total=2", d.get("total") == 2, f"total={d.get('total')}")
        check("/health healthy=2", d.get("healthy") == 2, f"healthy={d.get('healthy')}")
        check("/health 含两个账号", ACC1 in d.get("accounts", {}) and ACC2 in d.get("accounts", {}))

        # --- 账号列表 ---
        r = httpx.get(f"{base}/api/v1/accounts")
        accs = r.json().get("data", {}).get("accounts", [])
        check("GET /accounts 列出 2 个账号", len(accs) == 2, f"accounts={accs}")

        # --- 单账号 status ---
        r = httpx.get(f"{base}/api/v1/accounts/{ACC1}/status")
        s = r.json().get("data", {})
        check(f"GET /accounts/{ACC1}/status connected", s.get("connected") is True)
        check(f"status account_id 匹配", s.get("account_id") == ACC1, f"got={s.get('account_id')}")

        # --- 多账号隔离：各账号独立持仓 ---
        r1 = httpx.get(f"{base}/api/v1/accounts/{ACC1}/positions").json()
        r2 = httpx.get(f"{base}/api/v1/accounts/{ACC2}/positions").json()
        p1 = r1.get("data", {}).get("positions", [])
        p2 = r2.get("data", {}).get("positions", [])
        check(f"{ACC1} 持仓含 000001", any("000001" in str(p.get("证券代码")) for p in p1), f"p1={p1}")
        check(f"{ACC2} 持仓含 600036", any("600036" in str(p.get("证券代码")) for p in p2), f"p2={p2}")
        check("两账号持仓互相隔离",
              not any("600036" in str(p.get("证券代码")) for p in p1)
              and not any("000001" in str(p.get("证券代码")) for p in p2))

        # --- 只读端点：asset / orders / trades ---
        r = httpx.get(f"{base}/api/v1/accounts/{ACC1}/asset")
        check("GET /asset 成功", r.json().get("success") is True, f"status={r.status_code}")
        r = httpx.get(f"{base}/api/v1/accounts/{ACC1}/orders")
        check("GET /orders 成功且 data.orders 为列表",
              r.json().get("success") and isinstance(r.json().get("data", {}).get("orders"), list))
        r = httpx.get(f"{base}/api/v1/accounts/{ACC1}/trades")
        check("GET /trades 成功且 data.trades 为列表",
              r.json().get("success") and isinstance(r.json().get("data", {}).get("trades"), list))

        # --- 行情 tick ---
        r = httpx.get(f"{base}/api/v1/market/tick",
                      params={"stock_codes": "000001.SZ,600036.SH", "account_id": ACC1})
        check("GET /market/tick 成功", r.json().get("success") is True, f"status={r.status_code}")

        # --- 可观测性：metrics ---
        r = httpx.get(f"{base}/api/v1/metrics")
        check("GET /metrics 成功", r.json().get("success") is True)
        r = httpx.get(f"{base}/api/v1/metrics/{ACC1}")
        check(f"GET /metrics/{ACC1} 成功", r.json().get("success") is True)

        # --- 错误路径：不存在账号 404 ---
        r = httpx.get(f"{base}/api/v1/accounts/99999999/status")
        check("不存在账号 status 返回 404", r.status_code == 404, f"status={r.status_code}")
        r = httpx.get(f"{base}/api/v1/accounts/99999999/positions")
        check("不存在账号 positions 返回 404", r.status_code == 404, f"status={r.status_code}")
        r = httpx.get(f"{base}/api/v1/metrics/99999999")
        check("不存在账号 metrics 返回 404", r.status_code == 404, f"status={r.status_code}")

        # --- 注销账号 ---
        r = httpx.delete(f"{base}/api/v1/accounts/{ACC2}")
        check(f"DELETE /accounts/{ACC2} 成功", r.json().get("success") is True, f"status={r.status_code}")
        r = httpx.get(f"{base}/api/v1/health")
        check("注销后 /health total=1", r.json().get("data", {}).get("total") == 1)
        r = httpx.delete(f"{base}/api/v1/accounts/{ACC2}")
        check("重复注销返回 404", r.status_code == 404, f"status={r.status_code}")

    finally:
        server.stop(timeout=5.0)


def run_token_server_tests():
    """带 token 服务：认证 401/200（用 X-Forwarded-For 模拟远程 IP）"""
    print("\n=== 阶段B：真实 uvicorn 服务（带 API token，端口 8900）===")
    XtQuantManager.reset_instance()
    manager = XtQuantManager.get_instance()
    inject_account(manager, ACC1)

    token = "secret-test-token-123"
    # trust_proxy=True: 本用例刻意用 X-Forwarded-For 模拟远程 IP，
    # 生产默认为 False（否则伪造该头即可冒充本机绕过 token）。
    server = XtQuantServer(XtQuantServerConfig(
        host="127.0.0.1", port=8900, api_token=token, trust_proxy=True))
    server.start(blocking=False)
    base = "http://127.0.0.1:8900"
    # 模拟远程 IP 以绕过 local_ips 白名单，触发 token 验证
    remote_headers = {"X-Forwarded-For": "192.168.1.100"}
    try:
        if not wait_port(base):
            check("带 token 服务在 8900 启动并可达", False, "超时未就绪")
            return
        check("带 token 服务在 8900 启动并可达", True)

        # /health 免 token 可达（存活探测），但远程无 token 时不返回账号明细
        r = httpx.get(f"{base}/api/v1/health", headers=remote_headers)
        check("/health 无需 token 即可访问（远程 IP）", r.status_code == 200, f"status={r.status_code}")
        check("/health 远程无 token 不泄露账号明细",
              r.json().get("data", {}).get("accounts") == {},
              f"accounts={r.json().get('data', {}).get('accounts')}")
        r = httpx.get(f"{base}/api/v1/health",
                      headers={**remote_headers, "X-API-Token": token})
        check("/health 带 token 返回账号明细",
              ACC1 in r.json().get("data", {}).get("accounts", {}))

        # 伪造 X-Forwarded-For 不应绕过 token（trust_proxy 关闭时的生产行为）
        server_np = XtQuantServer(XtQuantServerConfig(
            host="127.0.0.1", port=8901, api_token=token))
        server_np.start(blocking=False)
        try:
            if wait_port("http://127.0.0.1:8901"):
                r = httpx.get("http://127.0.0.1:8901/api/v1/accounts",
                              headers={"X-Forwarded-For": "127.0.0.1"})
                check("伪造 XFF=127.0.0.1 不能绕过 token（trust_proxy=False）",
                      r.status_code == 401, f"status={r.status_code}")
        finally:
            server_np.stop(timeout=5.0)

        # 受保护端点：无 token -> 401
        r = httpx.get(f"{base}/api/v1/accounts", headers=remote_headers)
        check("无 token 访问 /accounts 返回 401（远程 IP）", r.status_code == 401, f"status={r.status_code}")

        # 错误 token -> 401
        r = httpx.get(f"{base}/api/v1/accounts", headers={**remote_headers, "X-API-Token": "wrong"})
        check("错误 token 返回 401（远程 IP）", r.status_code == 401, f"status={r.status_code}")

        # 正确 token -> 200
        r = httpx.get(f"{base}/api/v1/accounts", headers={**remote_headers, "X-API-Token": token})
        check("正确 token 返回 200（远程 IP）", r.status_code == 200, f"status={r.status_code}")

        # 本机访问（不带 X-Forwarded-For）免 token -> 200
        r = httpx.get(f"{base}/api/v1/accounts")
        check("本机访问免 token 返回 200", r.status_code == 200, f"status={r.status_code}")

    finally:
        server.stop(timeout=5.0)


def main():
    print("=" * 64)
    print("XtQuantManager 真实 HTTP 端到端 live 测试（Mock 账号，零真实 QMT）")
    print("=" * 64)
    run_open_server_tests()
    run_token_server_tests()

    print("\n" + "=" * 64)
    passed = sum(1 for _, ok, _ in _results if ok)
    total = len(_results)
    failed = [name for name, ok, _ in _results if not ok]
    print(f"汇总：{passed}/{total} 通过")
    if failed:
        print("失败项：")
        for name in failed:
            print(f"  - {name}")
        sys.exit(1)
    print("ALL PASSED")
    sys.exit(0)


if __name__ == "__main__":
    main()
