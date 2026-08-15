# QMT_trade_executor.py
# Big-QMT file-IPC solution -- QMT-side executor (multi-account).
#
# ASCII-ONLY: QMT strategy editor stores files as GBK. Non-ASCII bytes break
# Python's UTF-8 source decoding. KEEP THIS FILE PURE ASCII.
#
# RECOMMENDED: use MODEL-TRADING mode. QMT injects `get_trade_detail_data` into
# globals(), which the executor uses for snapshot (read path). Orders use
# __import__("xtquant.xttrader") (write path). Timed-run is a fallback where
# the VBA reader may be absent from globals().
#
# Multi-account: scans IPC_ROOT sub-dirs for config.json; handles each.
#
# Field notes from Big-QMT debugging (2026-07-12):
# - In model-trading mode, get_trade_detail_data/passorder/cancel are injected
#   into globals(), not ContextInfo.
# - ContextInfo mainly exposes market-data helpers; do not assume it has
#   query_stock_asset/order_stock/cancel_order.
# - xttrader read path works with StockAccount. During non-trading hours, asset
#   fields may be zero while positions still contain market_value. Normalize
#   snapshots before writing account.json.
# - order_stock should receive StockAccount when available. For market orders,
#   use price_type=LATEST_PRICE and price=0.

import os, json, time, shutil, traceback, threading
from datetime import datetime

IPC_ROOT = os.environ.get("QMT_IPC_ROOT", r"C:\QuantIPC")
DIR_LOG = os.path.join(IPC_ROOT, "qmt_log")

_DEFAULT_ACCOUNT_ID = "YOUR_ACCOUNT"
_DEFAULT_QMT_PATH = r"C:\QMT\userdata_mini"
ACCOUNT_FILTER = os.environ.get("QMT_IPC_ACCOUNT_FILTER", "").strip()
PROCESSING_STALE_SEC = int(os.environ.get("QMT_IPC_PROCESSING_STALE_SEC", "120"))
DONE_RETENTION_SEC = int(os.environ.get("QMT_IPC_DONE_RETENTION_SEC", "86400"))
SNAPSHOT_INTERVAL_SEC = 30
SNAPSHOT_TASK_STALE_SEC = int(os.environ.get("QMT_IPC_SNAPSHOT_TASK_STALE_SEC", "60"))
HEARTBEAT_INTERVAL_SEC = float(os.environ.get("QMT_IPC_HEARTBEAT_INTERVAL_SEC", "2.0"))
XT_CONNECT_TIMEOUT_SEC = int(os.environ.get("QMT_IPC_XT_CONNECT_TIMEOUT_SEC", "8"))
XT_QUERY_TIMEOUT_SEC = int(os.environ.get("QMT_IPC_XT_QUERY_TIMEOUT_SEC", "5"))
MAIN_INTERVAL_SEC = float(os.environ.get("QMT_IPC_MAIN_INTERVAL_SEC", "1.0"))
MAIN_LOG_INTERVAL_SEC = int(os.environ.get("QMT_IPC_MAIN_LOG_INTERVAL_SEC", "30"))
LOG_MAX_BYTES = int(os.environ.get("QMT_IPC_LOG_MAX_BYTES", "5242880"))
LOG_BACKUP_COUNT = int(os.environ.get("QMT_IPC_LOG_BACKUP_COUNT", "5"))

os.makedirs(DIR_LOG, exist_ok=True)

# xtconstant values hardcoded (QMT sandbox blocks `from xtquant import xtconstant`)
STOCK_BUY, STOCK_SELL = 23, 24
FIX_PRICE, LATEST_PRICE = 11, 5
ORDER_ALL_TRADED = 56
ORDER_PART_TRADED = 55
ORDER_PART_TRADED_CANCELED = 53
ORDER_CANCELED = 54
ORDER_REJECTED = 57

_LAST_SNAPSHOT_ATTEMPT = {}
_CONTEXT_INFO = {"obj": None}
_DIAG_DONE = {"ctx": False}
_MAIN_STATE = {"last_run": 0.0, "last_log": 0.0, "ticks": 0}
_MAIN_LOCK = threading.Lock()
_WORKER_STATE = {"thread": None, "started_at": 0.0}
_WORKER_LOCK = threading.Lock()
_SNAPSHOT_STATE = {}
_SNAPSHOT_LOCK = threading.Lock()
_HEARTBEAT_STATE = {}
_HEARTBEAT_LOCK = threading.Lock()
_LOG_LOCK = threading.Lock()


def _rotate_log(path):
    if LOG_MAX_BYTES <= 0:
        return
    try:
        if not os.path.exists(path) or os.path.getsize(path) < LOG_MAX_BYTES:
            return
        if LOG_BACKUP_COUNT <= 0:
            os.remove(path)
            return
        oldest = "%s.%d" % (path, LOG_BACKUP_COUNT)
        if os.path.exists(oldest):
            os.remove(oldest)
        for i in range(LOG_BACKUP_COUNT - 1, 0, -1):
            src = "%s.%d" % (path, i)
            dst = "%s.%d" % (path, i + 1)
            if os.path.exists(src):
                os.replace(src, dst)
        os.replace(path, "%s.1" % path)
    except Exception:
        pass


