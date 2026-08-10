#!/usr/bin/env python
"""Standalone smoke test for the 100-share live SELL async guard.

Default mode is fully mocked and never sends a broker order. It verifies the
exact TradingExecutor.sell_stock path that was fixed for:

1. trade push unavailable -> no submit
2. positive async seq without order_id -> submit once, no retry
3. unknown-submit cooldown -> immediate duplicate blocked
4. late seq->order_id map -> cooldown cleared
5. normal seq->order_id map -> 100-share sell succeeds

Optional live mode is intentionally gated and should only be used during market
hours after the mock mode passes.
"""
from __future__ import annotations

import argparse
import json
import os
import sqlite3
import sys
import threading
from pathlib import Path
from typing import Any, Dict, List, Optional


REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))


class SmokeFailure(AssertionError):
    pass


class FakeDataManager:
    def __init__(self, price: float) -> None:
        self.price = price

    def get_stock_name(self, stock_code: str, *args: Any, **kwargs: Any) -> str:
        return "JIUGUIJIU"

    def get_latest_data(self, stock_code: str) -> Dict[str, float]:
        return {"lastPrice": self.price, "close": self.price}


class FakeQmtTrader:
    def __init__(self, *, push_ready: bool = True, sell_return: int = 5209) -> None:
        self.push_ready = push_ready
        self.sell_return = sell_return
        self.sell_calls: List[Dict[str, Any]] = []
        self.ensure_calls = 0
        self.order_id_map: Dict[int, int] = {}

    def adjust_stock(self, stock: str) -> str:
        return stock if "." in stock else f"{stock}.SZ"

    def check_stock_is_av_sell(self, stock: str, amount: int) -> bool:
        return True

    def ensure_trade_push_ready(self) -> bool:
        self.ensure_calls += 1
        return self.push_ready

    def sell(
        self,
        security: str,
        price: float,
        amount: int,
        price_type: int,
        strategy_name: str,
        order_remark: str,
    ) -> int:
        self.sell_calls.append({
            "security": security,
            "price": price,
            "amount": amount,
            "price_type": price_type,
            "strategy_name": strategy_name,
            "order_remark": order_remark,
        })
        return self.sell_return


class FakePositionManager:
    def __init__(self, qmt_trader: FakeQmtTrader, real_order_ids: Optional[Dict[int, int]] = None) -> None:
        self.qmt_trader = qmt_trader
        self.real_order_ids = real_order_ids or {}
        self.track_order_calls: List[Dict[str, Any]] = []

    def _get_real_order_id(self, seq: int, **kwargs: Any) -> Optional[int]:
        return self.real_order_ids.get(seq)

    def get_position(self, stock_code: str) -> Dict[str, Any]:
        return {
            "stock_code": stock_code,
            "volume": 1900,
            "available": 1900,
            "cost_price": 41.12,
            "current_price": 41.50,
        }

    def track_order(self, **kwargs: Any) -> None:
        self.track_order_calls.append(kwargs)


def assert_that(condition: bool, message: str) -> None:
    if not condition:
        raise SmokeFailure(message)


def make_executor(qmt_trader: FakeQmtTrader, real_order_ids: Optional[Dict[int, int]], price: float):
    from trading_executor import TradingExecutor

    executor = TradingExecutor.__new__(TradingExecutor)
    executor.data_manager = FakeDataManager(price)
    executor.position_manager = FakePositionManager(qmt_trader, real_order_ids)
    executor.conn = sqlite3.connect(":memory:", check_same_thread=False)
    executor.conn.execute("""
        CREATE TABLE trade_records (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            stock_code TEXT,
            stock_name TEXT,
            trade_time TIMESTAMP,
            trade_type TEXT,
            price REAL,
            volume INTEGER,
            amount REAL,
            trade_id TEXT,
            commission REAL,
            strategy TEXT
        )
    """)
    executor.conn.commit()
    executor.order_cache = {}
    executor.callbacks = {}
    executor.trade_lock = threading.Lock()
    executor._trade_record_lock = threading.RLock()
    executor._unknown_order_submissions = {}
    return executor


