from __future__ import annotations

from dataclasses import asdict, dataclass, field
from enum import Enum
from typing import Any


class DeviceKind(str, Enum):
    EEG = "eeg"
    EMG = "emg"
    GLOVE = "glove"


class ConnectionState(str, Enum):
    UNCONFIGURED = "unconfigured"
    DISCOVERING = "discovering"
    DISCOVERED = "discovered"
    CONNECTING = "connecting"
    CONNECTED = "connected"
    DATA_VALID = "data_valid"
    DEGRADED = "degraded"
    RECONNECTING = "reconnecting"
    FAULT = "fault"
    DISCONNECTED = "disconnected"


@dataclass(slots=True)
class DeviceHealth:
    transport_ok: bool = False
    stream_ok: bool = False
    time_sync_ok: bool = False
    signal_ok: bool = False
    control_ready: bool = False
    reason: str = "尚未连接"

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(slots=True)
class DriverInfo:
    id: str
    kind: DeviceKind
    display_name: str
    description: str
    config_schema: dict[str, Any]
    available: bool = True
    maturity: str = "prototype"
    unavailable_reason: str | None = None

    def to_dict(self) -> dict[str, Any]:
        payload = asdict(self)
        payload["kind"] = self.kind.value
        return payload


@dataclass(slots=True)
class DeviceSlot:
    kind: DeviceKind
    driver_id: str | None = None
    state: ConnectionState = ConnectionState.UNCONFIGURED
    config: dict[str, Any] = field(default_factory=dict)
    health: DeviceHealth = field(default_factory=DeviceHealth)
    discovered: list[dict[str, Any]] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {
            "kind": self.kind.value,
            "driver_id": self.driver_id,
            "state": self.state.value,
            "config": self.config,
            "health": self.health.to_dict(),
            "discovered": self.discovered,
        }


@dataclass(slots=True)
class EegFrame:
    samples: list[list[float]]
    channel_names: list[str]
    sample_rate: float
    device_time: float | None
    host_time: float
    sequence: int
    quality: dict[str, float]


@dataclass(slots=True)
class EmgFrame:
    samples: list[float]
    sample_rate: float
    device_time: float | None
    host_time: float
    sequence: int
    packet_loss: float
    signal_quality: float


@dataclass(slots=True)
class GloveState:
    connected: bool
    armed: bool
    released: bool
    position: float | None
    target: float | None
    tension: float | None
    motion_state: str
    fault_code: str | None
    device_time: float | None
    host_time: float


@dataclass(slots=True)
class GloveCommand:
    command_id: str
    action: str
    trajectory_profile: str
    assist_level: float
    hold_ms: int
    lease_id: str
    payload: dict[str, Any] = field(default_factory=dict)


@dataclass(slots=True)
class EegIntentEvent:
    """运动前 EEG 窗口产出的意图事件（方向 + 抓握量）。"""

    state: str  # left / right / uncertain
    grip: float  # 0..1 抓握量
    laterality_db: float
    confidence: float
    method: str
    model_version: str
    ts_ns: int
    sequence: int = 0
    feature_window: tuple[float, float] | None = None

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(slots=True)
class AssistCommand:
    """试次级辅助动作命令，经安全监督器转译为设备级 GloveCommand。"""

    command_id: str
    trial_id: str
    action: str
    assist_level: float
    hold_ms: int
    lease_id: str
    payload: dict[str, Any] = field(default_factory=dict)


@dataclass(slots=True)
class CommandAck:
    """设备对一条运动命令的应答；ok=False 时须触发安全释放。"""

    command_id: str
    ok: bool
    fault_code: str | None = None
    echoed_state: dict[str, Any] = field(default_factory=dict)
    ts_ns: int = 0

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(slots=True)
class TrialOutcome:
    """单个试次的最终结果，用于记录与跨试次慢速闭环。"""

    trial_id: str
    repetition_index: int
    phase_reached: str
    intent_state: str | None = None
    emg_responded: bool | None = None
    fault_code: str | None = None
    ts_ns: int = 0

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(slots=True)
class RuntimeEvent:
    """运行时统一事件信封：状态机、监督器、采集循环与记录器之间流通的最小事件。"""

    name: str
    ts_ns: int
    source: str
    data: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {
            "name": self.name,
            "ts_ns": self.ts_ns,
            "source": self.source,
            "data": self.data,
        }