def log(msg):
    path = os.path.join(DIR_LOG, "log_%s.txt" % datetime.now().strftime("%Y%m%d"))
    try:
        with _LOG_LOCK:
            _rotate_log(path)
            with open(path, "a", encoding="utf-8") as f:
                f.write("[%s] %s\n" % (datetime.now().strftime("%H:%M:%S.%f")[:12], msg))
    except Exception:
        pass


def _load_json(path):
    try:
        with open(path, "r", encoding="utf-8-sig") as f:
            return json.load(f)
    except Exception:
        return None


def _as_float(v, default=0.0):
    try:
        if v is None:
            return default
        return float(v)
    except Exception:
        return default


def _as_int(v, default=0):
    try:
        if v is None:
            return default
        return int(v)
    except Exception:
        return default


def _first_attr(obj, names, default=None):
    for name in names:
        try:
            if hasattr(obj, name):
                v = getattr(obj, name)
                if v is not None:
                    return v
        except Exception:
            continue
    return default


def _make_position(stock, vol, available, cost, market_price, market_value):
    stock = str(stock or "")
    vol = _as_int(vol, 0)
    if vol <= 0 or not stock:
        return None
    available = _as_int(available, vol)
    cost = _as_float(cost, 0)
    market_price = _as_float(market_price, 0)
    market_value = _as_float(market_value, 0)
    if market_value <= 0 and market_price > 0:
        market_value = market_price * vol
    if market_price <= 0 and market_value > 0:
        market_price = market_value / vol
    return {"stock": stock, "volume": vol, "available": available,
            "cost": cost, "market_price": market_price, "market_value": market_value}


def _atomic_write_json(path, data):
    tmp = "%s.%s.%s.%s.tmp" % (
        path, os.getpid(), threading.get_ident(), int(time.time() * 1000000))
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)
    for attempt in range(8):
        try:
            os.replace(tmp, path)
            return
        except OSError:
            if attempt >= 7:
                try:
                    os.remove(tmp)
                except Exception:
                    pass
                raise
            time.sleep(0.02 * (attempt + 1))


def _account_dirs(acc_dir):
    dirs = {}
    for name in ("pending", "processing", "done"):
        dirs[name] = os.path.join(acc_dir, "orders", name)
        os.makedirs(dirs[name], exist_ok=True)
    dirs["cancel"] = os.path.join(acc_dir, "cancel")
    dirs["status"] = os.path.join(acc_dir, "status")
    os.makedirs(dirs["cancel"], exist_ok=True)
    os.makedirs(dirs["status"], exist_ok=True)
    return dirs


def discover_accounts():
    accounts = []
    if not os.path.isdir(IPC_ROOT):
        return accounts
    filt = None
    if ACCOUNT_FILTER:
        filt = set(a.strip() for a in ACCOUNT_FILTER.split(",") if a.strip())
    for name in sorted(os.listdir(IPC_ROOT)):
        sub = os.path.join(IPC_ROOT, name)
        if not os.path.isdir(sub):
            continue
        cfg = _load_json(os.path.join(sub, "config.json"))
        if not cfg:
            continue
        account_id = cfg.get("account_id") or name
        account_type = cfg.get("account_type") or "STOCK"
        qmt_path = cfg.get("qmt_path") or _DEFAULT_QMT_PATH
        ipc_secret = cfg.get("ipc_secret") or ""
        if filt and account_id not in filt:
            continue
        accounts.append({"account_id": account_id, "qmt_path": qmt_path,
                          "account_type": account_type,
                          "ipc_secret": ipc_secret,
                          "dir": sub, "dirs": _account_dirs(sub)})
    if not accounts and os.path.isdir(os.path.join(IPC_ROOT, "orders")):
        accounts.append({"account_id": _DEFAULT_ACCOUNT_ID,
                         "qmt_path": _DEFAULT_QMT_PATH, "account_type": "STOCK",
                         "dir": IPC_ROOT,
                         "dirs": _account_dirs(IPC_ROOT)})
    return accounts


def _lookup_qmt_symbol(name):
    g = globals().get(name)
    if callable(g):
        return g
    try:
        b = __builtins__
        if isinstance(b, dict):
            f = b.get(name)
        else:
            f = getattr(b, name, None)
        if callable(f):
            return f
    except Exception:
        pass
    ctx = _CONTEXT_INFO.get("obj")
    try:
        f = getattr(ctx, name, None) if ctx is not None else None
        if callable(f):
            return f
    except Exception:
        pass
    return None


def _get_vba_reader():
    """Look up `get_trade_detail_data` injected by QMT model-trading mode."""
    return _lookup_qmt_symbol("get_trade_detail_data")


def _make_stock_account(acc):
    try:
        _xttype = __import__("xtquant.xttype", fromlist=["StockAccount"])
        StockAccount = _xttype.StockAccount
        return StockAccount(acc["account_id"], acc.get("account_type", "STOCK")), ""
    except Exception as e:
        return None, str(e)[:120]


