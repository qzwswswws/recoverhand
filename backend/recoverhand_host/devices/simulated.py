from __future__ import annotations

import math
import random
import time
from typing import Any

from recoverhand_host.devices.base import DeviceDriver
from recoverhand_host.models import CommandAck, DeviceHealth, DeviceKind, GloveCommand
from recoverhand_host.runtime.clock import now_ns


class _SyntheticSignalDriver(DeviceDriver):
    def __init__(self, kind: DeviceKind) -> None:
        self.kind = kind
        self._connected = False
        self._config: dict[str, Any] = {}
        self._sequence = 0

    async def discover(self, config: dict[str, Any]) -> list[dict[str, Any]]:
        return [{"id": f"synthetic-{self.kind.value}-01", "name": "本机模拟设备", "rssi": None}]

    async def connect(self, config: dict[str, Any]) -> None:
        self._config = dict(config)
        self._connected = True

    async def disconnect(self) -> None:
        self._connected = False

    async def health(self) -> DeviceHealth:
        if not self._connected:
            return DeviceHealth(reason="模拟设备未连接")
        return DeviceHealth(
            transport_ok=True,
            stream_ok=True,
            time_sync_ok=True,
            signal_ok=True,
            control_ready=self.kind == DeviceKind.GLOVE,
            reason="模拟数据有效",
        )

    def _require_connected(self) -> None:
        if not self._connected:
            raise RuntimeError("设备未连接")


class SyntheticEegDriver(_SyntheticSignalDriver):
    def __init__(self) -> None:
        super().__init__(DeviceKind.EEG)

    async def preview(self) -> dict[str, Any]:
        self._require_connected()
        sample_rate = int(self._config.get("sample_rate", 250))
        channel_names = self._config.get("channel_names", "C3,Cz,C4").split(",")
        channel_names = [name.strip() for name in channel_names if name.strip()]
        points = min(sample_rate, 250)
        self._sequence += 1
        samples = []
        for channel_index, _ in enumerate(channel_names):
            phase = channel_index * 0.7
            samples.append([
                round(18 * math.sin(2 * math.pi * 10 * i / sample_rate + phase) + random.gauss(0, 3), 3)
                for i in range(points)
            ])
        return {
            "kind": self.kind.value,
            "sample_rate": sample_rate,
            "channel_names": channel_names,
            "samples": samples,
            "host_time": time.time(),
            "device_time": time.time(),
            "sequence": self._sequence,
            "quality": {name: 0.95 for name in channel_names},
            "notice": "模拟 EEG，仅用于联调，不代表人体信号",
        }


class SyntheticEmgDriver(_SyntheticSignalDriver):
    def __init__(self) -> None:
        super().__init__(DeviceKind.EMG)

    async def preview(self) -> dict[str, Any]:
        self._require_connected()
        sample_rate = int(self._config.get("sample_rate", 500))
        points = min(sample_rate, 300)
        active = bool(self._config.get("simulate_burst", True))
        self._sequence += 1
        samples = []
        for i in range(points):
            envelope = 1.0
            if active and points * 0.35 < i < points * 0.7:
                envelope = 5.5
            samples.append(round(envelope * random.gauss(0, 0.018), 5))
        return {
            "kind": self.kind.value,
            "sample_rate": sample_rate,
            "channel_names": ["腕部附近双电极差分通道"],
            "samples": [samples],
            "host_time": time.time(),
            "device_time": time.time(),
            "sequence": self._sequence,
            "packet_loss": 0.0,
            "signal_quality": 0.94,
            "notice": "模拟单通道 sEMG，仅用于联调",
        }


class SimulatedGloveDriver(_SyntheticSignalDriver):
    def __init__(self) -> None:
        super().__init__(DeviceKind.GLOVE)
        self._position = 512

    async def command(self, command: GloveCommand) -> CommandAck:
        self._require_connected()
        if command.action == "group":
            self._position = int(max(0.0, min(1.0, command.assist_level)) * 1023)
        return CommandAck(
            command_id=command.command_id,
            ok=True,
            echoed_state={"position": self._position},
            ts_ns=now_ns(),
        )

    async def preview(self) -> dict[str, Any]:
        self._require_connected()
        self._sequence += 1
        return {
            "kind": self.kind.value,
            "connected": True,
            "armed": False,
            "released": True,
            "position": self._position,
            "target": self._position,
            "pose": {
                "actual_flexion": [0.0, 0.0, 0.0, 0.0, 0.0],
                "target_flexion": [0.0, 0.0, 0.0, 0.0, 0.0],
                "side": None,
                "mapping": "模拟五指屈曲量；不是手指角度测量",
            },
            "tension": None,
            "motion_state": "idle",
            "fault_code": None,
            "host_time": time.time(),
            "device_time": None,
            "sequence": self._sequence,
            "notice": "只读连接预览；本页不提供运动指令",
        }
