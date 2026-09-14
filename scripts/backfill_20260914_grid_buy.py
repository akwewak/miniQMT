# -*- coding: utf-8 -*-
"""补录 2026-09-14 13:29:33 301085.SZ 网格买入的缺失流水。

背景：v3.9.1 起 trading_executor 调用 settlement_db.record_trade(conn=self.conn)
后未提交（record_trade 只在 owns_conn 时 commit），写事务悬在 data_manager
共享连接上并最终随连接回滚 —— 日志显示"保存交易记录成功"但 trade_records
里没有这一行。网格侧数据（grid_trades / grid_lots / grid_orders / 会话汇总）
均完整，只缺交割单流水。

同时修正 session 27 的 current_center_price：13:29 买入后应重建为 70.34，
当时因 database is locked 写库失败，内存与 DB 劈叉。

用法:
    python scripts/backfill_20260914_grid_buy.py --dry-run
    python scripts/backfill_20260914_grid_buy.py --execute
"""
import argparse
import os
import sqlite3
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

DB_PATH = os.path.join('data_25105132', 'trading.db')

# 口径依据（逐项可溯源，不臆造）：
#   price/volume/amount  <- grid_trades id=88、grid_orders 1745879043(filled)
#   trade_time/deal_time <- 成交回报到达时刻 13:29:33（日志 13:29:33,690）
#   time_source          <- exchange，与同会话 10:08 那条一致
#   commission           <- 0.0 + commission_source='unknown'，与 10:08 那条一致
#                           （券商未回传，绝不臆造费用）
#   strategy_label       <- '网格'，与 10:08 那条一致
TRADE = {
    'stock_code': '301085.SZ',
    'stock_name': '亚康股份',
    'trade_time': '2026-09-14 13:29:33',
    'trade_type': 'BUY',
    'price': 70.34,
    'volume': 200,
    'amount': 14068.0,
    'trade_id': '1745879043',
    'commission': 0.0,
    'strategy': 'grid',
    'account': '25105132',
    'deal_time': None,          # 运行时由 trade_time 换算
    'deal_time_str': '2026-09-14 13:29:33',
    'recorded_at': '2026-09-14 13:29:33',
    'time_source': 'exchange',
    'order_id': '1745879043',
    'fill_ids': '1745879043',
    'fills': 1,
    'strategy_label': '网格',
    'is_simulation': 0,
    'commission_source': 'unknown',
    'commission_rate': None,
    'side_source': 'deal',
    'row_status': 'active',
    'trade_id_source': 'order_id',
}

SESSION_ID = 27
CENTER_PRICE_EXPECTED_OLD = 73.4
CENTER_PRICE_NEW = 70.34


def _deal_epoch(ts_str):
    from datetime import datetime
    return int(datetime.strptime(ts_str, '%Y-%m-%d %H:%M:%S').timestamp())


