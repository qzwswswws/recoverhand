from __future__ import annotations

import asyncio
from collections.abc import Callable
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Protocol

from recoverhand_host.devices.base import ControlDriver
from recoverhand_host.devices.emg_analysis import EmgResponseAnalyzer, EnvelopeEmgAnalyzer
from recoverhand_host.models import (
    AssistCommand,
    CommandAck,
    GloveCommand,
    RuntimeEvent,
    TrialOutcome,
)
from recoverhand_host.runtime.clock import now_ns
from recoverhand_host.runtime.event_bus import EventBus
from recoverhand_host.runtime.recorder import SessionRecorder
from recoverhand_host.runtime.supervisor import SafetySupervisor
from recoverhand_host.runtime.trial import TrialPhase, TrialStateMachine

# 单个试次各相位的默认时长（秒）。阶段 1 仅用于联调，真实值由算法/医护后续调整。
DEFAULT_PHASE_DURATIONS: dict[TrialPhase, float] = {
    TrialPhase.REST_BASELINE: 2.0,
    TrialPhase.CUE: 1.0,
    TrialPhase.INTENT_WINDOW: 4.0,
    TrialPhase.INTENT_FROZEN: 0.2,
    TrialPhase.SAFETY_CHECK: 0.2,
    TrialPhase.ASSIST: 2.0,
    TrialPhase.HOLD: 1.0,
    TrialPhase.RELEASE_RECOVERY: 2.0,
}


class AssistStrategy(Protocol):
    """辅助策略：把冻结的 EEG 意图映射为手套命令序列。

    实现此协议即可替换闭环里的「意图 → 动作」映射；``assist_actions``
    接收冻结意图（含 ``state``/``grip``），返回按顺序下发的手套命令。
    """

    def assist_actions(self, intent: dict[str, Any] | None) -> list[tuple[str, dict[str, Any]]]:
        ...

    def release_actions(self) -> list[tuple[str, dict[str, Any]]]:
        ...


@dataclass(slots=True)
class TwoFingerAssistStrategy:
    """默认两指策略：拇指+食指拿捏，抓握量映射屈曲/伸展力量（1..9）。

    字段可调；如需不同指位、模式或「意图方向→指位」的映射，替换本策略即可。
    """

    mode: str = "grasp"
    fingers: list[str] = field(default_factory=lambda: ["thumb", "index"])
    flexion_duration: int = 3
    extension_duration: int = 3
    min_force: int = 1
    max_force: int = 9

    def _force_from_grip(self, grip: float) -> int:
        level = 1 + max(0.0, min(1.0, grip)) * (self.max_force - self.min_force)
        return max(self.min_force, min(self.max_force, round(level)))

    def assist_actions(self, intent: dict[str, Any] | None) -> list[tuple[str, dict[str, Any]]]:
        grip = float((intent or {}).get("grip", 0.0))
        force = self._force_from_grip(grip)
        return [
            ("mode", {"mode": self.mode}),
            ("fingers", {"selected": list(self.fingers)}),
            ("durations", {"flexion": self.flexion_duration, "extension": self.extension_duration}),
            ("forces", {"flexion": force, "extension": force}),
            ("start", {"confirm": True}),
        ]

    def release_actions(self) -> list[tuple[str, dict[str, Any]]]:
        return [("pause", {})]


