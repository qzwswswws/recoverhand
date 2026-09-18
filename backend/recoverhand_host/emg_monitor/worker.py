from __future__ import annotations

import asyncio
import queue
from collections.abc import Callable
from dataclasses import dataclass
from typing import Any

from PySide6.QtCore import QThread, Signal

from recoverhand_host.devices.waveletech_emg import WaveletechEmgDriver


@dataclass(slots=True)
class MonitorCommand:
    action: str
    config: dict[str, Any]


class EmgMonitorWorker(QThread):
    """在常驻 asyncio 事件循环中独占 BLE 设备，并以固定频率推送预览。"""

    scan_completed = Signal(object)
    connection_changed = Signal(bool, str)
    preview_ready = Signal(object)
    health_changed = Signal(object)
    failed = Signal(str, str)

    def __init__(
        self,
        driver_factory: Callable[[], WaveletechEmgDriver] = WaveletechEmgDriver,
        preview_interval_seconds: float = 0.04,
    ) -> None:
        super().__init__()
        self._driver_factory = driver_factory
        self._preview_interval_seconds = preview_interval_seconds
        self._commands: queue.Queue[MonitorCommand] = queue.Queue()
        self._stopping = False
        self._connected = False
        self._loop: asyncio.AbstractEventLoop | None = None
        self._monitor_task: asyncio.Task[None] | None = None

    def submit(self, action: str, config: dict[str, Any] | None = None) -> None:
        self._commands.put(MonitorCommand(action=action, config=dict(config or {})))

    def stop(self) -> None:
        self._stopping = True
        self._commands.put(MonitorCommand(action="stop", config={}))
        loop, task = self._loop, self._monitor_task
        if loop is not None and task is not None and not loop.is_closed():
            loop.call_soon_threadsafe(task.cancel)

    def run(self) -> None:
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
        driver = self._driver_factory()
        self._loop = loop
        self._monitor_task = loop.create_task(self._run_monitor(driver))
        try:
            loop.run_until_complete(self._monitor_task)
        except asyncio.CancelledError:
            pass
        finally:
            loop.run_until_complete(driver.disconnect())
            self._monitor_task = None
            self._loop = None
            loop.close()

    async def _run_monitor(self, driver: WaveletechEmgDriver) -> None:
        next_preview = asyncio.get_running_loop().time()
        while not self._stopping:
            await self._drain_one_command(driver)
            now = asyncio.get_running_loop().time()
            if self._connected and now >= next_preview:
                try:
                    preview = await driver.preview()
                    health = await driver.health()
                    self.preview_ready.emit(preview)
                    self.health_changed.emit(health.to_dict())
                except Exception as exc:  # noqa: BLE001 - 工作线程边界统一转成可见故障。
                    self._connected = False
                    self.failed.emit("stream", str(exc))
                    self.connection_changed.emit(False, "数据流已停止")
                next_preview = now + self._preview_interval_seconds
            await asyncio.sleep(0.01)

    async def _drain_one_command(self, driver: WaveletechEmgDriver) -> None:
        try:
            command = self._commands.get_nowait()
        except queue.Empty:
            return
        if command.action == "stop":
            self._stopping = True
            return
        try:
            if command.action == "scan":
                if self._connected:
                    raise RuntimeError("请先断开当前肌电贴再重新扫描")
                self.scan_completed.emit(await driver.discover(command.config))
                return
            if command.action == "connect":
                if self._connected:
                    await driver.disconnect()
                await driver.connect(command.config)
                await driver.start_stream()
                self._connected = True
                self.connection_changed.emit(True, "已连接并收到原始肌电数据")
                return
            if command.action == "disconnect":
                await driver.disconnect()
                self._connected = False
                self.connection_changed.emit(False, "已断开")
                return
            raise ValueError(f"未知监视器命令: {command.action}")
        except Exception as exc:  # noqa: BLE001 - 工作线程边界统一转成可见故障。
            if command.action == "connect":
                await driver.disconnect()
                self._connected = False
            self.failed.emit(command.action, str(exc))
