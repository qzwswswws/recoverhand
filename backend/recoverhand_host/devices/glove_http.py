from __future__ import annotations

import asyncio
import json
from typing import Any
from urllib.error import URLError
from urllib.request import Request, urlopen

from recoverhand_host.devices.base import DeviceDriver
from recoverhand_host.models import CommandAck, DeviceHealth, DeviceKind, GloveCommand
from recoverhand_host.runtime.clock import now_ns

# 固件支持的纯文本命令串（见 firmware/main/main.c 的 command() 分发）。
ACTION_BODIES = {
    "release": "release",
    "heartbeat": "heartbeat",
    "scan": "scan",
    "read": "read",
    "arm": "arm",
    "group_arm": "group_arm:POWER6V5A",
    "home": "home",
    "mark_open": "mark_open",
    "mark_close": "mark_close",
    "open": "open",
    "close": "close",
    "clear": "clear",
    "save_calibration": "save_calibration",
    "clear_all_calibration": "clear_all_calibration",
}

# 使固件进入 armed 状态的动作；成功后需要启动心跳租约。
_ARMING_BODIES = {"arm", "group_arm:POWER6V5A"}


def build_command_body(
    action: str,
    assist_level: float = 0.0,
    payload: dict[str, Any] | None = None,
) -> str:
    """把动作映射为固件 ``POST /api/command`` 的纯文本 body。"""
    payload = payload or {}
    if action in ACTION_BODIES:
        return ACTION_BODIES[action]
    if action == "group":
        percent = round(float(assist_level) * 100)
        percent = max(0, min(100, percent))
        return f"group:{percent}"
    if action == "jog":
        return f"jog{int(payload.get('delta', 0))}"
    if action == "select":
        return f"select:{int(payload.get('id', 1))}"
    if action == "setid":
        return f"setid:{int(payload['old'])}:{int(payload['new'])}:ONLYONE"
    raise ValueError(f"未知手套动作: {action}")


def interpret_ack(body: str, status: dict[str, Any]) -> tuple[bool, str | None]:
    """根据固件返回的状态 JSON 判断命令是否成功。

    固件失败路径统一调用 ``release_all(reason)``，会把 ``armed`` 置 false 并在
    ``message`` 里留下原因；运动类命令被拒绝时同样会释放。这里据此判定，
    而不是依赖中文文案匹配。
    """
    message = str(status.get("message", ""))

    def fail() -> tuple[bool, str | None]:
        return (False, message or "命令未确认")

    armed = status.get("armed") is True
    mode = status.get("mode")
    if body == "release":
        return (True, None) if status.get("all_released") is True else fail()
    if body == "arm":
        return (True, None) if (armed and mode == "single") else fail()
    if body == "group_arm:POWER6V5A":
        return (True, None) if (armed and mode == "group") else fail()
    if body.startswith("group:"):
        requested = int(body[len("group:"):])
        return (True, None) if (armed and status.get("group_requested") == requested) else fail()
    if body == "heartbeat":
        return (True, None)
    if body == "read":
        return (True, None) if int(status.get("online_count", 0)) > 0 else fail()
    if body.startswith("jog") or body in {"home", "open", "close"}:
        return (True, None) if armed else fail()
    # 管理类命令（scan/select/mark_*/clear/save_*/setid）按未报错处理，交后续核对。
    return (True, message or None)