def patch_config_for_mock():
    import config

    old_values = {
        "ENABLE_SIMULATION_MODE": config.ENABLE_SIMULATION_MODE,
        "ENABLE_ALLOW_SELL": getattr(config, "ENABLE_ALLOW_SELL", True),
        "ASYNC_ORDER_UNKNOWN_COOLDOWN_SECONDS": getattr(
            config, "ASYNC_ORDER_UNKNOWN_COOLDOWN_SECONDS", 300
        ),
        "is_trade_time": config.is_trade_time,
    }
    config.ENABLE_SIMULATION_MODE = False
    config.ENABLE_ALLOW_SELL = True
    config.ASYNC_ORDER_UNKNOWN_COOLDOWN_SECONDS = 300
    config.is_trade_time = lambda: True
    return config, old_values


def restore_config(config, old_values: Dict[str, Any]) -> None:
    config.ENABLE_SIMULATION_MODE = old_values["ENABLE_SIMULATION_MODE"]
    config.ENABLE_ALLOW_SELL = old_values["ENABLE_ALLOW_SELL"]
    config.ASYNC_ORDER_UNKNOWN_COOLDOWN_SECONDS = old_values[
        "ASYNC_ORDER_UNKNOWN_COOLDOWN_SECONDS"
    ]
    config.is_trade_time = old_values["is_trade_time"]


def test_push_not_ready_blocks_submit(stock: str, volume: int, price: float) -> Dict[str, Any]:
    qmt = FakeQmtTrader(push_ready=False, sell_return=5209)
    executor = make_executor(qmt, real_order_ids=None, price=price)
    result = executor.sell_stock(stock, volume=volume, price=price, strategy="grid")
    assert_that(result is None, "push-not-ready path should return None")
    assert_that(len(qmt.sell_calls) == 0, "push-not-ready path must not submit sell")
    assert_that(qmt.ensure_calls == 1, "push readiness should be checked once")
    return {"case": "push_not_ready_blocks_submit", "sell_calls": len(qmt.sell_calls)}


def test_unknown_seq_no_resubmit(stock: str, volume: int, price: float) -> Dict[str, Any]:
    qmt = FakeQmtTrader(push_ready=True, sell_return=5209)
    executor = make_executor(qmt, real_order_ids={}, price=price)

    first = executor.sell_stock(stock, volume=volume, price=price, strategy="grid")
    second = executor.sell_stock(stock, volume=volume, price=price, strategy="grid")

    assert_that(first is None, "first unknown submit should return None to caller")
    assert_that(second is None, "duplicate during unknown cooldown should return None")
    assert_that(len(qmt.sell_calls) == 1, "positive seq without order_id must submit only once")
    call = qmt.sell_calls[0]
    assert_that(call["amount"] == volume, f"sell volume should be {volume}")
    assert_that(call["security"] == f"{stock}.SZ", "stock should be adjusted to .SZ")
    assert_that((f"{stock}.SZ", "SELL") in executor._unknown_order_submissions,
                "unknown submit should be recorded for cooldown")
    return {
        "case": "unknown_seq_no_resubmit",
        "first_result": first,
        "second_result": second,
        "sell_calls": len(qmt.sell_calls),
        "unknown_entries": len(executor._unknown_order_submissions),
    }


def test_late_order_id_map_clears_cooldown(stock: str, volume: int, price: float) -> Dict[str, Any]:
    qmt = FakeQmtTrader(push_ready=True, sell_return=5209)
    executor = make_executor(qmt, real_order_ids={}, price=price)
    executor._mark_unknown_order_submission(f"{stock}.SZ", "SELL", 5209, price, volume, "grid")
    qmt.order_id_map[5209] = 940572811

    blocked = executor._has_recent_unknown_order_submission(f"{stock}.SZ", "SELL")
    assert_that(blocked is False, "late seq->order_id map should clear cooldown")
    assert_that(executor._unknown_order_submissions == {}, "unknown map should be empty after clear")
    return {"case": "late_order_id_map_clears_cooldown", "blocked": blocked}


def test_confirmed_order_success(stock: str, volume: int, price: float) -> Dict[str, Any]:
    qmt = FakeQmtTrader(push_ready=True, sell_return=5209)
    executor = make_executor(qmt, real_order_ids={5209: 940572900}, price=price)
    order_id = executor.sell_stock(stock, volume=volume, price=price, strategy="grid")

    assert_that(order_id == 940572900, "resolved seq should return real order_id")
    assert_that(len(qmt.sell_calls) == 1, "resolved seq should submit once")
    assert_that(str(order_id) in executor.order_cache, "resolved order should be cached")
    assert_that(executor.order_cache[str(order_id)]["volume"] == volume,
                f"cached volume should be {volume}")
    assert_that(executor._unknown_order_submissions == {}, "resolved order must not leave cooldown")
    return {
        "case": "confirmed_order_success",
        "order_id": order_id,
        "sell_calls": len(qmt.sell_calls),
    }


