import pytest
from recoverhand_host.session import InvalidTransition, SessionController, SessionState


def configured_controller() -> SessionController:
    controller = SessionController()
    controller.begin_setup()
    controller.configure(
        {
            "patient_name": "研究对象 01",
            "affected_side": "右侧",
            "protocol_name": "运动想象辅助屈伸（研发）",
            "target_repetitions": 6,
            "simulation": True,
        }
    )
    return controller


def test_session_happy_path() -> None:
    controller = configured_controller()
    assert controller.state == SessionState.DEVICE_CHECK
    controller.begin_calibration()
    controller.complete_calibration()
    controller.begin_training()
    controller.record_repetition()
    controller.pause_training()
    controller.resume_training()
    controller.begin_ending("操作者结束训练")
    controller.complete_ending()
    snapshot = controller.reset()
    assert snapshot["state"] == SessionState.IDLE.value
    assert snapshot["context"]["patient_name"] == ""


def test_session_rejects_skipping_required_steps() -> None:
    controller = SessionController()
    with pytest.raises(InvalidTransition):
        controller.begin_training()


def test_configuration_requires_patient_and_side() -> None:
    controller = SessionController()
    controller.begin_setup()
    with pytest.raises(ValueError, match="不能为空"):
        controller.configure({"affected_side": "左侧"})
