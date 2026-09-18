import asyncio
from pathlib import Path

from recoverhand_host.bootstrap import build_registry
from recoverhand_host.runtime.replay import SessionReplay
from recoverhand_host.runtime.session_runtime import SessionRuntime
from recoverhand_host.runtime.trial import TrialPhase


def test_advance_trial_respects_phase_duration(tmp_path: Path) -> None:
    now = 0
    runtime = SessionRuntime("s1", tmp_path, now=lambda: now)
    runtime.start({})
    trial = runtime.begin_trial(0)
    durations = {TrialPhase.REST_BASELINE: 2.0, TrialPhase.CUE: 1.0}

    now = int(1.0e9)  # 未跨过 2 秒
    assert runtime._advance_trial(durations) is False
    assert trial.phase is TrialPhase.REST_BASELINE

    now = int(2.5e9)  # 跨过 2 秒
    assert runtime._advance_trial(durations) is True
    assert trial.phase is TrialPhase.CUE


def test_publish_data_is_recorded(tmp_path: Path) -> None:
    runtime = SessionRuntime("s1", tmp_path)
    runtime.start({})
    runtime.publish_data("eeg", {"sample_rate": 250})
    runtime.stop("结束")

    names = [event.name for event in SessionReplay("s1", tmp_path).load_events()]
    assert "data.eeg" in names


def test_run_records_full_session_and_is_replayable(tmp_path: Path) -> None:
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
            eeg, emg, glove, target_repetitions=1, tick_seconds=0.005, phase_durations=short
        )
        runtime.stop("完成")

    asyncio.run(scenario())

    names = [event.name for event in SessionReplay("s1", tmp_path).load_events()]
    assert names[0] == "session.started"
    assert "trial.started" in names
    assert "data.eeg" in names
    assert "data.emg" in names
    assert "data.glove" in names
    assert "trial.completed" in names
    assert names[-1] == "session.stopped"