def _call_with_timeout(fn, args, timeout_sec):
    box = {"value": None, "err": None}
    def _run():
        try:
            box["value"] = fn(*args)
        except Exception as e:
            box["err"] = e
    th = threading.Thread(target=_run, daemon=True)
    th.start()
    th.join(timeout_sec)
    if th.is_alive():
        return False, None, "timeout(%ss)" % timeout_sec
    if box["err"] is not None:
        return False, None, str(box["err"])[:120]
    return True, box["value"], ""


def _call_account_method(trader, method_name, account_obj, account_id):
    method = getattr(trader, method_name, None)
    if not callable(method):
        return False, None, "missing"
    last_err = "not called"
    for label, arg in (("StockAccount", account_obj), ("account_id", account_id)):
        if arg is None:
            continue
        try:
            ok, data, err = _call_with_timeout(method, (arg,), XT_QUERY_TIMEOUT_SEC)
            if not ok:
                last_err = "%s %s" % (label, err)
                continue
            if isinstance(data, str):
                last_err = "%s returned str: %s" % (label, data[:80])
                continue
            return True, data, label
        except Exception as e:
            last_err = "%s error: %s" % (label, str(e)[:120])
    return False, None, last_err


def _snapshot_from_xttrader(acc):
    account_id = acc["account_id"]
    trader = None
    try:
        account_obj, account_err = _make_stock_account(acc)
        if account_obj is None:
            log("[%s] snapshot xttrader StockAccount unavailable: %s" % (account_id, account_err))

        trader = _try_connect_xttrader(acc["qmt_path"])
        if trader is None:
            log("[%s] snapshot xttrader unavailable, fallback to VBA" % account_id)
            return None
        log("[%s] snapshot xttrader connected (path=%s)" % (account_id, acc["qmt_path"]))

        if account_obj is not None and hasattr(trader, "subscribe"):
            try:
                ok, rc, err = _call_with_timeout(trader.subscribe, (account_obj,), XT_QUERY_TIMEOUT_SEC)
                if ok:
                    log("[%s] snapshot xttrader subscribe rc=%s" % (account_id, rc))
                else:
                    log("[%s] snapshot xttrader subscribe failed: %s" % (account_id, err))
            except Exception as e:
                log("[%s] snapshot xttrader subscribe error: %s" % (account_id, str(e)[:120]))

        ok_asset, asset, asset_via = _call_account_method(
            trader, "query_stock_asset", account_obj, account_id)
        if not ok_asset or asset is None:
            log("[%s] snapshot xttrader asset failed: %s" % (account_id, asset_via))
            return None

        ok_pos, pos_data, pos_via = _call_account_method(
            trader, "query_stock_positions", account_obj, account_id)
        if not ok_pos:
            log("[%s] snapshot xttrader positions failed: %s" % (account_id, pos_via))
            return None

        positions = []
        total_mv = 0.0
        for p in (pos_data or []):
            if isinstance(p, str):
                continue
            stock = _first_attr(p, ["stock_code", "m_strInstrumentID", "code", "instrument_id"], "")
            vol = _as_int(_first_attr(p, ["volume", "m_nVolume"], 0))
            av = _as_int(_first_attr(p, ["can_use_volume", "available", "m_nCanUseVolume"], vol))
            cost = _as_float(_first_attr(p, ["open_price", "avg_price", "cost_price", "m_dOpenPrice"], 0))
            mp = _as_float(_first_attr(p, ["market_price", "last_price", "m_dLastPrice"], 0))
            mv = _as_float(_first_attr(p, ["market_value", "m_dMarketValue"], mp * vol))
            row = _make_position(stock, vol, av, cost, mp, mv)
            if row is None:
                continue
            total_mv += row["market_value"]
            positions.append(row)

        market_value = _as_float(_first_attr(asset, ["market_value", "m_dMarketValue"], total_mv))
        if market_value <= 0:
            market_value = total_mv
        available_cash = _as_float(_first_attr(asset, ["cash", "available", "m_dAvailable"], 0))
        total_asset = _as_float(_first_attr(asset, ["total_asset", "m_dTotalAsset", "asset"], 0))
        if total_asset <= 0:
            total_asset = available_cash + market_value
        snap = {
            "timestamp": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
            "account_id": account_id,
            "source": "xttrader",
            "total_asset": total_asset,
            "available": available_cash,
            "market_value": market_value,
            "frozen": _as_float(_first_attr(asset, ["frozen_cash", "frozen", "m_dFrozen"], 0)),
            "positions": positions,
            "today_pnl": _as_float(_first_attr(asset, ["position_profit", "pnl", "m_dPositionProfit"], 0)),
        }
        log("[%s] snapshot xttrader: total=%.0f positions=%d via asset=%s pos=%s" % (
            account_id, snap["total_asset"], len(positions), asset_via, pos_via))
        return snap
    except Exception as e:
        log("[%s] snapshot xttrader error: %s\n%s" % (account_id, e, traceback.format_exc()))
        return None
    finally:
        try:
            if trader is not None and hasattr(trader, "stop"):
                trader.stop()
        except Exception:
            pass


