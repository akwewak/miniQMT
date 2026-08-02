"""委托（Order）相关的共享常量与格式化工具。

web_server.py（Flask 直连）和 xtquant_manager/server.py（网关）都要把
QMT 原始委托对象映射成前端字段，此处收口以免两边各写一份、口径漂移。
"""
from datetime import datetime

# 委托状态码 → 中文描述
ORDER_STATUS_DESC = {
    48: "未报",
    49: "待报",
    50: "已报",
    51: "已报待撤",
    52: "部成待撤",
    53: "部撤",
    54: "已撤",
    55: "部成",
    56: "已成",
    57: "废单",
}

# 活跃（在途）委托状态码：已提交但尚未终结
ACTIVE_ORDER_STATUS = frozenset({48, 49, 50, 51, 52, 55})

# 委托类型码
ORDER_TYPE_BUY = 23
ORDER_TYPE_SELL = 24


def format_order_time(value):
    """格式化委托时间为 'YYYY-MM-DD HH:MM:SS'。

    QMT 的 order_time 是 Unix 秒级时间戳(int)，不能按字符串日期解析；
    同时兼容已经是字符串/datetime 的情形。无法解析时返回 None。
    """
    if value is None:
        return None

    if isinstance(value, datetime):
        return value.strftime('%Y-%m-%d %H:%M:%S')

    if isinstance(value, (int, float)) and not isinstance(value, bool):
        if value <= 0:
            return None
        try:
            return datetime.fromtimestamp(value).strftime('%Y-%m-%d %H:%M:%S')
        except (ValueError, OSError, OverflowError):
            return None

    text = str(value).strip()
    if not text:
        return None
    # 纯数字字符串同样按时间戳处理
    if text.isdigit():
        return format_order_time(int(text))

    normalized = text.replace('T', ' ')
    for fmt in ('%Y-%m-%d %H:%M:%S.%f', '%Y-%m-%d %H:%M:%S', '%Y-%m-%d %H:%M'):
        try:
            return datetime.strptime(normalized, fmt).strftime('%Y-%m-%d %H:%M:%S')
        except ValueError:
            pass
    return text


def is_pending(status):
    """委托是否处于在途（已报未成交/部成）状态。"""
    return status in ACTIVE_ORDER_STATUS


def status_desc(status, fallback=''):
    """委托状态描述，优先使用 QMT 回传的 status_msg。"""
    return fallback or ORDER_STATUS_DESC.get(status, '未知')


def sort_orders(orders):
    """就地排序：在途委托整体在前，组内按时间倒序（缺时间排最后）。"""
    orders.sort(key=lambda o: o.get('order_time') or '', reverse=True)
    orders.sort(key=lambda o: not o.get('is_pending'))
    return orders
