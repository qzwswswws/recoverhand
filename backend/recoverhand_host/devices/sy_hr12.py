from __future__ import annotations

import asyncio
import logging
from collections.abc import Callable
from typing import Any

from recoverhand_host.devices.base import DeviceDriver
from recoverhand_host.devices.sy_hr12_protocol import (
    QUERY_STATE_FRAME,
    QUERY_VERSION_FRAME,
    DeviceState,
    ProtocolError,
    duration_frame,
    finger_frame,
    force_frame,
    mode_frame,
    normalize_fingers,
    normalize_mode,
    parse_state_snapshot,
    poweroff_frame,
    run_frame,
)
from recoverhand_host.models import CommandAck, DeviceHealth, DeviceKind, GloveCommand
from recoverhand_host.runtime.clock import now_ns

try:
    from bleak import BleakClient, BleakScanner
except ImportError:  # 可选依赖；未安装 BLE SDK 时主应用仍可启动。
    BleakClient = None  # type: ignore[assignment,misc]
    BleakScanner = None  # type: ignore[assignment,misc]

LOGGER = logging.getLogger(__name__)

DEFAULT_NAME = "SY-HR12-15"
DEFAULT_ADDRESS = "00:FB:18:00:64:0B"
AE30_SERVICE_UUID = "0000ae30-0000-1000-8000-00805f9b34fb"
AE01_WRITE_UUID = "0000ae01-0000-1000-8000-00805f9b34fb"
AE02_NOTIFY_UUID = "0000ae02-0000-1000-8000-00805f9b34fb"