def write_snapshot(acc):
    """Write account snapshot. Prefer xttrader; use VBA as fallback."""
    account_id = acc["account_id"]
    snap = _snapshot_from_xttrader(acc)
    if snap is not None:
        _atomic_write_json(os.path.join(acc["dirs"]["status"], "account.json"), snap)
        return True

    gtdd = _get_vba_reader()
    if not callable(gtdd):
        log("[%s] snapshot skipped: VBA reader not found" % account_id)
        return False

    account, positions = None, None

    # Account cash
    for args in [(account_id, "STOCK", "ACCOUNT"),
                 (account_id, "stock", "account"),
                 (account_id, "ACCOUNT")]:
        try:
            data = gtdd(*args)
            if data:
                o = data[0]
                account = {
                    "total_asset": float(getattr(o, "m_dTotalAsset",
                                          getattr(o, "m_dBalance", 0))),
                    "available": float(getattr(o, "m_dAvailable", 0)),
                    "market_value": 0.0,
                    "frozen": float(getattr(o, "m_dFrozen", 0)),
                    "pnl": 0.0,
                }
                break
        except Exception:
            continue

    # Positions
    for args in [(account_id, "STOCK", "POSITION"), (account_id, "POSITION")]:
        try:
            pos_data = gtdd(*args)
            positions = []
            if pos_data:
                total_mv = 0.0
                for p in pos_data:
                    stk = getattr(p, "m_strInstrumentID", "")
                    vol = int(getattr(p, "m_nVolume", 0))
                    av = int(getattr(p, "m_nCanUseVolume", vol))
                    cost = float(getattr(p, "m_dOpenPrice", 0))
                    mp = float(getattr(p, "m_dLastPrice", 0))
                    mv = float(getattr(p, "m_dMarketValue", mp * vol))
                    row = _make_position(stk, vol, av, cost, mp, mv)
                    if row is None:
                        continue
                    total_mv += row["market_value"]
                    positions.append(row)
                if account and account.get("market_value", 0) == 0:
                    account["market_value"] = total_mv
            break
        except Exception:
            continue

    if account is None:
        log("[%s] snapshot failed: VBA returned no account data" % account_id)
        return False

    snap = {
        "timestamp": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        "account_id": account_id,
        "source": "vba",
        "total_asset": max(account.get("total_asset", 0),
                           account.get("available", 0) + account.get("market_value", 0)),
        "available": account.get("available", 0),
        "market_value": account.get("market_value", 0),
        "frozen": account.get("frozen", 0),
        "positions": positions or [],
        "today_pnl": account.get("pnl", 0),
    }
    _atomic_write_json(os.path.join(acc["dirs"]["status"], "account.json"), snap)
    log("[%s] snapshot VBA: total=%.0f positions=%d" % (
        account_id, snap["total_asset"], len(positions or [])))
    return True


def write_done(dirs, processing_path, order, status, msg,
               filled_price=0, filled_vol=0):
    result = {
        "version": "1.0",
        "order_id": order["order_id"],
        "orig_timestamp": order.get("timestamp", ""),
        "exec_timestamp": datetime.now().strftime("%Y-%m-%d %H:%M:%S.%f")[:23],
        "status": status,
        "action": order.get("action", ""),
        "stock_code": order.get("stock_code", ""),
        "filled_price": filled_price,
        "filled_volume": filled_vol,
        "total_volume": order["volume"],
        "strategy": order.get("strategy", ""),
        "remark": order.get("remark", ""),
        "error": msg if status in ("rejected", "error", "cancelled_by_user") else None,
    }
    _atomic_write_json(os.path.join(dirs["done"], os.path.basename(processing_path)), result)
    try:
        os.remove(processing_path)
    except Exception:
        pass


def _order_secret_valid(acc, order):
    secret = acc.get("ipc_secret") or ""
    if not secret:
        return True
    return str(order.get("secret", "")) == str(secret)


def _try_connect_xttrader(qmt_path):
    """Import + connect XtQuantTrader. Returns trader or None."""
    box = {"t": None, "rc": None, "err": None}
    def _c():
        try:
            _xt = __import__("xtquant.xttrader", fromlist=["XtQuantTrader"])
            XtQuantTrader = _xt.XtQuantTrader
            t = XtQuantTrader(qmt_path, int(time.time() * 1000) % 1000000)
            if hasattr(t, "start"):
                t.start()
            box["rc"] = t.connect()
            box["t"] = t
        except Exception as e:
            box["err"] = e
    th = threading.Thread(target=_c, daemon=True); th.start(); th.join(XT_CONNECT_TIMEOUT_SEC)
    if th.is_alive():
        log("xttrader import/connect timeout (%ss) for %s" % (XT_CONNECT_TIMEOUT_SEC, qmt_path))
        return None
    if box["err"] is not None:
        log("xttrader import/connect error for %s: %s" % (qmt_path, str(box["err"])[:120]))
        return None
    if box["rc"] not in (0, None):
        log("xttrader connect rc=%s for %s" % (box["rc"], qmt_path))
        try:
            if box["t"] is not None and hasattr(box["t"], "stop"):
                box["t"].stop()
        except Exception:
            pass
        return None
    return box["t"]


