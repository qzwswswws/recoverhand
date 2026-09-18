from __future__ import annotations

from pathlib import Path

from PySide6.QtCore import Qt
from PySide6.QtGui import QCloseEvent
from PySide6.QtWidgets import (
    QFrame,
    QHBoxLayout,
    QLabel,
    QMainWindow,
    QMessageBox,
    QPushButton,
    QSizePolicy,
    QStackedWidget,
    QVBoxLayout,
    QWidget,
)

from recoverhand_host.bootstrap import build_registry
from recoverhand_host.session import InvalidTransition, SessionController, SessionState
from recoverhand_host.storage.profiles import ProfileStore

from .device_worker import DeviceWorker
from .pages import (
    CalibrationPage,
    DashboardPage,
    DeviceCheckPage,
    PatientPlanPage,
    ReportPage,
    SettingsPage,
    TrainingPage,
)
from .widgets import StatusPill, refresh_style

STATE_LABELS = {
    SessionState.IDLE: "等待新会话",
    SessionState.SESSION_SETUP: "填写患者与方案",
    SessionState.DEVICE_CHECK: "设备检查",
    SessionState.CALIBRATION: "个体标定",
    SessionState.READY: "可以开始训练",
    SessionState.TRAINING: "训练进行中",
    SessionState.PAUSED: "训练已暂停",
    SessionState.ENDING: "正在结束与恢复",
    SessionState.REVIEW: "等待复核",
    SessionState.FAULT: "需要处理故障",
}

# 会话流程的顺序；用于「不能跳过设备检查/标定」的导航门控。
SESSION_ORDER = [
    SessionState.IDLE,
    SessionState.SESSION_SETUP,
    SessionState.DEVICE_CHECK,
    SessionState.CALIBRATION,
    SessionState.READY,
    SessionState.TRAINING,
    SessionState.PAUSED,
    SessionState.ENDING,
    SessionState.REVIEW,
    SessionState.FAULT,
]

# 各页面对应的最低会话状态；其余页面（总览/患者/设置）不设门控。
PAGE_MIN_STATE = {
    2: SessionState.DEVICE_CHECK,
    3: SessionState.CALIBRATION,
    4: SessionState.READY,
    5: SessionState.REVIEW,
}