def run_mock(args: argparse.Namespace) -> int:
    if args.volume != 100:
        raise SmokeFailure("This smoke script is scoped to exactly 100 shares in mock mode")

    config, old_values = patch_config_for_mock()
    try:
        results = [
            test_push_not_ready_blocks_submit(args.stock, args.volume, args.price),
            test_unknown_seq_no_resubmit(args.stock, args.volume, args.price),
            test_late_order_id_map_clears_cooldown(args.stock, args.volume, args.price),
            test_confirmed_order_success(args.stock, args.volume, args.price),
        ]
    finally:
        restore_config(config, old_values)

    print(json.dumps({
        "mode": "mock",
        "stock": args.stock,
        "volume": args.volume,
        "price": args.price,
        "success": True,
        "results": results,
    }, ensure_ascii=False, indent=2))
    return 0


def run_live_submit(args: argparse.Namespace) -> int:
    if args.volume != 100:
        raise SmokeFailure("Live smoke test refuses volume other than 100")
    expected_confirm = f"SELL_100_{args.stock}"
    if args.confirm_real_sell != expected_confirm:
        raise SmokeFailure(
            f"Live submit requires --confirm-real-sell {expected_confirm}"
        )

    import config
    from data_manager import get_data_manager
    from position_manager import get_position_manager
    from trading_executor import TradingExecutor

    config.ENABLE_SIMULATION_MODE = False
    config.ENABLE_AUTO_OPERATION = False

    if not config.is_trade_time():
        raise SmokeFailure("Live submit refused: current time is not market trading time")

    dm = None
    pm = None
    qmt = None
    try:
        dm = get_data_manager()
        pm = get_position_manager()
        executor = TradingExecutor()
        qmt = getattr(pm, "qmt_trader", None)
        if not qmt or not getattr(pm, "qmt_connected", False):
            raise SmokeFailure("Live submit refused: QMT trader is not connected")
        if hasattr(qmt, "ensure_trade_push_ready") and not qmt.ensure_trade_push_ready():
            raise SmokeFailure("Live submit refused: trade push is not ready")

        position = pm.get_position(args.stock) or pm.get_position(f"{args.stock}.SZ")
        available = int((position or {}).get("available") or 0)
        if available < args.volume:
            raise SmokeFailure(f"Live submit refused: available={available}, need={args.volume}")

        order_id = executor.sell_stock(
            args.stock,
            volume=args.volume,
            price=args.price,
            price_type=args.price_type,
            strategy=args.strategy,
        )
        print(json.dumps({
            "mode": "live-submit",
            "stock": args.stock,
            "volume": args.volume,
            "price": args.price,
            "order_id": order_id,
            "success": bool(order_id),
        }, ensure_ascii=False, indent=2))
        return 0 if order_id else 2
    finally:
        try:
            if pm:
                pm.stop_sync_thread()
        except Exception:
            pass
        try:
            if dm:
                dm.close()
        except Exception:
            pass
        try:
            if qmt and hasattr(qmt, "stop"):
                qmt.stop()
        except Exception:
            pass


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Standalone 100-share SELL smoke test for async order guard."
    )
    parser.add_argument("--mode", choices=["mock", "live-submit"], default="mock")
    parser.add_argument("--account-id", default="", help="Set QMT_ACCOUNT_ID before importing config.")
    parser.add_argument("--stock", default="000799")
    parser.add_argument("--volume", type=int, default=100)
    parser.add_argument("--price", type=float, default=41.50)
    parser.add_argument("--price-type", type=int, default=5)
    parser.add_argument("--strategy", default="grid")
    parser.add_argument("--confirm-real-sell", default="")
    return parser


def main(argv: Optional[List[str]] = None) -> int:
    args = build_parser().parse_args(argv)
    if args.account_id:
        os.environ["QMT_ACCOUNT_ID"] = args.account_id

    try:
        if args.mode == "mock":
            return run_mock(args)
        return run_live_submit(args)
    except SmokeFailure as exc:
        print(json.dumps({"success": False, "error": str(exc)}, ensure_ascii=False, indent=2))
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
