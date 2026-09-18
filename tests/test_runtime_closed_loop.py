import asyncio
from pathlib import Path

from recoverhand_host.bootstrap import build_registry
from recoverhand_host.models import CommandAck
from recoverhand_host.runtime.replay import SessionReplay
from recoverhand_host.runtime.session_runtime import SessionRuntime, TwoFingerAssistStrategy
from recoverhand_host.runtime.trial import TrialPhase


def test_two_finger_strategy_defaults() -> None:
    strategy = TwoFingerAssistStrategy()
    actions = strategy.assist_actions({"state": "right", "grip": 0.0})
    assert [action for action, _ in actions] == ["mode", "fingers", "durations", "forces", "start"]
    assert actions[0][1] == {"mode": "grasp"}
    assert actions[1][1] == {"selected": ["thumb", "index"]}
    assert strategy.release_actions() == [("pause", {})]


def test_two_finger_strategy_is_adjustable() -> None:
    strategy = TwoFingerAssistStrategy(mode="opposition", fingers=["thumb", "middle"])
    actions = strategy.assist_actions({"grip": 0.5})
    assert actions[0][1] == {"mode": "opposition"}
    assert actions[1][1] == {"selected": ["thumb", "middle"]}


def test_grip_maps_to_force() -> None:
    strategy = TwoFingerAssistStrategy()
    assert strategy.assist_actions({"grip": 0.0})[3][1] == {"flexion": 1, "extension": 1}
    assert strategy.assist_actions({"grip": 0.5})[3][1] == {"flexion": 5, "extension": 5}
    assert strategy.assist_actions({"grip": 1.0})[3][1] == {"flexion": 9, "extension": 9}


class _RecordingGlove:
    def __init__(self) -> None:
        self.actions: list[tuple[str, dict]] = []

    async def command(self, command) -> CommandAck:
        self.actions.append((command.action, command.payload))
        return CommandAck(command_id=command.command_id, ok=True)


class _RespondingAnalyzer:
    def update(self, preview) -> None:
        pass

    def reset(self) -> None:
        pass

    def responded(self) -> bool:
        return True

    def metrics(self) -> dict:
        return {}


class _CustomStrategy:
    def assist_actions(self, intent) -> list[tuple[str, dict]]:
        return [("mode", {"mode": "mirror"}), ("start", {"confirm": True})]

    def release_actions(self) -> list[tuple[str, dict]]:
        return [("pause", {})]


def test_custom_strategy_is_injected_and_used(tmp_path) -> None:
    async def scenario() -> list[tuple[str, dict]]:
        registry = build_registry()
        eeg = registry.create("synthetic_eeg")
        await eeg.connect({"sample_rate": 250, "channel_names": "C3,Cz,C4"})
        emg = registry.create("synthetic_emg")
        await emg.connect({"sample_rate": 250, "simulate_burst": True})
        glove = _RecordingGlove()

        runtime = SessionRuntime("s1", tmp_path)
        runtime.start({"protocol": "bench"})
        short = {
            phase: 0.01
            for phase in TrialPhase
            if phase not in {TrialPhase.COMPLETED, TrialPhase.ABORTED}
        }
        await runtime.run(
            eeg, emg, glove, target_repetitions=1, tick_seconds=0.005,
            phase_durations=short, assist_strategy=_CustomStrategy(),
        )
        runtime.stop("完成")
        return glove.actions

    actions = asyncio.run(scenario())
    assert ("mode", {"mode": "mirror"}) in actions
    assert ("start", {"confirm": True}) in actions
    assert ("pause", {}) in actions


def test_closed_loop_records_intent_command_and_outcome(tmp_path: Path) -> None:
    async def scenario() -> None:
        registry = build_registry()
        eeg = registry.create("synthetic_eeg")
        await eeg.connect({"sample_rate": 250, "channel_names": "C3,Cz,C4"})
        emg = registry.create("synthetic_emg")
        await emg.connect({"sample_rate": 250, "simulate_burst": True})
        glove = registry.create("simulated_glove")
        await glove.connect({"initial_position": 512})

        runtime = SessionRuntime("s1", tmp_path)
        runtime.start({"protocol": "bench"})
        short = {
            phase: 0.01
            for phase in TrialPhase
            if phase not in {TrialPhase.COMPLETED, TrialPhase.ABORTED}
        }
        await runtime.run(
            eeg, emg, glove, target_repetitions=1, tick_seconds=0.005,
            phase_durations=short, emg_analyzer=_RespondingAnalyzer(),
        )
        runtime.stop("完成")

    asyncio.run(scenario())

    events = SessionReplay("s1", tmp_path).load_events()
    names = [event.name for event in events]
    assert "intent.frozen" in names
    assert "safety.command_authorized" in names
    assert "command.ack" in names
    assert "trial.completed" in names

    completed = next(event for event in events if event.name == "trial.completed")
    assert completed.data["phase_reached"] == "completed"
    assert completed.data["intent_state"] == "uncertain"
    assert completed.data["emg_responded"] is True
