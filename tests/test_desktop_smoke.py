import os
import time

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtWidgets import QApplication
from recoverhand_host.desktop.main_window import MainWindow
from recoverhand_host.session import SessionState


def wait_until(app: QApplication, predicate, timeout: float = 3.0) -> None:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        app.processEvents()
        if predicate():
            return
        time.sleep(0.01)
    raise AssertionError("等待桌面界面状态变化超时")


def test_desktop_window_builds_and_closes(tmp_path) -> None:
    app = QApplication.instance() or QApplication([])
    window = MainWindow(tmp_path)
    try:
        assert window.pages.count() == 7
        assert len(window.nav_buttons) == 7
        assert window.active_profile["name"] == "全模拟联调"
        assert window.windowTitle() == "RecoverHand 康复手上位机"
        app.processEvents()
    finally:
        window.close()
        app.processEvents()


def test_desktop_simulation_workflow(tmp_path) -> None:
    app = QApplication.instance() or QApplication([])
    window = MainWindow(tmp_path)
    try:
        window.begin_session()
        window.patient_page.patient_name.setText("研究对象 01")
        window.patient_page.patient_code.setText("RH-SIM-001")
        window.patient_page.right_side.setChecked(True)
        window.patient_page.repetitions.setValue(1)
        window.patient_page._submit()
        assert window.controller.state == SessionState.DEVICE_CHECK
        assert window.pages.currentWidget() is window.device_page

        window.device_page.connect_all()
        wait_until(app, lambda: window.device_page.next_button.isEnabled())
        window.device_page.next_button.click()
        assert window.controller.state == SessionState.CALIBRATION

        window.calibration_page.timer.setInterval(1)
        window.calibration_page.start_button.click()
        wait_until(app, lambda: window.controller.state == SessionState.READY)
        assert window.pages.currentWidget() is window.training_page

        window.training_page.start_button.click()
        assert window.controller.state == SessionState.TRAINING
        # 手动驱动一个运行时事件：试次完成 → repetition_completed → finish_requested
        window.training_page._on_runtime_event(
            {"name": "trial.completed", "data": {"phase_reached": "completed"}}
        )
        assert window.controller.state == SessionState.REVIEW
        assert window.controller.context.completed_repetitions == 1
        assert window.pages.currentWidget() is window.report_page

        window.report_page.completed.emit()
        assert window.controller.state == SessionState.IDLE
        assert window.pages.currentWidget() is window.dashboard
    finally:
        window.close()
        app.processEvents()