class BenchHttpGloveDriver(DeviceDriver):
    """ESP32 SC09 台架固件的 HTTP 驱动，支持读取状态与下发动作命令。

    动作命令走 ``POST /api/command``（请求头 ``X-Hand-Control: 1``），响应即
    ``/api/status`` 同款 JSON。固件在 armed 状态下要求 ≤2 秒收到一次心跳，
    否则自行释放；本驱动在成功进入 armed 后自动启动心跳租约循环。
    """

    kind = DeviceKind.GLOVE

    def __init__(self, heartbeat_interval_s: float = 0.5) -> None:
        self._connected = False
        self._base_url = "http://192.168.4.1"
        self._timeout = 1.2
        self._last_status: dict[str, Any] | None = None
        self._last_error = "尚未连接"
        self._heartbeat_interval_s = heartbeat_interval_s
        self._lease_active = False
        self._heartbeat_task: asyncio.Task[None] | None = None

    async def discover(self, config: dict[str, Any]) -> list[dict[str, Any]]:
        base_url = str(config.get("base_url", self._base_url)).rstrip("/")
        return [{"id": base_url, "name": "配置的 ESP32 地址", "rssi": None}]

    def _read_status(self) -> dict[str, Any]:
        request = Request(f"{self._base_url}/api/status", method="GET")
        with urlopen(request, timeout=self._timeout) as response:
            return json.loads(response.read().decode("utf-8"))

    def _post(self, body: str) -> dict[str, Any]:
        request = Request(
            f"{self._base_url}/api/command",
            data=body.encode("utf-8"),
            method="POST",
            headers={"X-Hand-Control": "1"},
        )
        with urlopen(request, timeout=self._timeout) as response:
            return json.loads(response.read().decode("utf-8"))

    async def connect(self, config: dict[str, Any]) -> None:
        self._base_url = str(config.get("base_url", self._base_url)).rstrip("/")
        self._timeout = float(config.get("timeout_seconds", self._timeout))
        self._heartbeat_interval_s = float(
            config.get("heartbeat_interval_seconds", self._heartbeat_interval_s)
        )
        try:
            self._last_status = await asyncio.to_thread(self._read_status)
        except (OSError, URLError, ValueError, json.JSONDecodeError) as exc:
            self._last_error = f"状态检查失败: {exc}"
            raise RuntimeError(self._last_error) from exc
        self._connected = True
        self._last_error = "台架固件状态可读，可下发动作命令"

    async def disconnect(self) -> None:
        await self._stop_lease()
        self._connected = False

    async def health(self) -> DeviceHealth:
        if not self._connected:
            return DeviceHealth(reason=self._last_error)
        status = self._last_status or {}
        online = int(status.get("online_count", 0)) > 0
        return DeviceHealth(
            transport_ok=True,
            stream_ok=True,
            time_sync_ok=False,
            signal_ok=online,
            control_ready=True,
            reason="舵机在线，可下发动作" if online else "ESP32 可访问，但舵机未响应",
        )

    async def preview(self) -> dict[str, Any]:
        if not self._connected:
            raise RuntimeError("设备未连接")
        try:
            self._last_status = await asyncio.to_thread(self._read_status)
            self._last_error = "状态已刷新"
        except (OSError, URLError, ValueError, json.JSONDecodeError) as exc:
            self._last_error = f"状态刷新失败: {exc}"
            raise RuntimeError(self._last_error) from exc
        return self._status_to_preview(dict(self._last_status))

    @staticmethod
    def _status_to_preview(status: dict[str, Any]) -> dict[str, Any]:
        servos = status.get("servos") or []
        any_error = next(
            (servo.get("error") for servo in servos if int(servo.get("error", 0)) != 0),
            None,
        )
        return {
            "kind": DeviceKind.GLOVE.value,
            "connected": True,
            "armed": status.get("armed") is True,
            "released": status.get("all_released") is True,
            "position": None,
            "target": status.get("group_requested"),
            "pose": None,
            "tension": None,
            "motion_state": status.get("mode", "safe"),
            "fault_code": f"SERVO_ALARM_{any_error}" if any_error else None,
            "host_time": None,
            "device_time": None,
            "sequence": 0,
            "status": status,
            "notice": "台架状态；动作命令经 POST /api/command 下发",
        }

    async def command(self, command: GloveCommand) -> CommandAck:
        """下发一条动作命令，返回固件状态推导出的应答。"""
        if not self._connected:
            return CommandAck(
                command_id=command.command_id,
                ok=False,
                fault_code="设备未连接",
                ts_ns=now_ns(),
            )
        body = build_command_body(command.action, command.assist_level, command.payload)
        try:
            status = await asyncio.to_thread(self._post, body)
        except (OSError, URLError, ValueError, json.JSONDecodeError) as exc:
            self._last_error = f"命令发送失败: {exc}"
            return CommandAck(
                command_id=command.command_id,
                ok=False,
                fault_code=self._last_error,
                ts_ns=now_ns(),
            )
        self._last_status = status
        self._last_error = "状态已刷新"
        ok, fault = interpret_ack(body, status)
        await self._sync_lease(body, status)
        return CommandAck(
            command_id=command.command_id,
            ok=ok,
            fault_code=fault,
            echoed_state=status,
            ts_ns=now_ns(),
        )

    async def _sync_lease(self, body: str, status: dict[str, Any]) -> None:
        armed = status.get("armed") is True
        if armed and body in _ARMING_BODIES:
            self._start_lease()
        elif not armed:
            await self._stop_lease()

    def _start_lease(self) -> None:
        if self._lease_active and self._heartbeat_task is not None:
            return
        self._lease_active = True
        self._heartbeat_task = asyncio.create_task(self._heartbeat_loop())

    async def _stop_lease(self) -> None:
        self._lease_active = False
        task, self._heartbeat_task = self._heartbeat_task, None
        if task is not None:
            task.cancel()
            try:
                await task
            except asyncio.CancelledError:
                pass

    async def _heartbeat_loop(self) -> None:
        try:
            while self._lease_active and self._connected:
                try:
                    status = await asyncio.to_thread(self._post, "heartbeat")
                    self._last_status = status
                    if status.get("armed") is not True:
                        self._lease_active = False  # 固件已自行释放
                except (OSError, URLError, ValueError, json.JSONDecodeError):
                    pass  # 心跳失败不退出循环；固件超时后会自行释放。
                await asyncio.sleep(self._heartbeat_interval_s)
        finally:
            self._heartbeat_task = None
