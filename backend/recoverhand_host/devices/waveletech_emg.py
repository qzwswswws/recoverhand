from __future__ import annotations

import asyncio
import logging
import math
import struct
import time
from collections import deque
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from recoverhand_host.devices.base import DeviceDriver
from recoverhand_host.models import DeviceHealth, DeviceKind

try:
    from bleak import BleakClient, BleakScanner
except ImportError:  # 可选依赖；模拟模式不能因为未安装 BLE SDK 而无法启动。
    BleakClient = None  # type: ignore[assignment,misc]
    BleakScanner = None  # type: ignore[assignment,misc]


SERVICE_UUID = "974cbe30-3e83-465e-acde-6f92fe712134"
NOTIFY_UUID = "974cbe31-3e83-465e-acde-6f92fe712134"

# 说明书截图中可见、但正文与厂家 APK 均未明确声明。当前只探测，不写入。
UNVERIFIED_TIME_WRITE_UUID = "974cbe32-3e83-465e-acde-6f92fe712134"

KNOWN_NAME_PREFIXES = ("EMGR-", "EMGG-", "EMGB-", "EMGY-")
SAMPLE_RATE_HZ = 250.0
SAMPLES_PER_PACKET = 6
SAMPLE_INTERVAL_SECONDS = 1.0 / SAMPLE_RATE_HZ
LOGGER = logging.getLogger(__name__)


class EmgProtocolError(ValueError):
    """设备通知包不符合已知协议。"""


@dataclass(frozen=True, slots=True)
class EmgDataPacket:
    sequence: int
    samples_uv: tuple[float, ...]


@dataclass(frozen=True, slots=True)
class EmgStatusPacket:
    sequence: int
    battery_percent: int
    mac: str
    battery_voltage_mv: int
    temperature_c: float
    timestamp_low32_ms: int


@dataclass(frozen=True, slots=True)
class EmgTimePacket:
    timestamp_ms: int


ParsedPacket = EmgDataPacket | EmgStatusPacket | EmgTimePacket


@dataclass(frozen=True, slots=True)
class _RawNotification:
    payload: bytes
    host_time: float
    monotonic_time: float


def _format_mac(payload: bytes) -> str:
    return ":".join(f"{value:02X}" for value in payload)


def parse_notification(payload: bytes | bytearray | memoryview) -> ParsedPacket:
    """解析唯理肌电贴的固定 20 字节通知包。"""

    data = bytes(payload)
    if len(data) != 20:
        raise EmgProtocolError(f"通知长度应为 20 字节，实际为 {len(data)} 字节")

    if data.startswith(b"TIME"):
        try:
            timestamp_ms = int(data[4:].decode("ascii"), 16)
        except (UnicodeDecodeError, ValueError) as exc:
            raise EmgProtocolError("TIME 响应不是 16 位十六进制时间戳") from exc
        return EmgTimePacket(timestamp_ms=timestamp_ms)

    packet_type = data[0]
    sequence = data[1]
    if packet_type == 0xD3:
        samples = tuple(
            int.from_bytes(data[offset : offset + 3], byteorder="big", signed=True) / 60.0
            for offset in range(2, 20, 3)
        )
        if len(samples) != SAMPLES_PER_PACKET:
            raise EmgProtocolError("肌电包未包含 6 个采样点")
        return EmgDataPacket(sequence=sequence, samples_uv=samples)

    if packet_type == 0xC0:
        battery_percent = data[2]
        if battery_percent > 100:
            raise EmgProtocolError(f"电量百分比超出范围: {battery_percent}")
        return EmgStatusPacket(
            sequence=sequence,
            battery_percent=battery_percent,
            mac=_format_mac(data[3:9]),
            # 说明书把电压写作有符号 16 位；物理量不应为负，第一版按无符号解析并保留原始包。
            battery_voltage_mv=int.from_bytes(data[9:11], byteorder="big", signed=False),
            temperature_c=int.from_bytes(data[11:13], byteorder="big", signed=True) / 10.0,
            timestamp_low32_ms=int.from_bytes(data[16:20], byteorder="big", signed=False),
        )

    raise EmgProtocolError(f"未知通知包类型: 0x{packet_type:02X}")


