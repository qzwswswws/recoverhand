from __future__ import annotations

import asyncio
from collections.abc import Callable

from recoverhand_host.models import RuntimeEvent


class EventBus:
    """有界事件总线：状态机、监督器与采集循环向订阅者广播 RuntimeEvent。

    队列满时丢弃最旧事件（drop-oldest），保证实时性优先、消费方永远读到
    最新状态，而不是被积压的历史事件拖垮。

    记录器通过 ``add_sink`` 注册为同步 sink，每一条事件都同步落盘、不丢不弃。
    """

    def __init__(self, maxsize: int = 256) -> None:
        self._maxsize = maxsize
        self._subscribers: set[asyncio.Queue[RuntimeEvent]] = set()
        self._sinks: set[Callable[[RuntimeEvent], None]] = set()

    def subscribe(self) -> asyncio.Queue[RuntimeEvent]:
        queue: asyncio.Queue[RuntimeEvent] = asyncio.Queue(maxsize=self._maxsize)
        self._subscribers.add(queue)
        return queue

    def unsubscribe(self, queue: asyncio.Queue[RuntimeEvent]) -> None:
        self._subscribers.discard(queue)

    def add_sink(self, sink: Callable[[RuntimeEvent], None]) -> None:
        self._sinks.add(sink)

    def remove_sink(self, sink: Callable[[RuntimeEvent], None]) -> None:
        self._sinks.discard(sink)

    def publish(self, event: RuntimeEvent) -> None:
        for sink in tuple(self._sinks):
            sink(event)
        for queue in tuple(self._subscribers):
            if queue.full():
                try:
                    queue.get_nowait()
                except asyncio.QueueEmpty:
                    pass
            queue.put_nowait(event)
