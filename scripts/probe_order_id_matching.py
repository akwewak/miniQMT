"""调用 Web API 000799 窄接口探测 QMT order_id 行为。

默认只跑 preflight，不下单。实盘测试必须显式指定 mode 和确认串：

sell-cancel:
  --mode sell-cancel --confirm SELL_CANCEL_100_000799_25105132

sell-fill 会真实卖出成交，除确认串外还必须传 --allow-fill。
"""

from __future__ import annotations

import argparse
import json
import os
import sys
import urllib.error
import urllib.parse
import urllib.request


DEFAULT_CANCEL_CONFIRM = "SELL_CANCEL_100_000799_25105132"
DEFAULT_FILL_CONFIRM = "SELL_FILL_100_000799_25105132"


def _request_json(method, url, token="", payload=None, timeout=120):
    data = None
    headers = {"Content-Type": "application/json"}
    if token:
        headers["X-API-Token"] = token
    if payload is not None:
        data = json.dumps(payload, ensure_ascii=False).encode("utf-8")

    req = urllib.request.Request(url, data=data, headers=headers, method=method)
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            body = resp.read().decode("utf-8", errors="replace")
            return resp.status, json.loads(body) if body else {}
    except urllib.error.HTTPError as e:
        body = e.read().decode("utf-8", errors="replace")
        try:
            parsed = json.loads(body) if body else {}
        except json.JSONDecodeError:
            parsed = {"raw": body}
        return e.code, parsed
    except (urllib.error.URLError, TimeoutError, OSError) as e:
        return 0, {"success": False, "error": str(e), "url": url}


def _api_url(base_url, path, token=""):
    base = base_url.rstrip("/")
    if not token:
        return f"{base}{path}"
    return f"{base}{path}?{urllib.parse.urlencode({'token': token})}"


def _print_json(title, value):
    print(f"\n== {title} ==")
    print(json.dumps(value, ensure_ascii=False, indent=2, default=str))


def main():
    parser = argparse.ArgumentParser(description="通过 Web API 窄接口探测 QMT order_id 匹配行为")
    parser.add_argument("--base-url", default="http://127.0.0.1:50000")
    parser.add_argument("--token-env", default="QMT_API_TOKEN")
    parser.add_argument("--mode", choices=["preflight", "sell-cancel", "sell-fill"], default="preflight")
    parser.add_argument("--confirm", default="")
    parser.add_argument("--price", type=float, default=None)
    parser.add_argument("--price-type", type=int, default=None)
    parser.add_argument("--use-suggested-price", action="store_true")
    parser.add_argument("--allow-fill", action="store_true")
    parser.add_argument("--resolve-timeout", type=float, default=35.0)
    parser.add_argument("--cancel-timeout", type=float, default=30.0)
    parser.add_argument("--fill-timeout", type=float, default=60.0)
    parser.add_argument("--poll-interval", type=float, default=1.0)
    args = parser.parse_args()

    token = os.environ.get(args.token_env, "")
    endpoint = _api_url(args.base_url, "/api/debug/order-probe-000799", token)

    if args.mode == "sell-cancel" and args.confirm != DEFAULT_CANCEL_CONFIRM:
        print(f"confirm 不匹配，sell-cancel 需要: {DEFAULT_CANCEL_CONFIRM}")
        return 3
    if args.mode == "sell-fill":
        if args.confirm != DEFAULT_FILL_CONFIRM:
            print(f"confirm 不匹配，sell-fill 需要: {DEFAULT_FILL_CONFIRM}")
            return 3
        if not args.allow_fill:
            print("sell-fill 会真实卖出成交，必须额外传 --allow-fill")
            return 3

    payload = {
        "mode": args.mode,
        "confirm": args.confirm,
        "resolve_timeout": args.resolve_timeout,
        "cancel_timeout": args.cancel_timeout,
        "fill_timeout": args.fill_timeout,
        "poll_interval": args.poll_interval,
    }
    if args.price is not None:
        payload["price"] = args.price
    if args.price_type is not None:
        payload["price_type"] = args.price_type
    if args.use_suggested_price:
        payload["use_suggested_price"] = True
    if args.allow_fill:
        payload["allow_fill"] = True

    status, result = _request_json("POST", endpoint, token, payload)
    _print_json(f"{args.mode} HTTP {status}", result)

    if status <= 0 or status >= 400:
        return 2
    if not result.get("success"):
        return 4
    return 0


if __name__ == "__main__":
    sys.exit(main())