def _cancel_xt_order(trader, account_obj, account_id, order_id):
    last_err = "cancel method missing"
    for method_name in ("cancel_order_stock", "cancel_order"):
        method = getattr(trader, method_name, None)
        if not callable(method):
            continue
        for label, account_arg in (("StockAccount", account_obj), ("account_id", account_id)):
            if account_arg is None:
                continue
            ok, ret, err = _call_with_timeout(method, (account_arg, order_id), XT_QUERY_TIMEOUT_SEC)
            if ok:
                return True, ret, "%s/%s" % (method_name, label)
            last_err = "%s/%s %s" % (method_name, label, err)
    return False, None, last_err


def _write_heartbeat(acc):
    """Refresh this account's heartbeat. Called at each main tick and, crucially,
    during the order-wait loop so a slow order does not starve the heartbeat and
    make the strategy side falsely detect a disconnect."""
    _atomic_write_json(os.path.join(acc["dirs"]["status"], "heartbeat.json"),
                       {"ts": datetime.now().isoformat(), "account_id": acc["account_id"]})


def _heartbeat_loop(acc):
    account_id = acc["account_id"]
    sleep_sec = HEARTBEAT_INTERVAL_SEC
    if sleep_sec <= 0:
        sleep_sec = 2.0
    if sleep_sec < 0.2:
        sleep_sec = 0.2
    log("[%s] heartbeat loop started interval=%.3fs" % (account_id, sleep_sec))
    while True:
        try:
            _write_heartbeat(acc)
        except Exception as e:
            log("[%s] heartbeat write failed: %s" % (account_id, str(e)[:120]))
        time.sleep(sleep_sec)


def _ensure_heartbeat_thread(acc):
    account_id = acc["account_id"]
    with _HEARTBEAT_LOCK:
        state = _HEARTBEAT_STATE.get(account_id) or {}
        th = state.get("thread")
        if th is not None and th.is_alive():
            return False
        th = threading.Thread(target=_heartbeat_loop, args=(acc,),
                              name="QmtIpcHeartbeat-%s" % account_id)
        th.daemon = True
        _HEARTBEAT_STATE[account_id] = {"thread": th, "started_at": time.time()}
        th.start()
        return True


def _order_result_from_status(status, traded_price, traded_vol, terminal_only=False):
    if status == ORDER_ALL_TRADED:
        return {"status": "filled", "price": traded_price, "vol": traded_vol}
    if status == ORDER_PART_TRADED_CANCELED:
        return {"status": "partial_cancelled", "price": traded_price, "vol": traded_vol}
    if status == ORDER_CANCELED:
        if traded_vol > 0:
            return {"status": "partial_cancelled", "price": traded_price, "vol": traded_vol}
        return {"status": "cancelled", "price": 0, "vol": 0}
    if status == ORDER_REJECTED:
        return {"status": "rejected", "price": traded_price, "vol": traded_vol}
    if status == ORDER_PART_TRADED and traded_vol > 0:
        if terminal_only:
            return {"status": "partial", "price": traded_price, "vol": traded_vol}
        return {"status": "partial", "price": traded_price, "vol": traded_vol}
    return None


def _query_xt_order_result(trader, account_obj, account_id, seq, terminal_only=False):
    ok_orders, orders, orders_via = _call_account_method(
        trader, "query_stock_orders", account_obj, account_id)
    if not ok_orders:
        return None, orders_via
    for o in (orders or []):
        oid2 = _first_attr(o, ["order_id", "order_sysid"], "")
        if str(oid2) != str(seq):
            continue
        status = _as_int(_first_attr(o, ["order_status"], 0))
        traded_price = _as_float(_first_attr(o, ["traded_price"], 0))
        traded_vol = _as_int(_first_attr(o, ["traded_vol", "traded_volume"], 0))
        return _order_result_from_status(status, traded_price, traded_vol, terminal_only), ""
    return None, "order not found"