class SyHr12GloveDriver(DeviceDriver):
    """SY-HR12 蓝牙康复手套驱动（杰理 V1.0.5，AE30 控制通道）。

    协议见 ``sy_hr12_protocol``；动作命令经 ``command()`` 以 ``GloveCommand``
    的 ``action`` + ``payload`` 下发。设备安全约束：机制未卸载时禁止发送运动命令。
    """

    kind = DeviceKind.GLOVE

    def __init__(
        self,
        scanner: Any | None = None,
        client_factory: Callable[..., Any] | None = None,
    ) -> None:
        self._scanner = scanner or BleakScanner
        self._client_factory = client_factory or BleakClient
        self._client: Any | None = None
        self._write_char: Any | None = None
        self._notify_char: Any | None = None
        self._connected = False
        self._config: dict[str, Any] = {}
        self._state = DeviceState()
        self._firmware: str | None = None
        self._last_error = "尚未连接"
        self._write_lock = asyncio.Lock()
        self._poll_task: asyncio.Task[None] | None = None
        self._write_delay_seconds = 0.05

    def _require_bleak(self) -> None:
        if self._scanner is None or self._client_factory is None:
            raise RuntimeError(
                "未安装 BLE 依赖；请在 host_app 目录执行 "
                ".\\\\.venv\\\\Scripts\\\\python.exe -m pip install -e \".[emg]\""
            )

    async def discover(self, config: dict[str, Any]) -> list[dict[str, Any]]:
        self._require_bleak()
        name = str(config.get("device_name", DEFAULT_NAME))
        address = str(config.get("device_address", DEFAULT_ADDRESS)).upper()
        timeout = float(config.get("scan_timeout_seconds", 6.0))
        try:
            devices = await self._scanner.discover(timeout=timeout, return_adv=True)
        except OSError as exc:
            raise RuntimeError(f"蓝牙扫描失败：{exc}") from exc
        result = []
        for device, advertisement in (devices or {}).values():
            local_name = advertisement.local_name or device.name or ""
            if local_name == name or device.address.upper() == address:
                result.append(
                    {"id": device.address, "name": local_name, "rssi": advertisement.rssi}
                )
        return result

    async def connect(self, config: dict[str, Any]) -> None:
        self._require_bleak()
        self._config = dict(config)
        name = str(config.get("device_name", DEFAULT_NAME))
        address = str(config.get("device_address", DEFAULT_ADDRESS))
        timeout = float(config.get("connect_timeout_seconds", 12.0))
        self._write_delay_seconds = float(config.get("write_delay_seconds", 0.05))

        device = await self._scanner.find_device_by_address(address, timeout=timeout)
        if device is None:
            device = await self._scanner.find_device_by_name(name, timeout=timeout)
        if device is None:
            message = f"未发现 {name}（{address}）；请确认设备已开机且手机已断开"
            self._last_error = message
            raise RuntimeError(message)

        client = self._client_factory(device, disconnected_callback=self._on_disconnect)
        try:
            await client.connect(timeout=timeout)
            service = client.services.get_service(AE30_SERVICE_UUID)
            if service is None:
                raise RuntimeError("设备缺少控制服务 AE30")
            self._write_char = next(
                (item for item in service.characteristics if item.uuid.lower() == AE01_WRITE_UUID),
                None,
            )
            self._notify_char = next(
                (item for item in service.characteristics if item.uuid.lower() == AE02_NOTIFY_UUID),
                None,
            )
            if self._write_char is None or self._notify_char is None:
                raise RuntimeError("AE30 服务缺少控制特征 AE01/AE02")
            await client.start_notify(self._notify_char, self._on_notification)
        except Exception as exc:
            try:
                await client.disconnect()
            except Exception:  # noqa: BLE001, S110 - 断开清理失败不影响主错误
                pass
            self._last_error = str(exc)
            raise
        self._client = client
        self._connected = True
        self._last_error = "已连接，等待状态同步"
        await self._send(QUERY_VERSION_FRAME)
        await self._send(QUERY_STATE_FRAME)

    async def start_stream(self) -> None:
        if self._firmware is None and self._connected:
            # 首次版本查询可能因 notify 订阅刚建立而丢失，流启动时补查一次。
            try:
                await self._send(QUERY_VERSION_FRAME)
            except Exception:  # noqa: BLE001, S110 - 版本查询失败不影响状态流
                pass
        if self._poll_task is None and self._connected:
            self._poll_task = asyncio.create_task(self._poll_state(), name="sy-hr12-poll")

    async def stop_stream(self) -> None:
        task, self._poll_task = self._poll_task, None
        if task is not None:
            task.cancel()
            try:
                await task
            except asyncio.CancelledError:
                pass

    async def disconnect(self) -> None:
        await self.stop_stream()
        client, self._client = self._client, None
        self._write_char = None
        self._notify_char = None
        self._connected = False
        if client is not None and getattr(client, "is_connected", False):
            try:
                await client.disconnect()
            except Exception as exc:  # noqa: BLE001 - 断开失败已记录日志
                LOGGER.debug("断开失败：%s", exc)

    def _on_disconnect(self, _client: Any) -> None:
        self._connected = False

    def _on_notification(self, _sender: Any, data: bytearray) -> None:
        frame = bytes(data)
        if len(frame) == 53 and frame[:5] == bytes.fromhex("A5 5A 01 35 03"):
            try:
                self._state = parse_state_snapshot(frame)
            except ProtocolError as exc:
                LOGGER.warning("状态快照解析失败：%s", exc)
            return
        if len(frame) >= 7 and frame[:5] == bytes.fromhex("A5 5A 01") + bytes((len(frame), 0)):
            try:
                self._firmware = frame[5:-1].decode("ascii")
            except UnicodeDecodeError:
                return

    async def _poll_state(self) -> None:
        poll_interval = float(self._config.get("poll_interval_seconds", 0.75))
        try:
            while self._connected:
                await self._send(QUERY_STATE_FRAME)
                await asyncio.sleep(poll_interval)
        except asyncio.CancelledError:
            raise
        except Exception as exc:  # noqa: BLE001 - 轮询失败记录到 last_error
            self._last_error = f"状态轮询停止：{exc}"

    async def _send(self, frame: bytes) -> None:
        if not self._connected or self._client is None or self._write_char is None:
            raise RuntimeError("设备尚未连接")
        async with self._write_lock:
            await self._client.write_gatt_char(self._write_char, frame, response=False)

    async def health(self) -> DeviceHealth:
        if not self._connected:
            return DeviceHealth(reason=self._last_error)
        synced = self._state.powered is not None or self._firmware is not None
        return DeviceHealth(
            transport_ok=True,
            stream_ok=True,
            time_sync_ok=False,
            signal_ok=synced,
            control_ready=True,
            reason=(
                "设备已连接，状态已同步，可下发动作" if synced
                else "设备已连接，正在读取状态（约 1 秒内同步）"
            ),
        )

    async def preview(self) -> dict[str, Any]:
        if not self._connected:
            raise RuntimeError("设备尚未连接")
        state = self._state.to_dict()
        state.update(
            {
                "kind": self.kind.value,
                "firmware": self._firmware,
                "device_name": str(self._config.get("device_name", DEFAULT_NAME)),
                "notice": "SY-HR12 蓝牙手套；机制未卸载时禁止发送运动命令",
            }
        )
        return state

    async def command(self, command: GloveCommand) -> CommandAck:
        if not self._connected:
            return CommandAck(
                command_id=command.command_id, ok=False, fault_code="设备尚未连接", ts_ns=now_ns()
            )
        try:
            frame = self._frame_for(command)
            await self._send(frame)
        except (ProtocolError, ValueError, RuntimeError) as exc:
            return CommandAck(
                command_id=command.command_id, ok=False, fault_code=str(exc), ts_ns=now_ns()
            )
        await asyncio.sleep(self._write_delay_seconds)  # 连发多条命令时给设备留出处理间隔
        return CommandAck(
            command_id=command.command_id,
            ok=True,
            echoed_state=self._state.to_dict(),
            ts_ns=now_ns(),
        )

    @staticmethod
    def _frame_for(command: GloveCommand) -> bytes:
        action = command.action
        payload = dict(command.payload or {})
        if action == "mode":
            return mode_frame(normalize_mode(payload["mode"]))
        if action == "fingers":
            return finger_frame(normalize_fingers(payload.get("selected", payload.get("fingers", ()))))
        if action == "durations":
            return duration_frame(payload["flexion"], payload["extension"])
        if action == "forces":
            return force_frame(payload["flexion"], payload["extension"])
        if action == "start":
            if payload.get("confirm") is not True:
                raise ProtocolError("start 需要 confirm=true")
            return run_frame(True)
        if action == "pause":
            return run_frame(False)
        if action == "poweroff":
            if payload.get("confirm") is not True:
                raise ProtocolError("poweroff 需要 confirm=true")
            return poweroff_frame()
        if action == "query":
            return QUERY_STATE_FRAME
        raise ProtocolError(f"未知手套动作: {action}")
