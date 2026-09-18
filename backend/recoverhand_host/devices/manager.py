from __future__ import annotations

import asyncio
from typing import Any

from recoverhand_host.devices.base import ControlDriver, DeviceDriver
from recoverhand_host.devices.registry import DriverRegistry
from recoverhand_host.models import (
    CommandAck,
    ConnectionState,
    DeviceHealth,
    DeviceKind,
    DeviceSlot,
    GloveCommand,
)


class DeviceManager:
    def __init__(self, registry: DriverRegistry) -> None:
        self.registry = registry
        self._slots = {kind: DeviceSlot(kind=kind) for kind in DeviceKind}
        self._drivers: dict[DeviceKind, DeviceDriver] = {}
        self._settings_locked = False
        self._lock = asyncio.Lock()
        self._subscribers: set[asyncio.Queue[dict[str, Any]]] = set()

    @property
    def settings_locked(self) -> bool:
        return self._settings_locked

    def snapshot(self) -> dict[str, Any]:
        return {
            "settings_locked": self._settings_locked,
            "devices": {kind.value: slot.to_dict() for kind, slot in self._slots.items()},
        }

    def subscribe(self) -> asyncio.Queue[dict[str, Any]]:
        queue: asyncio.Queue[dict[str, Any]] = asyncio.Queue(maxsize=8)
        self._subscribers.add(queue)
        return queue

    def unsubscribe(self, queue: asyncio.Queue[dict[str, Any]]) -> None:
        self._subscribers.discard(queue)

    def _publish(self) -> None:
        snapshot = self.snapshot()
        for queue in tuple(self._subscribers):
            if queue.full():
                try:
                    queue.get_nowait()
                except asyncio.QueueEmpty:
                    pass
            queue.put_nowait(snapshot)

    def set_settings_locked(self, locked: bool) -> dict[str, Any]:
        self._settings_locked = locked
        self._publish()
        return self.snapshot()

    def _assert_editable(self) -> None:
        if self._settings_locked:
            raise ValueError("标定或训练进行中，连接设置已锁定；请结束当前会话后修改")

    @staticmethod
    def _validate_schema(config: dict[str, Any], schema: dict[str, Any]) -> None:
        missing = [key for key in schema.get("required", []) if config.get(key) in (None, "")]
        if missing:
            raise ValueError(f"缺少必填配置: {', '.join(missing)}")
        properties = schema.get("properties", {})
        for key, value in config.items():
            expected = properties.get(key, {}).get("type")
            if expected == "number" and not isinstance(value, (int, float)):
                raise ValueError(f"配置 {key} 应为数字")
            if expected == "integer" and not isinstance(value, int):
                raise ValueError(f"配置 {key} 应为整数")
            if expected == "boolean" and not isinstance(value, bool):
                raise ValueError(f"配置 {key} 应为布尔值")

    def validate_profile(self, devices: dict[str, Any]) -> dict[str, Any]:
        errors: dict[str, list[str]] = {}
        for kind in DeviceKind:
            entry = devices.get(kind.value)
            if not entry:
                errors.setdefault(kind.value, []).append("未选择驱动")
                continue
            try:
                info = self.registry.info(str(entry.get("driver_id", "")))
                if info.kind != kind:
                    raise ValueError("驱动类型与设备位置不匹配")
                self._validate_schema(dict(entry.get("config", {})), info.config_schema)
            except ValueError as exc:
                errors.setdefault(kind.value, []).append(str(exc))
        return {"valid": not errors, "errors": errors}

    async def discover(
        self, kind: DeviceKind, driver_id: str, config: dict[str, Any]
    ) -> dict[str, Any]:
        self._assert_editable()
        info = self.registry.info(driver_id)
        if info.kind != kind:
            raise ValueError("驱动类型与设备位置不匹配")
        self._validate_schema(config, info.config_schema)
        slot = self._slots[kind]
        slot.driver_id = driver_id
        slot.config = dict(config)
        slot.state = ConnectionState.DISCOVERING
        slot.health = DeviceHealth(reason="正在发现设备")
        self._publish()
        try:
            driver = self.registry.create(driver_id)
            slot.discovered = await driver.discover(config)
            slot.state = ConnectionState.DISCOVERED
            slot.health = DeviceHealth(reason=f"发现 {len(slot.discovered)} 个候选设备")
        except Exception as exc:
            slot.state = ConnectionState.FAULT
            slot.health = DeviceHealth(reason=str(exc))
            self._publish()
            raise
        self._publish()
        return slot.to_dict()

    async def connect(
        self, kind: DeviceKind, driver_id: str, config: dict[str, Any]
    ) -> dict[str, Any]:
        self._assert_editable()
        info = self.registry.info(driver_id)
        if info.kind != kind:
            raise ValueError("驱动类型与设备位置不匹配")
        self._validate_schema(config, info.config_schema)
        async with self._lock:
            old_driver = self._drivers.pop(kind, None)
            if old_driver is not None:
                await old_driver.stop_stream()
                await old_driver.disconnect()
            slot = self._slots[kind]
            slot.driver_id = driver_id
            slot.config = dict(config)
            slot.state = ConnectionState.CONNECTING
            slot.health = DeviceHealth(reason="正在进行只读连接检查")
            self._publish()
            try:
                driver = self.registry.create(driver_id)
                await driver.connect(config)
                await driver.start_stream()
                health = await driver.health()
                slot.health = health
                slot.state = (
                    ConnectionState.DATA_VALID
                    if health.transport_ok and health.stream_ok and health.signal_ok
                    else ConnectionState.DEGRADED
                )
                self._drivers[kind] = driver
            except Exception as exc:
                slot.state = ConnectionState.FAULT
                slot.health = DeviceHealth(reason=str(exc))
                self._publish()
                raise
            self._publish()
            return slot.to_dict()

    async def disconnect(self, kind: DeviceKind) -> dict[str, Any]:
        self._assert_editable()
        async with self._lock:
            driver = self._drivers.pop(kind, None)
            if driver is not None:
                await driver.stop_stream()
                await driver.disconnect()
            slot = self._slots[kind]
            slot.state = ConnectionState.DISCONNECTED
            slot.health = DeviceHealth(reason="已断开")
            self._publish()
            return slot.to_dict()

    async def preview(self, kind: DeviceKind) -> dict[str, Any]:
        driver = self._drivers.get(kind)
        if driver is None:
            raise ValueError("设备尚未连接")
        try:
            payload = await driver.preview()
            self._slots[kind].health = await driver.health()
            self._publish()
            return payload
        except Exception as exc:
            self._slots[kind].state = ConnectionState.DEGRADED
            self._slots[kind].health = DeviceHealth(reason=str(exc))
            self._publish()
            raise

    async def command(self, kind: DeviceKind, command: GloveCommand) -> CommandAck:
        """向支持控制协议的设备下发一条动作命令。"""
        driver = self._drivers.get(kind)
        if driver is None:
            raise ValueError("设备尚未连接")
        if not isinstance(driver, ControlDriver):
            raise ValueError("该设备不支持动作命令")  # noqa: TRY004 - 与 manager 其他「不支持」路径保持一致
        return await driver.command(command)

    def get_drivers(self) -> dict[DeviceKind, DeviceDriver]:
        """返回当前已连接的驱动，供运行时采集循环复用。"""
        return dict(self._drivers)

    async def shutdown(self) -> None:
        for kind, driver in tuple(self._drivers.items()):
            await driver.stop_stream()
            await driver.disconnect()
            self._slots[kind].state = ConnectionState.DISCONNECTED
        self._drivers.clear()
        self._publish()
