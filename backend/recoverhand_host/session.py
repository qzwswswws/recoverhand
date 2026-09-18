from __future__ import annotations

from dataclasses import asdict, dataclass
from enum import Enum
from typing import Any, ClassVar


class SessionState(str, Enum):
    IDLE = "idle"
    SESSION_SETUP = "session_setup"
    DEVICE_CHECK = "device_check"
    CALIBRATION = "calibration"
    READY = "ready"
    TRAINING = "training"
    PAUSED = "paused"
    ENDING = "ending"
    REVIEW = "review"
    FAULT = "fault"


@dataclass(slots=True)
class SessionContext:
    patient_name: str = ""
    patient_code: str = ""
    affected_side: str = ""
    protocol_name: str = "运动想象辅助屈伸（研发）"
    target_repetitions: int = 10
    completed_repetitions: int = 0
    simulation: bool = True
    last_message: str = "尚未开始会话"

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


class InvalidTransition(ValueError):
    pass


class SessionController:
    """会话流程的唯一状态源；界面只能请求转换，不能自行跳过条件。"""

    _allowed: ClassVar[dict[SessionState, set[SessionState]]] = {
        SessionState.IDLE: {SessionState.SESSION_SETUP},
        SessionState.SESSION_SETUP: {SessionState.DEVICE_CHECK, SessionState.IDLE},
        SessionState.DEVICE_CHECK: {SessionState.CALIBRATION, SessionState.SESSION_SETUP, SessionState.FAULT},
        SessionState.CALIBRATION: {SessionState.READY, SessionState.DEVICE_CHECK, SessionState.FAULT},
        SessionState.READY: {SessionState.TRAINING, SessionState.DEVICE_CHECK, SessionState.IDLE},
        SessionState.TRAINING: {SessionState.PAUSED, SessionState.ENDING, SessionState.FAULT},
        SessionState.PAUSED: {SessionState.TRAINING, SessionState.ENDING, SessionState.FAULT},
        SessionState.ENDING: {SessionState.REVIEW, SessionState.FAULT},
        SessionState.REVIEW: {SessionState.IDLE},
        SessionState.FAULT: {SessionState.ENDING, SessionState.IDLE},
    }

    def __init__(self) -> None:
        self.state = SessionState.IDLE
        self.context = SessionContext()

    def snapshot(self) -> dict[str, Any]:
        return {"state": self.state.value, "context": self.context.to_dict()}

    def transition(self, target: SessionState, message: str) -> dict[str, Any]:
        if target not in self._allowed[self.state]:
            raise InvalidTransition(f"不能从 {self.state.value} 进入 {target.value}")
        self.state = target
        self.context.last_message = message
        return self.snapshot()

    def begin_setup(self) -> dict[str, Any]:
        self.context = SessionContext()
        return self.transition(SessionState.SESSION_SETUP, "请填写患者与训练方案")

    def configure(self, values: dict[str, Any]) -> dict[str, Any]:
        if self.state != SessionState.SESSION_SETUP:
            raise InvalidTransition("只能在患者与方案步骤保存会话配置")
        patient_name = str(values.get("patient_name", "")).strip()
        affected_side = str(values.get("affected_side", "")).strip()
        if not patient_name:
            raise ValueError("患者姓名或研究编号不能为空")
        if affected_side not in {"左侧", "右侧"}:
            raise ValueError("请选择患侧")
        self.context.patient_name = patient_name
        self.context.patient_code = str(values.get("patient_code", "")).strip()
        self.context.affected_side = affected_side
        self.context.protocol_name = str(values.get("protocol_name", self.context.protocol_name))
        self.context.target_repetitions = max(1, int(values.get("target_repetitions", 10)))
        self.context.simulation = bool(values.get("simulation", True))
        return self.transition(SessionState.DEVICE_CHECK, "请完成三类设备连接与信号检查")

    def begin_calibration(self) -> dict[str, Any]:
        return self.transition(SessionState.CALIBRATION, "正在执行个体化基线与意图标定")

    def complete_calibration(self) -> dict[str, Any]:
        return self.transition(SessionState.READY, "标定流程完成，可以开始训练")

    def begin_training(self) -> dict[str, Any]:
        self.context.completed_repetitions = 0
        return self.transition(SessionState.TRAINING, "训练进行中")

    def pause_training(self) -> dict[str, Any]:
        return self.transition(SessionState.PAUSED, "训练已暂停")

    def resume_training(self) -> dict[str, Any]:
        return self.transition(SessionState.TRAINING, "训练已继续")

    def record_repetition(self) -> dict[str, Any]:
        if self.state != SessionState.TRAINING:
            raise InvalidTransition("只有训练进行中才能记录重复次数")
        self.context.completed_repetitions += 1
        return self.snapshot()

    def begin_ending(self, reason: str) -> dict[str, Any]:
        return self.transition(SessionState.ENDING, reason)

    def complete_ending(self) -> dict[str, Any]:
        return self.transition(SessionState.REVIEW, "本次会话已结束，请复核记录")

    def reset(self) -> dict[str, Any]:
        if self.state != SessionState.REVIEW:
            raise InvalidTransition("请先完成并复核当前会话")
        snapshot = self.transition(SessionState.IDLE, "会话已归档，返回首页")
        self.context = SessionContext()
        return {"state": snapshot["state"], "context": self.context.to_dict()}
