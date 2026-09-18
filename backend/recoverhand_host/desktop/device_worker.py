from __future__ import annotations

import asyncio
import queue
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from PySide6.QtCore import QThread, Signal

from recoverhand_host.bootstrap import build_device_manager
from recoverhand_host.models import DeviceKind
from recoverhand_host.runtime.session_runtime import SessionRuntime


@dataclass(slots=True)
class DeviceWork:
    action: str
    payload: dict[str, Any]


class DeviceWorker(QThread):
    """在单独线程和固定 asyncio loop 中执行设备 I/O，并运行会话运行时。

    运行时采集循环复用 ``DeviceManager`` 已连接的驱动（BLE 驱动绑定在事件循环上，
    因此必须与设备连接在同一 loop 内运行）。运行时事件通过 ``runtime_event`` 信号
    转发到 Qt 主线程。
    """

    completed = Signal(str, object)
    failed = Signal(str, str)
    state_changed = Signal(object)
    runtime_event = Signal(object)  # 会话运行时的 RuntimeEvent（dict）

    def __init__(self) -> None:
        super().__init__()
        self._commands: queue.Queue[DeviceWork] = queue.Queue()
        self._stopping = False
        self._session_task: asyncio.Task[None] | None = None
        self._runtime: SessionRuntime | None = None

    def submit(self, action: str, **payload: Any) -> None:
        self._commands.put(DeviceWork(action=action, payload=payload))

    def stop(self) -> None:
        self._stopping = True
        self._commands.put(DeviceWork(action="stop", payload={}))

    def run(self) -> None:
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
        manager = build_device_manager()
        try:
            loop.run_until_complete(self._command_loop(manager))
        finally:
            loop.run_until_complete(self._cleanup(manager))
            loop.close()

    async def _cleanup(self, manager: Any) -> None:
        task, self._session_task = self._session_task, None
        if task is not None and not task.done():
            task.cancel()
            try:
                await task
            except asyncio.CancelledError:
                pass
        await manager.shutdown()

    async def _command_loop(self, manager: Any) -> None:
        """让设备事件循环持续运行，确保 BLE 通知和断线回调不会停摆。"""

        while not self._stopping:
            try:
                work = self._commands.get_nowait()
            except queue.Empty:
                await asyncio.sleep(0.02)
                continue
            if work.action == "stop":
                break
            if work.action == "start_session":
                if self._session_task is None:
                    self._session_task = asyncio.create_task(
                        self._run_session(manager, work.payload), name="session-runtime"
                    )
                self.completed.emit("start_session", {})
                continue
            if work.action == "stop_session":
                self._stop_session()
                self.completed.emit("stop_session", {})
                continue
            try:
                result = await self._execute(manager, work)
                self.state_changed.emit(manager.snapshot())
                self.completed.emit(work.action, result)
            except Exception as exc:  # noqa: BLE001 - 设备线程边界必须转成可见故障，不能静默退出
                self.state_changed.emit(manager.snapshot())
                self.failed.emit(work.action, str(exc))

    async def _run_session(self, manager: Any, payload: dict[str, Any]) -> None:
        runtime = SessionRuntime(payload["session_id"], Path(payload["data_root"]))
        self._runtime = runtime
        runtime.start(dict(payload.get("metadata", {})))
        events = runtime.subscribe()

        async def drain() -> None:
            while True:
                event = await events.get()
                self.runtime_event.emit(event.to_dict())

        drainer = asyncio.create_task(drain(), name="session-drain")
        try:
            drivers = manager.get_drivers()
            await runtime.run(
                drivers.get(DeviceKind.EEG),
                drivers.get(DeviceKind.EMG),
                drivers.get(DeviceKind.GLOVE),
                target_repetitions=int(payload.get("target_repetitions", 10)),
                tick_seconds=float(payload.get("tick_seconds", 0.05)),
                phase_durations=payload.get("phase_durations"),
                assist_strategy=payload.get("assist_strategy"),
            )
        except Exception as exc:  # noqa: BLE001 - 会话故障要可见
            self.failed.emit("session", str(exc))
        finally:
            drainer.cancel()
            try:
                await drainer
            except asyncio.CancelledError:
                pass
            runtime.stop("会话结束")
            runtime.unsubscribe(events)
            self._runtime = None
            self._session_task = None
            self.completed.emit("session_finished", runtime.snapshot())

    def _stop_session(self) -> None:
        runtime = self._runtime
        if runtime is not None:
            runtime.stop("操作者停止训练")

    @staticmethod
    async def _execute(manager: Any, work: DeviceWork) -> Any:
        if work.action == "connect_all":
            devices = work.payload["devices"]
            results: dict[str, Any] = {}
            for kind in DeviceKind:
                entry = devices[kind.value]
                results[kind.value] = await manager.connect(
                    kind, entry["driver_id"], dict(entry.get("config", {}))
                )
            return results
        if work.action == "preview_all":
            previews: dict[str, Any] = {}
            for kind in DeviceKind:
                previews[kind.value] = await manager.preview(kind)
            return previews
        if work.action == "disconnect_all":
            results = {}
            for kind in DeviceKind:
                results[kind.value] = await manager.disconnect(kind)
            return results
        if work.action == "connect_one":
            kind = DeviceKind(work.payload["kind"])
            return await manager.connect(
                kind,
                work.payload["driver_id"],
                dict(work.payload.get("config", {})),
            )
        if work.action == "preview_one":
            return await manager.preview(DeviceKind(work.payload["kind"]))
        if work.action == "command_one":
            return await manager.command(DeviceKind(work.payload["kind"]), work.payload["command"])
        raise ValueError(f"未知设备工作: {work.action}")