def process_one_order(acc, filepath):
    dirs, account_id = acc["dirs"], acc["account_id"]
    filename = os.path.basename(filepath)
    order = None
    trader = None
    try:
        processing_path = os.path.join(dirs["processing"], filename)
        shutil.move(filepath, processing_path)
        try: os.utime(processing_path, None)
        except OSError: pass
        order = _load_json(processing_path)
        if not order:
            order = {"order_id": os.path.splitext(filename)[0].replace("ord_", ""),
                     "volume": 0}
            log("[%s] invalid order json %s, write error" % (account_id, filename))
            write_done(dirs, processing_path, order, "error", "invalid order json")
            return
        if not _order_secret_valid(acc, order):
            log("[%s] invalid order secret %s, write error" % (account_id, filename))
            write_done(dirs, processing_path, order, "error", "invalid order secret")
            return
        oid = order["order_id"]
        log("[%s] handle %s: %s %s %s" % (account_id, oid, order["action"],
                                           order["stock_code"], order["volume"]))
        cancel_path = os.path.join(dirs["cancel"], "cancel_%s.json" % oid)
        if os.path.exists(cancel_path):
            write_done(dirs, processing_path, order, "cancelled", "user cancel")
            os.remove(cancel_path); return
        trader = _try_connect_xttrader(acc["qmt_path"])
        if trader is None:
            write_done(dirs, processing_path, order, "rejected", "xttrader connect timeout/error")
            return
        account_obj, account_err = _make_stock_account(acc)
        if account_obj is None:
            log("[%s] order StockAccount unavailable, use account_id fallback: %s" % (account_id, account_err))
        elif hasattr(trader, "subscribe"):
            ok, rc, err = _call_with_timeout(trader.subscribe, (account_obj,), XT_QUERY_TIMEOUT_SEC)
            if not ok:
                log("[%s] order subscribe failed: %s" % (account_id, err))
        account_arg = account_obj if account_obj is not None else account_id
        xt_action = STOCK_BUY if order["action"] == "buy" else STOCK_SELL
        if order.get("price_type") == "market":
            price_type, price = LATEST_PRICE, 0
        else:
            price_type, price = FIX_PRICE, order["price"]
        ok, seq, err = _call_with_timeout(
            trader.order_stock,
            (account_arg, order["stock_code"], xt_action, order["volume"],
             price_type, price, order.get("strategy", ""), order.get("remark", "")),
            XT_QUERY_TIMEOUT_SEC)
        if not ok:
            write_done(dirs, processing_path, order, "rejected", "order_stock failed: %s" % err)
            return
        try:
            if int(seq) <= 0:
                write_done(dirs, processing_path, order, "rejected", "order_stock returned %s" % seq)
                return
        except Exception:
            if not str(seq).strip():
                write_done(dirs, processing_path, order, "rejected", "order_stock returned empty seq")
                return
        log("[%s] order seq=%s" % (account_id, seq))
        timeout = order.get("timeout_sec", 30)
        deadline = time.time() + timeout
        result = None
        last_partial = None
        while time.time() < deadline:
            time.sleep(0.5)
            _write_heartbeat(acc)  # keep heartbeat fresh during blocking order wait
            if os.path.exists(cancel_path):
                ok, ret, via = _cancel_xt_order(trader, account_obj, account_id, seq)
                if ok:
                    log("[%s] inflight cancel sent oid=%s seq=%s" % (account_id, oid, seq))
                else:
                    log("[%s] inflight cancel failed oid=%s seq=%s: %s" % (account_id, oid, seq, via))
                try: os.remove(cancel_path)
                except Exception: pass
            current_result, orders_via = _query_xt_order_result(
                trader, account_obj, account_id, seq)
            if orders_via and orders_via != "order not found":
                log("[%s] query_stock_orders failed during wait: %s" % (account_id, orders_via))
                continue
            if current_result:
                if current_result["status"] == "partial":
                    last_partial = current_result
                    continue
                result = current_result
                break
        if result is None:
            _cancel_xt_order(trader, account_obj, account_id, seq)
            current_result, _ = _query_xt_order_result(
                trader, account_obj, account_id, seq, terminal_only=True)
            if current_result and current_result.get("vol", 0) > 0:
                result = current_result
            elif last_partial and last_partial.get("vol", 0) > 0:
                result = last_partial
            else:
                result = {"status": "cancelled_timeout", "price": 0, "vol": 0}
            log("[%s] order %s timeout(%ss) cancelled" % (account_id, oid, timeout))
        write_done(dirs, processing_path, order, result["status"],
                   "price=%s, vol=%s" % (result["price"], result["vol"]),
                   filled_price=result["price"], filled_vol=result["vol"])
    except Exception as e:
        log("[%s] error: %s\n%s" % (account_id, e, traceback.format_exc()))
        if order:
            write_done(dirs, processing_path, order, "error", str(e))
    finally:
        try:
            if trader is not None and hasattr(trader, "stop"):
                trader.stop()
        except Exception:
            pass


def recover_leftovers(acc):
    dirs, account_id = acc["dirs"], acc["account_id"]
    try: names = os.listdir(dirs["processing"])
    except OSError: return
    now = time.time()
    for fn in names:
        if not fn.endswith(".json"): continue
        fp = os.path.join(dirs["processing"], fn)
        try:
            if now - os.path.getmtime(fp) < PROCESSING_STALE_SEC: continue
            order = _load_json(fp) or {}
        except OSError: continue
        order.setdefault("order_id", os.path.splitext(fn)[0].replace("ord_", ""))
        order.setdefault("volume", 0)
        log("[%s] recover leftover processing %s (>%ss), write error" % (account_id, fn, PROCESSING_STALE_SEC))
        write_done(dirs, fp, order, "error", "executor interrupted leftover, abandoned (fill unknown)")