class MainWindow(QMainWindow):
    def __init__(self, host_app_root: Path) -> None:
        super().__init__()
        self.setWindowTitle("RecoverHand 康复手上位机")
        self.setMinimumSize(1180, 760)
        self.resize(1440, 900)
        self.controller = SessionController()
        self.registry = build_registry()
        self.profile_store = ProfileStore(host_app_root / "data" / "recoverhand.db")
        self.profile_store.initialize()
        self.profile_store.seed_default()
        self.active_profile = self.profile_store.list()[0]
        self.device_worker = DeviceWorker()
        self.device_worker.start()
        self._build_ui()
        self.training_page.set_data_root(host_app_root / "data" / "sessions")
        self._connect_pages()
        self.device_page.set_profile(self.active_profile)
        self._apply_session()

    def _build_ui(self) -> None:
        shell = QWidget()
        shell.setObjectName("shell")
        shell_layout = QHBoxLayout(shell)
        shell_layout.setContentsMargins(0, 0, 0, 0)
        shell_layout.setSpacing(0)

        sidebar = QFrame()
        sidebar.setObjectName("sidebar")
        sidebar.setFixedWidth(232)
        sidebar_layout = QVBoxLayout(sidebar)
        sidebar_layout.setContentsMargins(20, 22, 20, 20)
        sidebar_layout.setSpacing(7)
        brand = QHBoxLayout()
        brand_mark = QLabel("RH")
        brand_mark.setObjectName("brandMark")
        brand_text = QVBoxLayout()
        brand_text.setSpacing(0)
        product = QLabel("RecoverHand")
        product.setObjectName("brandTitle")
        subtitle = QLabel("康复手上位机")
        subtitle.setObjectName("brandSubtitle")
        brand_text.addWidget(product)
        brand_text.addWidget(subtitle)
        brand.addWidget(brand_mark)
        brand.addLayout(brand_text)
        brand.addStretch(1)
        sidebar_layout.addLayout(brand)

        mode = QLabel("研 发 模 拟 模 式")
        mode.setObjectName("simulationBadge")
        mode.setAlignment(Qt.AlignmentFlag.AlignCenter)
        sidebar_layout.addWidget(mode)
        nav_caption = QLabel("康复会话")
        nav_caption.setObjectName("navCaption")
        sidebar_layout.addWidget(nav_caption)
        nav_items = [
            "总览",
            "01  患者与方案",
            "02  设备检查",
            "03  个体标定",
            "04  康复训练",
            "05  训练报告",
            "系统设置",
        ]
        self.nav_buttons: list[QPushButton] = []
        for index, label in enumerate(nav_items):
            button = QPushButton(label)
            button.setObjectName("navButton")
            button.setProperty("active", index == 0)
            button.setCursor(Qt.CursorShape.PointingHandCursor)
            button.clicked.connect(lambda _checked=False, target=index: self.navigate(target))
            sidebar_layout.addWidget(button)
            self.nav_buttons.append(button)
        sidebar_layout.addStretch(1)
        boundary = QLabel("研发原型 · 不用于无人监督训练\n真实设备未接入")
        boundary.setObjectName("sidebarBoundary")
        boundary.setWordWrap(True)
        sidebar_layout.addWidget(boundary)
        shell_layout.addWidget(sidebar)

        body = QWidget()
        body.setObjectName("body")
        body_layout = QVBoxLayout(body)
        body_layout.setContentsMargins(0, 0, 0, 0)
        body_layout.setSpacing(0)
        topbar = QFrame()
        topbar.setObjectName("topbar")
        topbar_layout = QHBoxLayout(topbar)
        topbar_layout.setContentsMargins(26, 13, 26, 13)
        self.patient_summary = QLabel("尚未选择患者或研究对象")
        self.patient_summary.setObjectName("patientSummary")
        self.session_status = StatusPill("等待新会话", "quiet")
        topbar_layout.addWidget(self.patient_summary)
        topbar_layout.addStretch(1)
        topbar_layout.addWidget(QLabel("会话状态"))
        topbar_layout.addWidget(self.session_status)
        body_layout.addWidget(topbar)

        self.pages = QStackedWidget()
        self.pages.setObjectName("pageStack")
        self.dashboard = DashboardPage()
        self.patient_page = PatientPlanPage()
        self.device_page = DeviceCheckPage(self.device_worker)
        self.calibration_page = CalibrationPage()
        self.training_page = TrainingPage(self.device_worker)
        self.report_page = ReportPage()
        self.settings_page = SettingsPage(self.registry, self.profile_store)
        for page in (
            self.dashboard,
            self.patient_page,
            self.device_page,
            self.calibration_page,
            self.training_page,
            self.report_page,
            self.settings_page,
        ):
            self.pages.addWidget(page)
        body_layout.addWidget(self.pages, 1)

        footer = QFrame()
        footer.setObjectName("safetyFooter")
        footer_layout = QHBoxLayout(footer)
        footer_layout.setContentsMargins(22, 11, 22, 11)
        safety_text = QLabel("软件停止不能替代机械快拆或独立断电；真实设备阶段必须等待固件释放确认。")
        safety_text.setObjectName("safetyText")
        self.stop_button = QPushButton("停止当前训练流程")
        self.stop_button.setProperty("variant", "danger")
        self.stop_button.setEnabled(False)
        self.stop_button.clicked.connect(self.stop_session)
        footer_layout.addWidget(safety_text, 1)
        footer_layout.addWidget(self.stop_button)
        body_layout.addWidget(footer)
        shell_layout.addWidget(body, 1)
        body.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding)
        self.setCentralWidget(shell)

    def _connect_pages(self) -> None:
        self.dashboard.new_session.connect(self.begin_session)
        self.dashboard.open_devices.connect(lambda: self.navigate(6))
        self.patient_page.submitted.connect(self.configure_session)
        self.device_page.proceed.connect(self.begin_calibration)
        self.device_page.open_settings.connect(lambda: self.navigate(6))
        self.calibration_page.completed.connect(self.complete_calibration)
        self.training_page.start_requested.connect(self.begin_training)
        self.training_page.pause_requested.connect(self.toggle_pause)
        self.training_page.repetition_completed.connect(self.record_repetition)
        self.training_page.finish_requested.connect(self.finish_training)
        self.report_page.completed.connect(self.complete_review)
        self.settings_page.profile_saved.connect(self.use_profile)

    def navigate(self, index: int) -> None:
        if index == 1 and self.controller.state == SessionState.IDLE:
            self.controller.begin_setup()
            self._apply_session()
        required = PAGE_MIN_STATE.get(index)
        if required is not None and not self._state_at_least(required):
            QMessageBox.information(
                self,
                "请按流程进行",
                "请先完成设备连接与个体标定，再进入后续步骤。",
            )
            return
        self.pages.setCurrentIndex(index)
        for button_index, button in enumerate(self.nav_buttons):
            button.setProperty("active", button_index == index)
            refresh_style(button)

    def _state_at_least(self, required: SessionState) -> bool:
        return SESSION_ORDER.index(self.controller.state) >= SESSION_ORDER.index(required)

    def begin_session(self) -> None:
        if self.controller.state != SessionState.IDLE:
            QMessageBox.information(self, "已有进行中的会话", "请完成或结束当前会话后再创建新会话。")
            return
        self.controller.begin_setup()
        self._apply_session()
        self.navigate(1)

    def configure_session(self, values: object) -> None:
        try:
            self.controller.configure(dict(values))
        except (ValueError, InvalidTransition) as exc:
            QMessageBox.warning(self, "无法进入设备检查", str(exc))
            return
        current = self.settings_page.current_profile()
        if current is not None:
            self.active_profile = current
        self.device_page.set_profile(self.active_profile)
        self._apply_session()
        self.navigate(2)

    def begin_calibration(self) -> None:
        try:
            self.controller.begin_calibration()
        except InvalidTransition as exc:
            QMessageBox.warning(self, "尚不能标定", f"请先从患者与方案步骤进入本次会话。\n\n{exc}")
            return
        self.calibration_page.set_allowed(True)
        self._apply_session()
        self.navigate(3)

    def complete_calibration(self) -> None:
        try:
            self.controller.complete_calibration()
        except InvalidTransition as exc:
            QMessageBox.warning(self, "状态错误", str(exc))
            return
        self.training_page.configure(self.controller.context.to_dict(), ready=True)
        self._apply_session()
        self.navigate(4)

    def begin_training(self) -> None:
        try:
            self.controller.begin_training()
        except InvalidTransition as exc:
            QMessageBox.warning(self, "尚不能开始训练", str(exc))
            return
        self.training_page.begin_runtime()
        self._apply_session()

    def toggle_pause(self, pause: bool) -> None:
        try:
            if pause:
                self.controller.pause_training()
            else:
                self.controller.resume_training()
        except InvalidTransition as exc:
            QMessageBox.warning(self, "状态错误", str(exc))
            return
        self.training_page.set_paused(pause)
        self._apply_session()

    def record_repetition(self) -> None:
        try:
            self.controller.record_repetition()
        except InvalidTransition:
            return
        self._apply_session()

    def stop_session(self) -> None:
        if self.controller.state not in {SessionState.TRAINING, SessionState.PAUSED}:
            return
        self.finish_training("操作者从全局停止按钮结束训练")

    def finish_training(self, reason: str) -> None:
        if self.controller.state not in {SessionState.TRAINING, SessionState.PAUSED}:
            return
        self.training_page.stop_runtime()
        try:
            self.controller.begin_ending(reason)
            self._apply_session()
            # 当前仅有模拟手套；真实设备接入后须等待固件释放状态再完成此转换。
            self.controller.complete_ending()
        except InvalidTransition as exc:
            QMessageBox.warning(self, "结束流程异常", str(exc))
            return
        self.report_page.set_context(self.controller.context.to_dict())
        self._apply_session()
        self.navigate(5)

    def complete_review(self) -> None:
        try:
            self.controller.reset()
        except InvalidTransition as exc:
            QMessageBox.warning(self, "无法完成复核", str(exc))
            return
        self.device_worker.submit("disconnect_all")
        self.calibration_page.set_allowed(False)
        self.training_page.configure(self.controller.context.to_dict(), ready=False)
        self._apply_session()
        self.navigate(0)

    def use_profile(self, profile: object) -> None:
        self.active_profile = dict(profile)
        self.device_page.set_profile(self.active_profile)

    def _apply_session(self) -> None:
        state = self.controller.state
        context = self.controller.context
        label = STATE_LABELS[state]
        tone = "quiet"
        if state in {SessionState.DEVICE_CHECK, SessionState.CALIBRATION, SessionState.READY}:
            tone = "working"
        elif state == SessionState.TRAINING:
            tone = "good"
        elif state in {SessionState.PAUSED, SessionState.ENDING}:
            tone = "warning"
        elif state == SessionState.FAULT:
            tone = "bad"
        self.session_status.set_status(label, tone)
        if context.patient_name:
            code = f" · {context.patient_code}" if context.patient_code else ""
            self.patient_summary.setText(f"{context.patient_name}{code}　|　患侧：{context.affected_side}")
        else:
            self.patient_summary.setText("尚未选择患者或研究对象")
        self.stop_button.setEnabled(state in {SessionState.TRAINING, SessionState.PAUSED})
        self.settings_page.set_locked(
            state
            in {
                SessionState.CALIBRATION,
                SessionState.READY,
                SessionState.TRAINING,
                SessionState.PAUSED,
                SessionState.ENDING,
            }
        )

    def closeEvent(self, event: QCloseEvent) -> None:
        if self.controller.state in {SessionState.TRAINING, SessionState.PAUSED}:
            answer = QMessageBox.question(
                self,
                "训练尚未结束",
                "关闭软件会中止当前模拟流程。真实设备阶段还必须独立确认手套释放。是否关闭？",
            )
            if answer != QMessageBox.StandardButton.Yes:
                event.ignore()
                return
            self.training_page.stop_runtime()
        self.training_page.shutdown()
        self.device_worker.stop()
        self.device_worker.wait(3000)
        event.accept()
