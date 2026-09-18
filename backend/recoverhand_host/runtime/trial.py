from __future__ import annotations

from collections.abc import Callable
from enum import Enum
from typing import ClassVar

from recoverhand_host.models import RuntimeEvent
from recoverhand_host.runtime.clock import now_ns


class TrialPhase(str, Enum):
    """单个试次内的相位；与 UI 会话级状态机（session.SessionState）分层。"""

    REST_BASELINE = "rest_baseline"  # 静息基线
    CUE = "cue"  # 动作提示
    INTENT_WINDOW = "intent_window"  # EEG 意图窗口
    INTENT_FROZEN = "intent_frozen"  # 意图冻结（此后不再被运动后信号反向修改）
    SAFETY_CHECK = "safety_check"  # 安全检查
    ASSIST = "assist"  # 手套辅助运动
    HOLD = "hold"  # 保持
    RELEASE_RECOVERY = "release_recovery"  # 释放与恢复
    COMPLETED = "completed"  # 试次完成
    ABORTED = "aborted"  # 试次中止


class InvalidTrialTransition(ValueError):
    pass


class TrialStateMachine:
    """试次级状态机：唯一相位源，任何相位变化都产生一个 RuntimeEvent。"""

    _allowed: ClassVar[dict[TrialPhase, set[TrialPhase]]] = {
        TrialPhase.REST_BASELINE: {TrialPhase.CUE, TrialPhase.ABORTED},
        TrialPhase.CUE: {TrialPhase.INTENT_WINDOW, TrialPhase.ABORTED},
        TrialPhase.INTENT_WINDOW: {TrialPhase.INTENT_FROZEN, TrialPhase.ABORTED},
        TrialPhase.INTENT_FROZEN: {TrialPhase.SAFETY_CHECK, TrialPhase.ABORTED},
        TrialPhase.SAFETY_CHECK: {TrialPhase.ASSIST, TrialPhase.ABORTED},
        TrialPhase.ASSIST: {TrialPhase.HOLD, TrialPhase.ABORTED},
        TrialPhase.HOLD: {TrialPhase.RELEASE_RECOVERY, TrialPhase.ABORTED},
        TrialPhase.RELEASE_RECOVERY: {TrialPhase.COMPLETED, TrialPhase.ABORTED},
        TrialPhase.COMPLETED: set(),
        TrialPhase.ABORTED: set(),
    }

    # 快乐路径的确定性下一步，供时间驱动骨架使用。
    _next: ClassVar[dict[TrialPhase, TrialPhase]] = {
        TrialPhase.REST_BASELINE: TrialPhase.CUE,
        TrialPhase.CUE: TrialPhase.INTENT_WINDOW,
        TrialPhase.INTENT_WINDOW: TrialPhase.INTENT_FROZEN,
        TrialPhase.INTENT_FROZEN: TrialPhase.SAFETY_CHECK,
        TrialPhase.SAFETY_CHECK: TrialPhase.ASSIST,
        TrialPhase.ASSIST: TrialPhase.HOLD,
        TrialPhase.HOLD: TrialPhase.RELEASE_RECOVERY,
        TrialPhase.RELEASE_RECOVERY: TrialPhase.COMPLETED,
    }

    def __init__(
        self,
        trial_id: str,
        repetition_index: int = 0,
        bus=None,
        now: Callable[[], int] = now_ns,
    ) -> None:
        self.trial_id = trial_id
        self.repetition_index = repetition_index
        self.phase = TrialPhase.REST_BASELINE
        self._bus = bus
        self._now = now

    @property
    def terminal(self) -> bool:
        return self.phase in {TrialPhase.COMPLETED, TrialPhase.ABORTED}

    def _emit(self, name: str, **data: object) -> RuntimeEvent:
        event = RuntimeEvent(
            name=name,
            ts_ns=self._now(),
            source=f"trial:{self.trial_id}",
            data=data,
        )
        if self._bus is not None:
            self._bus.publish(event)
        return event

    def transition(self, target: TrialPhase, **data: object) -> RuntimeEvent:
        if target not in self._allowed[self.phase]:
            raise InvalidTrialTransition(
                f"不能从 {self.phase.value} 进入 {target.value}"
            )
        previous = self.phase
        self.phase = target
        return self._emit(
            "trial.phase_changed",
            previous=previous.value,
            current=target.value,
            **data,
        )

    def advance(self) -> RuntimeEvent:
        """沿快乐路径推进一个相位；终端相位后不可推进。"""
        if self.phase not in self._next:
            raise InvalidTrialTransition(f"{self.phase.value} 无后续相位")
        return self.transition(self._next[self.phase])

    def abort(self, reason: str) -> RuntimeEvent:
        return self.transition(TrialPhase.ABORTED, reason=reason)
