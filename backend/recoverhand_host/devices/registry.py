from __future__ import annotations

from collections.abc import Callable

from recoverhand_host.devices.base import DeviceDriver
from recoverhand_host.models import DeviceKind, DriverInfo

DriverFactory = Callable[[], DeviceDriver]


class DriverRegistry:
    def __init__(self) -> None:
        self._info: dict[str, DriverInfo] = {}
        self._factories: dict[str, DriverFactory] = {}

    def register(self, info: DriverInfo, factory: DriverFactory | None = None) -> None:
        if info.id in self._info:
            raise ValueError(f"驱动已注册: {info.id}")
        if info.available and factory is None:
            raise ValueError(f"可用驱动缺少工厂: {info.id}")
        self._info[info.id] = info
        if factory is not None:
            self._factories[info.id] = factory

    def list(self, kind: DeviceKind | None = None) -> list[DriverInfo]:
        infos = self._info.values()
        if kind is not None:
            infos = (info for info in infos if info.kind == kind)
        return list(infos)

    def info(self, driver_id: str) -> DriverInfo:
        try:
            return self._info[driver_id]
        except KeyError as exc:
            raise ValueError(f"未知驱动: {driver_id}") from exc

    def create(self, driver_id: str) -> DeviceDriver:
        info = self.info(driver_id)
        if not info.available:
            reason = info.unavailable_reason or "驱动尚未实现"
            raise ValueError(f"{info.display_name}不可用: {reason}")
        return self._factories[driver_id]()