def archive_old(acc):
    dirs = acc["dirs"]
    archive_dir = os.path.join(acc["dir"], "orders", "done_archive")
    try: names = os.listdir(dirs["done"])
    except OSError: return
    now = time.time(); moved = 0
    for fn in names:
        if not fn.endswith(".json"): continue
        fp = os.path.join(dirs["done"], fn)
        try:
            if now - os.path.getmtime(fp) < DONE_RETENTION_SEC: continue
            os.makedirs(archive_dir, exist_ok=True)
            shutil.move(fp, os.path.join(archive_dir, fn)); moved += 1
        except Exception: continue
    if moved: log("[%s] archived %d old done -> done_archive/" % (acc["account_id"], moved))


def _snapshot_due(acc):
    account_id = acc["account_id"]
    now = time.time()
    last = _LAST_SNAPSHOT_ATTEMPT.get(account_id, 0)
    if now - last < SNAPSHOT_INTERVAL_SEC:
        return False
    snap_path = os.path.join(acc["dirs"]["status"], "account.json")
    try:
        if os.path.exists(snap_path) and now - os.path.getmtime(snap_path) < SNAPSHOT_INTERVAL_SEC:
            return False
    except OSError:
        pass
    _LAST_SNAPSHOT_ATTEMPT[account_id] = now
    return True


def _snapshot_worker(acc):
    account_id = acc["account_id"]
    try:
        write_snapshot(acc)
        archive_old(acc)
    except Exception as e:
        log("[%s] snapshot worker error: %s" % (account_id, str(e)[:120]))
    finally:
        with _SNAPSHOT_LOCK:
            state = _SNAPSHOT_STATE.get(account_id)
            if state and state.get("thread") is threading.current_thread():
                state["finished_at"] = time.time()


def _start_snapshot_task(acc):
    account_id = acc["account_id"]
    now = time.time()
    with _SNAPSHOT_LOCK:
        state = _SNAPSHOT_STATE.get(account_id) or {}
        th = state.get("thread")
        if th is not None and th.is_alive():
            started_at = state.get("started_at", now)
            last_log = state.get("last_log", 0)
            if now - started_at >= SNAPSHOT_TASK_STALE_SEC and now - last_log >= MAIN_LOG_INTERVAL_SEC:
                state["last_log"] = now
                _SNAPSHOT_STATE[account_id] = state
                log("[%s] snapshot task still running %.0fs, skip new snapshot" % (
                    account_id, now - started_at))
            return False
        th = threading.Thread(target=_snapshot_worker, args=(acc,),
                              name="QmtIpcSnapshot-%s" % account_id)
        th.daemon = True
        _SNAPSHOT_STATE[account_id] = {
            "thread": th,
            "started_at": now,
            "last_log": 0,
        }
        th.start()
        return True


def _remember_context(ContextInfo):
    if ContextInfo is not None:
        _CONTEXT_INFO["obj"] = ContextInfo


def _builtin_callable(name):
    try:
        b = __builtins__
        if isinstance(b, dict):
            return callable(b.get(name))
        return callable(getattr(b, name, None))
    except Exception:
        return False


def _dump_context_info(ContextInfo):
    if _DIAG_DONE.get("ctx") or ContextInfo is None:
        return
    _DIAG_DONE["ctx"] = True
    try:
        import inspect
        members = [n for n, _ in inspect.getmembers(ContextInfo) if not n.startswith("_")]
    except Exception as e:
        log("ContextInfo dump failed: %s" % str(e)[:120])
        members = []
    log("ContextInfo has %d public members" % len(members))
    for i in range(0, len(members), 35):
        log("ContextInfo members[%03d:%03d]: %s" % (
            i, min(i + 35, len(members)), ", ".join(members[i:i + 35])))
    keys = ("trade", "order", "account", "position", "asset", "query", "pass", "cancel")
    trade_like = [n for n in members if any(k in n.lower() for k in keys)]
    log("ContextInfo trade-like members: %s" % (", ".join(trade_like) if trade_like else "none"))
    for name in ("get_trade_detail_data", "passorder", "cancel",
                 "query_stock_asset", "query_stock_positions",
                 "query_account", "order_stock", "cancel_order"):
        try:
            ctx_ok = callable(getattr(ContextInfo, name, None))
        except Exception:
            ctx_ok = False
        log("QMT symbol %s callable: globals=%s builtins=%s ContextInfo=%s" % (
            name, callable(globals().get(name)), _builtin_callable(name), ctx_ok))


def handle_account(acc):
    """Heartbeat, leftovers, pending orders, account snapshot."""
    dirs = acc["dirs"]
    _ensure_heartbeat_thread(acc)
    _write_heartbeat(acc)
    recover_leftovers(acc)
    pending_dir = dirs["pending"]
    pending = sorted([f for f in os.listdir(pending_dir)
                      if f.endswith(".json") and not f.startswith(".")])
    for fn in pending[:5]:
        fp = os.path.join(pending_dir, fn)
        if os.path.exists(fp): process_one_order(acc, fp)
    if _snapshot_due(acc):
        _start_snapshot_task(acc)


