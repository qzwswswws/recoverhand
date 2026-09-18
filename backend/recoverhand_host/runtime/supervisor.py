from __future__ import annotations

from collections.abc import Callable

from recoverhand_host.models import AssistCommand, CommandAck, RuntimeEvent
from recoverhand_host.runtime.clock import now_ns
from recoverhand_host.runtime.event_bus import EventBus


class SafetySupervisor:
    """独立安全监督器：所有运动命令必须经过它，并维护心跳租约看门狗。

    与脑电/肌电算法解耦——即使识别算法失效，也必须能够停止或释放。
    阶段 2 接入手套驱动后，心跳续约与强制释放会真正下发到设备；
    当前阶段先落地授权/应答/看门狗的纯逻辑，便于脱离硬件单测。

    时钟通过 ``now`` 注入，测试可传假时钟确定性驱动看门狗。
    """

    def __init__(
        self,
        bus: EventBus,
        lease_id: str | None = None,
        heartbeat_timeout_s: float = 2.0,
        now: Callable[[], int] = now_ns,
    ) -> None:
        self._bus = bus
        self.lease_id = lease_id
        self.heartbeat_timeout_s = heartbeat_timeout_s
        self._now = now
        self.armed = False
        self._last_heartbeat_ns: int | None = None
        self._released_reason: str | None = None

    def _emit(self, name: str, **data: object) -> RuntimeEvent:
        event = RuntimeEvent(
            name=name,
            ts_ns=self._now(),
            source="safety",
            data=data,
        )
        self._bus.publish(event)
        return event

    def authorize(self, command: AssistCommand) -> RuntimeEvent:
        """命令准入：记录待执行命令，进入 armed 状态并开始心跳计时。"""
        self.armed = True
        self._released_reason = None
        self._last_heartbeat_ns = self._now()
        return self._emit(
            "safety.command_authorized",
            command_id=command.command_id,
            action=command.action,
            lease_id=command.lease_id,
        )

    def note_heartbeat(self) -> None:
        """续心跳租约；armed 期间必须持续调用，否则看门狗会判超时。"""
        if self.armed:
            self._last_heartbeat_ns = self._now()

    def lease_expired(self) -> bool:
        return (
            self.armed
            and self._last_heartbeat_ns is not None
            and (self._now() - self._last_heartbeat_ns)
            > int(self.heartbeat_timeout_s * 1_000_000_000)
        )

    def on_command_ack(self, ack: CommandAck) -> RuntimeEvent | None:
        """命令应答：非 ok 立即强制释放，并返回释放事件。"""
        if not ack.ok:
            return self.force_release(f"命令失败: {ack.fault_code or '未知故障'}")
        self.note_heartbeat()
        return None

    def force_release(self, reason: str) -> RuntimeEvent:
        """强制释放：任何故障/超时/退出都必须落到这里。"""
        was_armed = self.armed
        self.armed = False
        self._released_reason = reason
        return self._emit(
            "safety.release",
            reason=reason,
            was_armed=was_armed,
        )

    def check_watchdog(self) -> RuntimeEvent | None:
        """看门狗检查：租约超时则强制释放并返回释放事件。"""
        if self.lease_expired():
            return self.force_release("心跳租约超时")
        return None

    def snapshot(self) -> dict[str, object]:
        return {
            "armed": self.armed,
            "lease_id": self.lease_id,
            "released_reason": self._released_reason,
        }
