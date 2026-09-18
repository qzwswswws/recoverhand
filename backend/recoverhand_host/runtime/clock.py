from __future__ import annotations

import time

NS_PER_SECOND = 1_000_000_000


def now_ns() -> int:
    """统一主机单调时钟（纳秒），用于运行时内的事件排序与时间差计算。

    使用 ``time.monotonic_ns()`` 而非墙钟时间：单调时钟不受系统校时影响，
    保证同一会话内事件的前后关系与时间差可复现、可离线对齐。
    """
    return time.monotonic_ns()
