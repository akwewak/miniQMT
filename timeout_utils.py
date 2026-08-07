"""超时执行辅助工具。"""
import concurrent.futures
import threading

from logger import get_logger

logger = get_logger("timeout_utils")

# 超时后无法回收的调用计数（Python 无法强制终止线程，只能观测）
_leak_lock = threading.Lock()
_leaked_calls = 0
# 每泄漏 N 次告警一次，避免刷屏
LEAK_WARN_INTERVAL = 10


def get_leaked_call_count():
    """返回累计的超时泄漏调用数，供健康检查/诊断读取。"""
    with _leak_lock:
        return _leaked_calls


def reset_leaked_call_count():
    """重置泄漏计数（供测试使用）。"""
    global _leaked_calls
    with _leak_lock:
        _leaked_calls = 0


def _record_leak(func):
    """记录一次无法回收的超时调用，并按间隔告警。"""
    global _leaked_calls
    with _leak_lock:
        _leaked_calls += 1
        count = _leaked_calls
    if count == 1 or count % LEAK_WARN_INTERVAL == 0:
        name = getattr(func, '__name__', repr(func))
        logger.warning(
            f"[TIMEOUT_LEAK] 调用 {name} 超时后仍在后台运行且无法终止，"
            f"累计泄漏 {count} 次。Python 无法强制杀死线程，若该数值持续增长，"
            f"说明底层(通常是 QMT)调用长期卡死，需人工检查 QMT 客户端状态。"
        )
    return count


def run_with_timeout(func, timeout):
    """在线程中执行阻塞调用，超时后不等待底层调用返回。

    注意：超时后底层线程**无法被终止**——future.cancel() 只能取消尚未开始的任务，
    cancel_futures 也不会中断已运行的线程。若底层调用永久阻塞（如 QMT 无响应），
    该线程会一直存活。此处记录泄漏计数并周期告警，使问题可观测，
    而不是假装已经处理。
    """
    executor = concurrent.futures.ThreadPoolExecutor(max_workers=1)
    future = executor.submit(func)
    try:
        return future.result(timeout=timeout)
    except concurrent.futures.TimeoutError:
        if not future.cancel():
            # cancel 失败 = 任务已在执行中，线程无法回收
            _record_leak(func)
        raise
    finally:
        try:
            executor.shutdown(wait=False, cancel_futures=True)
        except TypeError:
            # Python 3.8 不支持 cancel_futures 参数
            executor.shutdown(wait=False)
