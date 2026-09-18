from __future__ import annotations

from abc import ABC, abstractmethod
from typing import Any, Protocol, runtime_checkable

from recoverhand_host.models import CommandAck, DeviceHealth, DeviceKind, GloveCommand


class DeviceDriver(ABC):
    """所有真实设备、回放设备和模拟设备共用的最小生命周期。"""

    kind: DeviceKind

    @abstractmethod
    async def discover(self, config: dict[str, Any]) -> list[dict[str, Any]]:
        raise NotImplementedError

    @abstractmethod
    async def connect(self, config: dict[str, Any]) -> None:
        raise NotImplementedError

    @abstractmethod
    async def disconnect(self) -> None:
        raise NotImplementedError

    @abstractmethod
    async def health(self) -> DeviceHealth:
        raise NotImplementedError

    async def start_stream(self) -> None:
        return None

    async def stop_stream(self) -> None:
        return None

    @abstractmethod
    async def preview(self) -> dict[str, Any]:
        raise NotImplementedError


@runtime_checkable
class ControlDriver(Protocol):
    """可下发动作命令的设备协议；当前只有手套类驱动实现，EEG/EMG 不实现。"""

    async def command(self, command: GloveCommand) -> CommandAck:
        ...
