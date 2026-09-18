from pathlib import Path

from recoverhand_host.models import RuntimeEvent
from recoverhand_host.runtime.recorder import SessionRecorder
from recoverhand_host.runtime.replay import SessionReplay
from recoverhand_host.runtime.session_runtime import SessionRuntime


def test_recorder_replay_roundtrip_and_determinism(tmp_path: Path) -> None:
    recorder = SessionRecorder("s1", tmp_path)
    recorder.start({"algorithm_version": "0.1", "thresholds": {"mu": 3.0}})
    recorder.record_event(RuntimeEvent("a", 1000, "s", {"x": 1}))
    recorder.record_event(RuntimeEvent("b", 2000, "s", {"y": 2}))
    recorder.finalize()

    replay = SessionReplay("s1", tmp_path)
    events = replay.load_events()
    assert [event.name for event in events] == ["a", "b"]
    assert events[0].ts_ns == 1000
    assert events[1].data == {"y": 2}

    metadata = replay.metadata()
    assert metadata["session_id"] == "s1"
    assert metadata["algorithm_version"] == "0.1"
    assert metadata["thresholds"] == {"mu": 3.0}

    # 重复读取得到相同结果。
    assert replay.load_events() == events


def test_session_runtime_wires_events_into_recorder(tmp_path: Path) -> None:
    runtime = SessionRuntime("s1", tmp_path)
    runtime.start({"protocol": "bench"})
    trial = runtime.begin_trial(0)
    trial.advance()
    runtime.stop("手动结束")

    names = [event.name for event in SessionReplay("s1", tmp_path).load_events()]
    assert names[0] == "session.started"
    assert "trial.started" in names
    assert "trial.phase_changed" in names
    assert "safety.release" in names
    assert names[-1] == "session.stopped"