class SessionRuntime:
    """运行时组装：统一时钟 + 事件总线 + 试次状态机 + 安全监督器 + 记录器。

    不依赖 Qt；UI 只通过 ``subscribe()`` 订阅事件、通过 ``snapshot()`` 读取当前状态。
    ``run()`` 是常驻采集循环：轮询三个设备适配器、推进试次状态机，并在试次内
    完成「意图冻结 → 安全检查 → 手套辅助 → 释放」的闭环。
    """

    def __init__(self, session_id: str, data_root: Path, *, now: Callable[[], int] = now_ns) -> None:
        self.session_id = session_id
        self._now = now
        self.bus = EventBus()
        self.recorder = SessionRecorder(session_id, data_root)
        self.supervisor = SafetySupervisor(self.bus, lease_id=session_id, now=now)
        self.trial: TrialStateMachine | None = None
        self._started = False
        self._running = False
        self._phase_started_ns = 0

    def subscribe(self):
        return self.bus.subscribe()

    def unsubscribe(self, queue) -> None:
        self.bus.unsubscribe(queue)

    def start(self, metadata: dict[str, Any]) -> None:
        if self._started:
            raise RuntimeError("运行时已启动")
        self.recorder.start(metadata)
        self.bus.add_sink(self.recorder.record_event)
        self._started = True
        self._running = True
        self.bus.publish(RuntimeEvent("session.started", self._now(), f"session:{self.session_id}", {}))

    def begin_trial(self, repetition_index: int) -> TrialStateMachine:
        if self.trial is not None and not self.trial.terminal:
            raise RuntimeError("当前试次尚未结束，不能开始新试次")
        trial = TrialStateMachine(
            trial_id=f"{self.session_id}:t{repetition_index + 1}",
            repetition_index=repetition_index,
            bus=self.bus,
            now=self._now,
        )
        self.trial = trial
        self._phase_started_ns = self._now()
        self.bus.publish(
            RuntimeEvent(
                "trial.started",
                self._now(),
                f"trial:{trial.trial_id}",
                {"repetition_index": repetition_index},
            )
        )
        return trial

    def publish_data(self, kind: str, payload: dict[str, Any]) -> None:
        """把设备适配器的一次预览作为数据事件广播并落盘。"""
        self.bus.publish(RuntimeEvent(f"data.{kind}", self._now(), f"data:{kind}", payload))

    def _advance_trial(self, durations: dict[TrialPhase, float]) -> bool:
        trial = self.trial
        if trial is None or trial.terminal:
            return False
        duration = durations.get(trial.phase, 1.0)
        if self._now() - self._phase_started_ns >= int(duration * 1_000_000_000):
            trial.advance()
            self._phase_started_ns = self._now()
            return True
        return False

    def _freeze_intent(self, preview: dict[str, Any] | None) -> dict[str, Any]:
        """冻结运动前 EEG 意图；此后不再被运动后信号反向修改。"""
        intent = dict((preview or {}).get("intent") or {})
        if not intent.get("state"):
            intent = {
                "state": "uncertain",
                "grip": 0.0,
                "laterality_db": None,
                "confidence": 0.0,
                "method": "none",
                "model_version": "none",
            }
        trial_id = self.trial.trial_id if self.trial else None
        self.bus.publish(
            RuntimeEvent(
                "intent.frozen",
                self._now(),
                f"trial:{trial_id}",
                {"trial_id": trial_id, **intent},
            )
        )
        return intent

    def _authorize_assist(self, trial: TrialStateMachine, intent: dict[str, Any]) -> AssistCommand:
        grip = max(0.0, min(1.0, float((intent or {}).get("grip", 0.0))))
        assist = AssistCommand(
            command_id=f"{trial.trial_id}:assist",
            trial_id=trial.trial_id,
            action="assist",
            assist_level=grip,
            hold_ms=1000,
            lease_id=self.session_id,
        )
        self.supervisor.authorize(assist)
        return assist

    async def _send_glove(
        self, glove, action: str, payload: dict[str, Any] | None = None
    ) -> CommandAck | None:
        """向手套下发动作命令并回传应答；失败即触发安全释放。"""
        if glove is None or not isinstance(glove, ControlDriver):
            return None
        command = GloveCommand(
            command_id=f"{self.session_id}:{action}:{self._now()}",
            action=action,
            trajectory_profile="assist",
            assist_level=0.0,
            hold_ms=0,
            lease_id=self.session_id,
            payload=dict(payload or {}),
        )
        try:
            ack = await glove.command(command)
        except Exception as exc:  # noqa: BLE001 - 运行边界统一转成可见故障。
            ack = CommandAck(
                command_id=command.command_id, ok=False, fault_code=str(exc), ts_ns=self._now()
            )
        self.bus.publish(RuntimeEvent("command.ack", self._now(), "glove", ack.to_dict()))
        if ack.ok is False:
            self.supervisor.force_release(ack.fault_code or "辅助命令失败")
        else:
            self.supervisor.on_command_ack(ack)
        return ack

    def _record_outcome(
        self,
        trial: TrialStateMachine,
        repetition_index: int,
        intent: dict[str, Any] | None,
        emg_observed: bool,
    ) -> None:
        outcome = TrialOutcome(
            trial_id=trial.trial_id,
            repetition_index=repetition_index,
            phase_reached=trial.phase.value,
            intent_state=(intent or {}).get("state"),
            emg_responded=emg_observed,
        )
        self.bus.publish(
            RuntimeEvent(
                "trial.completed",
                self._now(),
                f"trial:{trial.trial_id}",
                outcome.to_dict(),
            )
        )

    async def _poll(self, eeg, emg, glove) -> tuple[dict[str, Any] | None, dict[str, Any] | None, dict[str, Any] | None]:
        previews: dict[str, Any] = {}
        for kind, driver in (("eeg", eeg), ("emg", emg), ("glove", glove)):
            if driver is None:
                previews[kind] = None
                continue
            try:
                preview = await driver.preview()
            except Exception:  # noqa: BLE001 - 单个设备采集失败不中断试次，由 health/监督器处理
                preview = None
            if preview is not None:
                self.publish_data(kind, preview)
            previews[kind] = preview
        return previews["eeg"], previews["emg"], previews["glove"]

    async def run(
        self,
        eeg,
        emg,
        glove,
        *,
        target_repetitions: int = 10,
        tick_seconds: float = 0.05,
        phase_durations: dict[TrialPhase, float] | None = None,
        assist_strategy: AssistStrategy | None = None,
        emg_analyzer: EmgResponseAnalyzer | None = None,
    ) -> None:
        """常驻采集循环：推进试次并执行「意图冻结 → 安全检查 → 辅助 → 释放」闭环。"""
        if not self._started:
            raise RuntimeError("请先调用 start() 再运行采集循环")
        durations = phase_durations or DEFAULT_PHASE_DURATIONS
        strategy = assist_strategy or TwoFingerAssistStrategy()
        analyzer = emg_analyzer or EnvelopeEmgAnalyzer()
        repetition = 0
        trial = self.begin_trial(repetition)
        intent: dict[str, Any] | None = None
        while self._running and repetition < target_repetitions:
            eeg_p, emg_p, _glove_p = await self._poll(eeg, emg, glove)

            self.supervisor.note_heartbeat()
            if self.supervisor.check_watchdog() is not None:
                trial.abort("心跳租约超时")
                break

            advanced = False
            if not trial.terminal:
                advanced = self._advance_trial(durations)

            if advanced and not trial.terminal:
                if trial.phase is TrialPhase.INTENT_FROZEN:
                    intent = self._freeze_intent(eeg_p)
                elif trial.phase is TrialPhase.SAFETY_CHECK:
                    self._authorize_assist(trial, intent or {})
                elif trial.phase is TrialPhase.ASSIST:
                    for action, payload in strategy.assist_actions(intent):
                        ack = await self._send_glove(glove, action, payload)
                        if ack is not None and ack.ok is False:
                            trial.abort("辅助命令失败")
                            break
                elif trial.phase is TrialPhase.RELEASE_RECOVERY:
                    for action, payload in strategy.release_actions():
                        await self._send_glove(glove, action, payload)

            if trial.phase in {TrialPhase.ASSIST, TrialPhase.HOLD} and emg_p is not None:
                analyzer.update(emg_p)

            if trial.phase is TrialPhase.COMPLETED:
                self._record_outcome(trial, repetition, intent, analyzer.responded())
                repetition += 1
                intent = None
                analyzer.reset()
                if repetition < target_repetitions:
                    trial = self.begin_trial(repetition)
            elif trial.phase is TrialPhase.ABORTED:
                self._record_outcome(trial, repetition, intent, analyzer.responded())
                break

            await asyncio.sleep(tick_seconds)

    def stop(self, reason: str) -> None:
        if not self._started:
            return
        self._running = False
        self.supervisor.force_release(reason)
        self.bus.publish(
            RuntimeEvent("session.stopped", self._now(), f"session:{self.session_id}", {"reason": reason})
        )
        self.bus.remove_sink(self.recorder.record_event)
        self.recorder.finalize()
        self._started = False

    def snapshot(self) -> dict[str, Any]:
        trial = None
        if self.trial is not None:
            trial = {
                "trial_id": self.trial.trial_id,
                "phase": self.trial.phase.value,
                "repetition_index": self.trial.repetition_index,
            }
        return {
            "session_id": self.session_id,
            "started": self._started,
            "running": self._running,
            "trial": trial,
            "supervisor": self.supervisor.snapshot(),
        }
