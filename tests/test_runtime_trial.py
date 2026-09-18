import pytest
from recoverhand_host.runtime.trial import InvalidTrialTransition, TrialPhase, TrialStateMachine


class _RecordingBus:
    def __init__(self) -> None:
        self.events = []

    def publish(self, event) -> None:
        self.events.append(event)


def test_trial_happy_path_reaches_completion_in_order() -> None:
    trial = TrialStateMachine("s:1", repetition_index=0)
    seen = [trial.phase]
    while not trial.terminal:
        trial.advance()
        seen.append(trial.phase)

    assert seen == [
        TrialPhase.REST_BASELINE,
        TrialPhase.CUE,
        TrialPhase.INTENT_WINDOW,
        TrialPhase.INTENT_FROZEN,
        TrialPhase.SAFETY_CHECK,
        TrialPhase.ASSIST,
        TrialPhase.HOLD,
        TrialPhase.RELEASE_RECOVERY,
        TrialPhase.COMPLETED,
    ]


def test_trial_cannot_advance_past_completion() -> None:
    trial = TrialStateMachine("s:1")
    while not trial.terminal:
        trial.advance()
    with pytest.raises(InvalidTrialTransition):
        trial.advance()


def test_trial_aborts_from_any_phase_with_reason() -> None:
    trial = TrialStateMachine("s:1")
    trial.advance()  # rest_baseline -> cue
    event = trial.abort("测试中止")
    assert trial.phase == TrialPhase.ABORTED
    assert event.data["reason"] == "测试中止"


def test_trial_emits_phase_changed_event() -> None:
    bus = _RecordingBus()
    trial = TrialStateMachine("s:1", bus=bus)
    trial.advance()
    assert bus.events[-1].name == "trial.phase_changed"
    assert bus.events[-1].data["previous"] == TrialPhase.REST_BASELINE.value
    assert bus.events[-1].data["current"] == TrialPhase.CUE.value