def _worker_daemon_for(reason):
    forced = os.environ.get("QMT_IPC_WORKER_DAEMON")
    if forced is not None:
        return forced.strip().lower() not in ("0", "false", "no", "off")
    if reason in ("init", "handlebar"):
        return False
    return True


def _in_qmt_runtime():
    for name in ("get_trade_detail_data", "passorder", "cancel"):
        if callable(globals().get(name)):
            return True
    return False


def _foreground_loop_enabled(reason):
    forced = os.environ.get("QMT_IPC_FOREGROUND_LOOP")
    if forced is not None:
        return forced.strip().lower() not in ("0", "false", "no", "off")
    return reason in ("init", "handlebar") and _in_qmt_runtime()


def _top_level_worker_enabled():
    forced = os.environ.get("QMT_IPC_TOP_LEVEL_WORKER")
    if forced is not None:
        return forced.strip().lower() not in ("0", "false", "no", "off")
    return not _in_qmt_runtime()


def _worker_loop():
    log("worker loop started pid=%s daemon=%s interval=%.3fs root=%s" % (
        os.getpid(), threading.current_thread().daemon, MAIN_INTERVAL_SEC, IPC_ROOT))
    sleep_sec = MAIN_INTERVAL_SEC
    if sleep_sec <= 0:
        sleep_sec = 1.0
    if sleep_sec < 0.2:
        sleep_sec = 0.2
    while True:
        try:
            main()
        except Exception as e:
            log("worker loop error: %s\n%s" % (e, traceback.format_exc()))
        time.sleep(sleep_sec)


def _start_worker(reason):
    daemon = _worker_daemon_for(reason)
    with _WORKER_LOCK:
        th = _WORKER_STATE.get("thread")
        if th is not None and th.is_alive():
            if not th.daemon or daemon:
                return
            log("worker promote requested by %s (old daemon still alive)" % reason)
        th = threading.Thread(target=_worker_loop, name="QmtIpcExecutorWorker")
        th.daemon = daemon
        th.start()
        _WORKER_STATE["thread"] = th
        _WORKER_STATE["started_at"] = time.time()
        _WORKER_STATE["daemon"] = daemon
        log("worker start requested by %s daemon=%s" % (reason, daemon))


def _foreground_loop(reason):
    log("foreground loop started by %s pid=%s interval=%.3fs root=%s" % (
        reason, os.getpid(), MAIN_INTERVAL_SEC, IPC_ROOT))
    sleep_sec = MAIN_INTERVAL_SEC
    if sleep_sec <= 0:
        sleep_sec = 1.0
    if sleep_sec < 0.2:
        sleep_sec = 0.2
    while True:
        try:
            main()
        except Exception as e:
            log("foreground loop error: %s\n%s" % (e, traceback.format_exc()))
        time.sleep(sleep_sec)


def main():
    if not _MAIN_LOCK.acquire(False):
        return
    try:
        now = time.time()
        if now - _MAIN_STATE["last_run"] < MAIN_INTERVAL_SEC:
            return
        _MAIN_STATE["last_run"] = now
        _MAIN_STATE["ticks"] += 1
        accounts = discover_accounts()
        if not accounts:
            if now - _MAIN_STATE["last_log"] >= MAIN_LOG_INTERVAL_SEC:
                _MAIN_STATE["last_log"] = now
                log("no account dirs found (waiting for config.json)")
            return
        for acc in accounts:
            try: _ensure_heartbeat_thread(acc)
            except Exception as e: log("[%s] heartbeat start error: %s" % (acc.get("account_id", "?"), e))
        for acc in accounts:
            try: handle_account(acc)
            except Exception as e: log("[%s] handle_account error: %s" % (acc.get("account_id", "?"), e))
        if now - _MAIN_STATE["last_log"] >= MAIN_LOG_INTERVAL_SEC:
            _MAIN_STATE["last_log"] = now
            th = _WORKER_STATE.get("thread")
            worker_alive = th is not None and th.is_alive()
            log("tick ok accounts=%d ticks=%d worker=%s" % (
                len(accounts), _MAIN_STATE["ticks"], worker_alive))
    finally:
        _MAIN_LOCK.release()


def init(ContextInfo):
    _remember_context(ContextInfo)
    _dump_context_info(ContextInfo)
    if _foreground_loop_enabled("init"):
        _foreground_loop("init")
        return
    _start_worker("init")
    try: main()
    except Exception as e: log("init error: %s" % e)


def handlebar(ContextInfo):
    _remember_context(ContextInfo)
    if _foreground_loop_enabled("handlebar"):
        _foreground_loop("handlebar")
        return
    _start_worker("handlebar")
    try: main()
    except Exception as e: log("handlebar error: %s" % e)


try:
    if _top_level_worker_enabled():
        _start_worker("top-level")
    main()
except Exception as _e:
    import traceback as _tb; _tb.print_exc()
    try: log("top-level fault: %s" % _e)
    except Exception: pass