class WaveletechEmgDriver(DeviceDriver):
    """唯理科技单通道双电极肌电贴的只读 BLE 采集驱动。"""

    kind = DeviceKind.EMG

    def __init__(
        self,
        scanner: Any | None = None,
        client_factory: Callable[..., Any] | None = None,
    ) -> None:
        self._scanner = scanner or BleakScanner
        self._client_factory = client_factory or BleakClient
        self._client: Any | None = None
        self._device: Any | None = None
        self._devices_by_id: dict[str, Any] = {}
        self._config: dict[str, Any] = {}
        self._streaming = False
        self._disconnected = False
        self._notification_queue: asyncio.Queue[_RawNotification] = asyncio.Queue(maxsize=256)
        self._consumer_task: asyncio.Task[None] | None = None
        self._first_emg = asyncio.Event()
        self._samples: deque[tuple[float, float]] = deque(maxlen=1_000)
        self._status: EmgStatusPacket | None = None
        self._last_packet_monotonic: float | None = None
        self._last_emg_monotonic: float | None = None
        self._last_host_time: float | None = None
        self._last_emg_sequence = 0
        self._last_global_sequence: int | None = None
        self._received_sequence_packets = 0
        self._missing_sequence_packets = 0
        self._duplicate_sequence_packets = 0
        self._out_of_order_packets = 0
        self._invalid_packets = 0
        self._queue_drops = 0
        self._time_write_characteristic_present = False
        self._raw_file: Any = None

    def _require_bleak(self) -> None:
        if self._scanner is None or self._client_factory is None:
            raise RuntimeError(
                '尚未安装 BLE 依赖；请在 host_app 目录执行 .\\.venv\\Scripts\\python.exe -m pip install -e ".[emg]"'
            )

    @staticmethod
    def _name_matches(name: str, name_filter: str) -> bool:
        normalized = name.upper()
        if name_filter and name_filter.upper() not in normalized:
            return False
        return normalized.startswith(KNOWN_NAME_PREFIXES)

    async def _scan(self, config: dict[str, Any]) -> list[tuple[Any, Any]]:
        self._require_bleak()
        timeout = float(config.get("scan_timeout_seconds", 5.0))
        try:
            discovered = await self._scanner.discover(timeout=timeout, return_adv=True)
        except OSError as exc:
            error_code = getattr(exc, "winerror", None) or getattr(exc, "errno", None)
            raise RuntimeError(
                f"Windows 蓝牙扫描失败（错误码 {error_code}）；请确认蓝牙已开启、适配器支持 BLE，且未被系统禁用"
            ) from exc
        if isinstance(discovered, dict):
            return list(discovered.values())
        return [(device, None) for device in discovered]

    async def discover(self, config: dict[str, Any]) -> list[dict[str, Any]]:
        name_filter = str(config.get("device_name_filter", "")).strip()
        identifier = str(config.get("device_identifier") or config.get("mac_address") or "").strip()
        candidates: list[dict[str, Any]] = []
        self._devices_by_id.clear()
        for device, advertisement in await self._scan(config):
            name = str(getattr(advertisement, "local_name", None) or getattr(device, "name", None) or "")
            address = str(getattr(device, "address", ""))
            if identifier and address.casefold() != identifier.casefold():
                continue
            if not self._name_matches(name, name_filter):
                continue
            self._devices_by_id[address] = device
            manufacturer_data = getattr(advertisement, "manufacturer_data", {}) or {}
            candidates.append(
                {
                    "id": address,
                    "name": name,
                    "rssi": getattr(advertisement, "rssi", None),
                    "manufacturer_data": {
                        str(company_id): bytes(value).hex().upper()
                        for company_id, value in manufacturer_data.items()
                    },
                }
            )
        return candidates

    async def connect(self, config: dict[str, Any]) -> None:
        self._require_bleak()
        if self._client is not None:
            await self.disconnect()
        self._config = dict(config)
        candidates = await self.discover(config)
        if not candidates:
            target = str(config.get("device_identifier") or config.get("mac_address") or "").strip()
            detail = f"（标识 {target}）" if target else ""
            raise RuntimeError(f"未发现名称为 EMGR/EMGG/EMGB/EMGY 的唯理肌电贴{detail}")
        if len(candidates) > 1:
            identifiers = "、".join(candidate["id"] for candidate in candidates)
            raise RuntimeError(f"发现多个唯理肌电贴（{identifiers}）；请在连接档案填写目标设备标识后重试")
        self._device = self._devices_by_id[candidates[0]["id"]]

        connect_timeout = float(config.get("connect_timeout_seconds", 10.0))
        self._client = self._client_factory(
            self._device,
            disconnected_callback=self._on_disconnected,
            timeout=connect_timeout,
        )
        try:
            await self._client.connect()
            service = self._client.services.get_service(SERVICE_UUID)
            if service is None:
                raise RuntimeError(f"设备缺少目标 GATT 服务 {SERVICE_UUID}")
            if service.get_characteristic(NOTIFY_UUID) is None:
                raise RuntimeError(f"设备缺少肌电通知特征 {NOTIFY_UUID}")
            candidate = self._client.services.get_characteristic(UNVERIFIED_TIME_WRITE_UUID)
            self._time_write_characteristic_present = candidate is not None
            self._disconnected = False
        except Exception:
            await self._safe_disconnect_client()
            raise

    async def disconnect(self) -> None:
        await self.stop_stream()
        self.stop_raw_recording()
        await self._safe_disconnect_client()
        self._device = None
        self._devices_by_id.clear()
        self._disconnected = False

    async def _safe_disconnect_client(self) -> None:
        client, self._client = self._client, None
        if client is not None and getattr(client, "is_connected", False):
            await client.disconnect()

    def _on_disconnected(self, _client: Any) -> None:
        self._disconnected = True
        self._streaming = False

    def _reset_stream_state(self) -> None:
        self._samples.clear()
        self._status = None
        self._last_packet_monotonic = None
        self._last_emg_monotonic = None
        self._last_host_time = None
        self._last_emg_sequence = 0
        self._last_global_sequence = None
        self._received_sequence_packets = 0
        self._missing_sequence_packets = 0
        self._duplicate_sequence_packets = 0
        self._out_of_order_packets = 0
        self._invalid_packets = 0
        self._queue_drops = 0
        self._first_emg = asyncio.Event()
        while not self._notification_queue.empty():
            try:
                self._notification_queue.get_nowait()
            except asyncio.QueueEmpty:
                break

    async def start_stream(self) -> None:
        if self._client is None or not getattr(self._client, "is_connected", False):
            raise RuntimeError("肌电贴尚未连接")
        if self._streaming:
            return
        self._reset_stream_state()
        self._consumer_task = asyncio.create_task(self._consume_notifications())
        try:
            await self._client.start_notify(NOTIFY_UUID, self._handle_notification)
            self._streaming = True
            timeout = float(self._config.get("stream_start_timeout_seconds", 3.0))
            await asyncio.wait_for(self._first_emg.wait(), timeout=timeout)
        except TimeoutError as exc:
            await self.stop_stream()
            raise RuntimeError("已连接肌电贴，但在等待时间内没有收到 0xD3 肌电数据") from exc
        except Exception:
            await self.stop_stream()
            raise

    async def stop_stream(self) -> None:
        client = self._client
        if self._streaming and client is not None and getattr(client, "is_connected", False):
            try:
                await client.stop_notify(NOTIFY_UUID)
            except Exception as exc:
                LOGGER.debug("取消肌电通知失败，继续清理本地流状态", exc_info=exc)
        self._streaming = False
        task, self._consumer_task = self._consumer_task, None
        if task is not None:
            task.cancel()
            try:
                await task
            except asyncio.CancelledError:
                pass

    def start_raw_recording(self, path: Path) -> None:
        """开始把原始样本写入文件（float32 小端，µV，250 Hz 连续流）。"""
        if self._raw_file is not None:
            raise RuntimeError("原始记录已在进行")
        self._raw_file = Path(path).open("wb")  # noqa: SIM115 - 句柄跨流式采集保持打开，stop_raw_recording 关闭

    def stop_raw_recording(self) -> None:
        if self._raw_file is not None:
            self._raw_file.close()
            self._raw_file = None

    def _handle_notification(self, _sender: Any, data: bytearray) -> None:
        notification = _RawNotification(
            payload=bytes(data),
            host_time=time.time(),
            monotonic_time=time.monotonic(),
        )
        if self._notification_queue.full():
            try:
                self._notification_queue.get_nowait()
                self._queue_drops += 1
            except asyncio.QueueEmpty:
                pass
        self._notification_queue.put_nowait(notification)

    async def _consume_notifications(self) -> None:
        while True:
            notification = await self._notification_queue.get()
            try:
                packet = parse_notification(notification.payload)
            except EmgProtocolError:
                self._invalid_packets += 1
                continue
            self._last_packet_monotonic = notification.monotonic_time
            self._last_host_time = notification.host_time
            if isinstance(packet, EmgTimePacket):
                continue
            self._track_sequence(packet.sequence)
            if isinstance(packet, EmgStatusPacket):
                self._status = packet
                continue
            self._last_emg_monotonic = notification.monotonic_time
            self._last_emg_sequence = packet.sequence
            first_sample_time = notification.host_time - ((SAMPLES_PER_PACKET - 1) * SAMPLE_INTERVAL_SECONDS)
            for index, sample_uv in enumerate(packet.samples_uv):
                self._samples.append((first_sample_time + index * SAMPLE_INTERVAL_SECONDS, sample_uv))
                if self._raw_file is not None:
                    self._raw_file.write(struct.pack("<f", sample_uv))
            self._first_emg.set()

    def _track_sequence(self, sequence: int) -> None:
        previous = self._last_global_sequence
        self._last_global_sequence = sequence
        self._received_sequence_packets += 1
        if previous is None:
            return
        delta = (sequence - previous) & 0xFF
        if delta == 0:
            self._duplicate_sequence_packets += 1
        elif 1 < delta <= 127:
            self._missing_sequence_packets += delta - 1
        elif delta > 127:
            self._out_of_order_packets += 1

    def _packet_loss(self) -> float:
        total = self._received_sequence_packets + self._missing_sequence_packets
        if total == 0:
            return 0.0
        return self._missing_sequence_packets / total

    def _signal_quality(self) -> float:
        if not self._samples:
            return 0.0
        recent = [value for _, value in list(self._samples)[-250:]]
        if not all(math.isfinite(value) for value in recent):
            return 0.0
        transport_quality = max(0.0, 1.0 - self._packet_loss())
        invalid_penalty = min(0.5, (self._invalid_packets + self._queue_drops) * 0.02)
        return max(0.0, transport_quality - invalid_penalty)

    async def health(self) -> DeviceHealth:
        connected = bool(
            self._client is not None
            and getattr(self._client, "is_connected", False)
            and not self._disconnected
        )
        age = (
            time.monotonic() - self._last_emg_monotonic
            if self._last_emg_monotonic is not None
            else math.inf
        )
        stream_ok = connected and self._streaming and age <= 1.0
        signal_ok = stream_ok and bool(self._samples) and self._signal_quality() > 0.0
        if not connected:
            reason = "肌电贴未连接或连接已断开"
        elif not stream_ok:
            reason = "BLE 已连接，但肌电通知流中断"
        elif not signal_ok:
            reason = "收到通知，但数据格式或连续性异常"
        else:
            battery = f"，电量 {self._status.battery_percent}%" if self._status else ""
            reason = f"肌电数据流有效{battery}；电极接触质量尚未验证"
        return DeviceHealth(
            transport_ok=connected,
            stream_ok=stream_ok,
            time_sync_ok=False,
            signal_ok=signal_ok,
            control_ready=False,
            reason=reason,
        )

    async def preview(self) -> dict[str, Any]:
        if self._client is None or not getattr(self._client, "is_connected", False):
            raise RuntimeError("肌电贴尚未连接")
        points = int(SAMPLE_RATE_HZ * float(self._config.get("preview_seconds", 1.0)))
        points = max(25, min(points, self._samples.maxlen or 1_000))
        recent = list(self._samples)[-points:]
        status = self._status
        return {
            "kind": self.kind.value,
            "sample_rate": SAMPLE_RATE_HZ,
            "channel_names": ["腕部双电极差分通道"],
            "samples": [[value for _, value in recent]],
            "sample_times": [sample_time for sample_time, _ in recent],
            "unit": "µV",
            "host_time": self._last_host_time or time.time(),
            "device_time": None,
            "sequence": self._last_emg_sequence,
            "packet_loss": self._packet_loss(),
            "signal_quality": self._signal_quality(),
            "battery_percent": status.battery_percent if status else None,
            "battery_voltage_mv": status.battery_voltage_mv if status else None,
            "temperature_c": status.temperature_c if status else None,
            "device_mac": status.mac if status else None,
            "device_timestamp_low32_ms": status.timestamp_low32_ms if status else None,
            "time_sync": "未校准",
            "time_write_characteristic_detected": self._time_write_characteristic_present,
            "diagnostics": {
                "received_sequence_packets": self._received_sequence_packets,
                "missing_sequence_packets": self._missing_sequence_packets,
                "duplicate_sequence_packets": self._duplicate_sequence_packets,
                "out_of_order_packets": self._out_of_order_packets,
                "invalid_packets": self._invalid_packets,
                "queue_drops": self._queue_drops,
            },
            "notice": "原始单通道 sEMG；当前质量分数只反映传输连续性，不代表电极接触或临床有效性",
        }