def main():
    ap = argparse.ArgumentParser()
    g = ap.add_mutually_exclusive_group(required=True)
    g.add_argument('--dry-run', action='store_true', help='只预演，不写库')
    g.add_argument('--execute', action='store_true', help='正式执行')
    ap.add_argument('--db', default=DB_PATH)
    args = ap.parse_args()

    if not os.path.exists(args.db):
        print(f"[ERROR] 数据库不存在: {args.db}")
        return 2

    conn = sqlite3.connect(args.db, timeout=30.0)
    conn.row_factory = sqlite3.Row
    try:
        # ---------- 前置校验 ----------
        dup = conn.execute(
            "SELECT COUNT(*) c FROM trade_records WHERE trade_id=? AND stock_code=?",
            (TRADE['trade_id'], TRADE['stock_code'])).fetchone()['c']
        if dup:
            print(f"[SKIP] trade_records 已存在 trade_id={TRADE['trade_id']}，无需补录")
            return 0

        gt = conn.execute(
            "SELECT id, volume, amount, trigger_price FROM grid_trades WHERE trade_id=?",
            (TRADE['trade_id'],)).fetchone()
        if gt is None:
            print("[ERROR] grid_trades 中找不到对应成交，拒绝补录（避免凭空造数据）")
            return 2
        # 与网格账本交叉核对，任一不符即中止
        if (int(gt['volume']) != TRADE['volume']
                or abs(float(gt['trigger_price']) - TRADE['price']) > 1e-6
                or abs(float(gt['amount']) - TRADE['amount']) > 1e-6):
            print(f"[ERROR] 与 grid_trades 不一致，拒绝补录: "
                  f"grid_trades(vol={gt['volume']}, px={gt['trigger_price']}, "
                  f"amt={gt['amount']}) vs 本次(vol={TRADE['volume']}, "
                  f"px={TRADE['price']}, amt={TRADE['amount']})")
            return 2
        print(f"[OK] 已与 grid_trades id={gt['id']} 交叉核对一致")

        sess = conn.execute(
            "SELECT current_center_price FROM grid_trading_sessions WHERE id=?",
            (SESSION_ID,)).fetchone()
        if sess is None:
            print(f"[ERROR] 找不到 session {SESSION_ID}")
            return 2
        cur_center = float(sess['current_center_price'])
        fix_center = abs(cur_center - CENTER_PRICE_EXPECTED_OLD) < 1e-6
        if not fix_center:
            print(f"[NOTE] session {SESSION_ID} 中心价当前={cur_center}，"
                  f"非预期的 {CENTER_PRICE_EXPECTED_OLD}（可能已被手工修正），"
                  f"本次不改动中心价")

        rec = dict(TRADE)
        rec['deal_time'] = _deal_epoch(rec['deal_time_str'])

        print("\n将写入 trade_records:")
        for k in ('stock_code', 'stock_name', 'trade_time', 'trade_type', 'price',
                  'volume', 'amount', 'trade_id', 'order_id', 'strategy',
                  'strategy_label', 'time_source', 'deal_time', 'deal_time_str',
                  'commission', 'commission_source', 'account'):
            print(f"    {k:<20} = {rec[k]!r}")
        if fix_center:
            print(f"\n将修正 session {SESSION_ID} 中心价: "
                  f"{cur_center} -> {CENTER_PRICE_NEW}")

        if args.dry_run:
            print("\n[DRY-RUN] 未写入任何数据")
            return 0

        # ---------- 正式执行（单事务） ----------
        cols = ('account', 'stock_code', 'stock_name', 'trade_time', 'trade_type',
                'price', 'volume', 'amount', 'trade_id', 'commission', 'strategy',
                'deal_time', 'deal_time_str', 'recorded_at', 'time_source',
                'order_id', 'fill_ids', 'fills', 'strategy_label', 'is_simulation',
                'commission_source', 'commission_rate', 'side_source',
                'row_status', 'trade_id_source')
        conn.execute("BEGIN IMMEDIATE")
        cur = conn.execute(
            "INSERT OR IGNORE INTO trade_records(%s) VALUES (%s)"
            % (','.join(cols), ','.join('?' * len(cols))),
            tuple(rec[c] for c in cols))
        if cur.rowcount != 1:
            conn.rollback()
            print("[ERROR] INSERT 被唯一索引挡下（rowcount=0），已回滚")
            return 2
        if fix_center:
            conn.execute(
                "UPDATE grid_trading_sessions SET current_center_price=?, "
                "updated_at=CURRENT_TIMESTAMP WHERE id=?",
                (CENTER_PRICE_NEW, SESSION_ID))
        conn.commit()
        print(f"\n[DONE] 已补录 trade_records id={cur.lastrowid}"
              + (f"；session {SESSION_ID} 中心价已修正为 {CENTER_PRICE_NEW}"
                 if fix_center else ""))
        return 0
    finally:
        conn.close()


if __name__ == '__main__':
    sys.exit(main())
