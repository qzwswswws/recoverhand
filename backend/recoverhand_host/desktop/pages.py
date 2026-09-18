from __future__ import annotations

import uuid
from typing import Any, ClassVar

from PySide6.QtCore import Qt, QTimer, Signal
from PySide6.QtWidgets import (
    QButtonGroup,
    QCheckBox,
    QComboBox,
    QDoubleSpinBox,
    QFormLayout,
    QFrame,
    QGridLayout,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QMessageBox,
    QPushButton,
    QRadioButton,
    QScrollArea,
    QSpinBox,
    QVBoxLayout,
    QWidget,
)

from recoverhand_host.devices.manager import DeviceManager
from recoverhand_host.devices.registry import DriverRegistry
from recoverhand_host.devices.sy_hr12_protocol import FINGER_LABELS, FINGERS, MODE_LABELS, Mode
from recoverhand_host.models import DeviceKind, GloveCommand
from recoverhand_host.storage.profiles import ProfileStore

from .device_worker import DeviceWorker
from .particle_hand import ParticleHandCard
from .widgets import (
    Card,
    DeviceStatusCard,
    MetricCard,
    PageTitle,
    SignalPlot,
    StatusPill,
)


class BasePage(QScrollArea):
    def __init__(self) -> None:
        super().__init__()
        self.setWidgetResizable(True)
        self.setFrameShape(QFrame.Shape.NoFrame)
        self.setObjectName("pageScroll")
        self.content = QWidget()
        self.content.setObjectName("pageContent")
        self.root = QVBoxLayout(self.content)
        self.root.setContentsMargins(32, 28, 32, 36)
        self.root.setSpacing(20)
        self.setWidget(self.content)


def section_title(title: str, detail: str = "") -> QWidget:
    widget = QWidget()
    layout = QHBoxLayout(widget)
    layout.setContentsMargins(0, 0, 0, 0)
    heading = QLabel(title)
    heading.setObjectName("sectionTitle")
    layout.addWidget(heading)
    if detail:
        description = QLabel(detail)
        description.setObjectName("mutedText")
        layout.addWidget(description)
    layout.addStretch(1)
    return widget


def action_button(text: str, primary: bool = False) -> QPushButton:
    button = QPushButton(text)
    button.setProperty("variant", "primary" if primary else "secondary")
    button.setMinimumHeight(44)
    return button


class DashboardPage(BasePage):
    new_session = Signal()
    open_devices = Signal()

    def __init__(self) -> None:
        super().__init__()
        hero = Card("heroCard")
        hero_layout = QGridLayout(hero)
        hero_layout.setContentsMargins(28, 26, 28, 26)
        hero_layout.setHorizontalSpacing(28)
        hero_layout.setVerticalSpacing(12)
        eyebrow = QLabel("RECOVERHAND / 康复训练工作站")
        eyebrow.setObjectName("eyebrowOnDark")
        title = QLabel("让每一次辅助运动，\n都能被记录、解释和复核。")
        title.setObjectName("heroTitle")
        title.setWordWrap(True)
        detail = QLabel(
            "面向医护监督下的神经损伤手功能康复研究。"
            "EEG 判断运动意图，腕部单通道 sEMG 观察活动响应，辅助手套完成受限运动。"
        )
        detail.setObjectName("heroDescription")
        detail.setWordWrap(True)
        start = action_button("开始新的训练会话", primary=True)
        start.setObjectName("heroAction")
        start.clicked.connect(self.new_session)
        hero_layout.addWidget(eyebrow, 0, 0)
        hero_layout.addWidget(title, 1, 0)
        hero_layout.addWidget(detail, 2, 0)
        hero_layout.addWidget(start, 3, 0, alignment=Qt.AlignmentFlag.AlignLeft)
        hero_layout.setColumnStretch(0, 3)
        illustration = QLabel("EEG  →  意图\n            ↓\nsEMG ← 辅助手套")
        illustration.setObjectName("heroDiagram")
        illustration.setAlignment(Qt.AlignmentFlag.AlignCenter)
        hero_layout.addWidget(illustration, 0, 1, 4, 1)

        self.root.addWidget(hero)
        self.root.addWidget(section_title("一次标准会话", "六步完成，设备维护与患者流程分开"))
        steps = QGridLayout()
        step_data = [
            ("01", "患者与方案", "患侧、次数与训练协议"),
            ("02", "设备检查", "连接、时间与信号质量"),
            ("03", "个体标定", "静息基线与意图特征"),
            ("04", "康复训练", "提示、判断和受限辅助"),
            ("05", "结束恢复", "释放确认与恢复观察"),
            ("06", "训练报告", "结果、异常与人工复核"),
        ]
        for index, (number, title_text, body) in enumerate(step_data):
            card = Card("stepCard")
            layout = QVBoxLayout(card)
            layout.setContentsMargins(17, 15, 17, 15)
            number_label = QLabel(number)
            number_label.setObjectName("stepNumber")
            title_label = QLabel(title_text)
            title_label.setObjectName("cardTitle")
            body_label = QLabel(body)
            body_label.setObjectName("mutedText")
            body_label.setWordWrap(True)
            layout.addWidget(number_label)
            layout.addWidget(title_label)
            layout.addWidget(body_label)
            steps.addWidget(card, index // 3, index % 3)
        self.root.addLayout(steps)

        boundary = Card("noticeCard")
        boundary_layout = QHBoxLayout(boundary)
        boundary_layout.setContentsMargins(18, 15, 18, 15)
        boundary_text = QLabel(
            "当前版本是研发验证界面。模拟数据只能验证流程与软件联动，不能证明意图识别或康复效果。"
        )
        boundary_text.setWordWrap(True)
        devices = action_button("查看设备设置")
        devices.clicked.connect(self.open_devices)
        boundary_layout.addWidget(boundary_text, 1)
        boundary_layout.addWidget(devices)
        self.root.addWidget(boundary)
        self.root.addStretch(1)


class PatientPlanPage(BasePage):
    submitted = Signal(object)

    def __init__(self) -> None:
        super().__init__()
        self.root.addWidget(PageTitle("步骤 01 / 06", "患者与训练方案", "先确认对象、患侧和本次目标，再接入设备。"))
        form_card = Card()
        form = QFormLayout(form_card)
        form.setContentsMargins(24, 22, 24, 22)
        form.setHorizontalSpacing(24)
        form.setVerticalSpacing(17)
        self.patient_name = QLineEdit()
        self.patient_name.setPlaceholderText("姓名或匿名研究编号")
        self.patient_code = QLineEdit()
        self.patient_code.setPlaceholderText("选填，例如 RH-2026-001")
        self.protocol = QComboBox()
        self.protocol.addItems(["运动想象辅助屈伸（研发）", "被动辅助屈伸（对照）", "仅信号采集（研究）"])
        self.repetitions = QSpinBox()
        self.repetitions.setRange(1, 100)
        self.repetitions.setValue(10)
        self.repetitions.setSuffix(" 次")
        side_widget = QWidget()
        side_layout = QHBoxLayout(side_widget)
        side_layout.setContentsMargins(0, 0, 0, 0)
        self.left_side = QRadioButton("左侧")
        self.right_side = QRadioButton("右侧")
        side_group = QButtonGroup(self)
        side_group.addButton(self.left_side)
        side_group.addButton(self.right_side)
        side_layout.addWidget(self.left_side)
        side_layout.addWidget(self.right_side)
        side_layout.addStretch(1)
        self.simulation = QCheckBox("研发模拟模式：不连接真实人体信号，不发送真实运动命令")
        self.simulation.setChecked(True)
        self.simulation.setEnabled(False)
        form.addRow("患者/研究对象 *", self.patient_name)
        form.addRow("档案编号", self.patient_code)
        form.addRow("患侧 *", side_widget)
        form.addRow("训练协议", self.protocol)
        form.addRow("目标重复次数", self.repetitions)
        form.addRow("当前运行边界", self.simulation)
        self.root.addWidget(form_card)

        checklist = Card("noticeCard")
        checklist_layout = QVBoxLayout(checklist)
        checklist_layout.setContentsMargins(20, 17, 20, 17)
        checklist_layout.addWidget(QLabel("开始前确认"), alignment=Qt.AlignmentFlag.AlignLeft)
        text = QLabel("• 医护人员全程监督　• 手套机械快拆可用　• 患者无明显不适　• 当前只做模拟软件联调")
        text.setObjectName("mutedText")
        text.setWordWrap(True)
        checklist_layout.addWidget(text)
        self.root.addWidget(checklist)
        next_button = action_button("保存并进入设备检查", primary=True)
        next_button.clicked.connect(self._submit)
        self.root.addWidget(next_button, alignment=Qt.AlignmentFlag.AlignRight)
        self.root.addStretch(1)

    def _submit(self) -> None:
        side = "左侧" if self.left_side.isChecked() else "右侧" if self.right_side.isChecked() else ""
        self.submitted.emit(
            {
                "patient_name": self.patient_name.text(),
                "patient_code": self.patient_code.text(),
                "affected_side": side,
                "protocol_name": self.protocol.currentText(),
                "target_repetitions": self.repetitions.value(),
                "simulation": self.simulation.isChecked(),
            }
        )


class DeviceCheckPage(BasePage):
    proceed = Signal()
    open_settings = Signal()

    def __init__(self, worker: DeviceWorker) -> None:
        super().__init__()
        self.worker = worker
        self.profile: dict[str, Any] | None = None
        self._all_ready = False
        self.root.addWidget(
            PageTitle(
                "步骤 02 / 06",
                "设备连接与质量检查",
                "按连接档案依次检查 EEG、腕部单通道 sEMG 和辅助手套。连接通过不代表算法有效。",
            )
        )
        toolbar = Card("toolbarCard")
        toolbar_layout = QHBoxLayout(toolbar)
        toolbar_layout.setContentsMargins(18, 14, 18, 14)
        self.profile_label = QLabel("连接档案：尚未载入")
        self.profile_label.setObjectName("toolbarTitle")
        configure = action_button("修改设备设置")
        configure.clicked.connect(self.open_settings)
        self.connect_button = action_button("按当前档案检查全部", primary=True)
        self.connect_button.clicked.connect(self.connect_all)
        toolbar_layout.addWidget(self.profile_label)
        toolbar_layout.addStretch(1)
        toolbar_layout.addWidget(configure)
        toolbar_layout.addWidget(self.connect_button)
        self.root.addWidget(toolbar)

        cards_layout = QGridLayout()
        self.cards = {
            "eeg": DeviceStatusCard("01", "EEG · 运动想象", "脑电意图设备", "等待连接和信号预览", True),
            "emg": DeviceStatusCard("02", "sEMG · 单个双电极", "腕部肌电贴片", "只解释局部肌肉活动时序和幅度", True),
            "glove": DeviceStatusCard(
                "03",
                "执行与反馈",
                "辅助屈伸手套",
                "本页只读取状态，不提供动作按钮",
                False,
                with_hand=True,
            ),
        }
        cards_layout.addWidget(self.cards["eeg"], 0, 0)
        cards_layout.addWidget(self.cards["emg"], 0, 1)
        cards_layout.addWidget(self.cards["glove"], 1, 0, 1, 2)
        self.root.addLayout(cards_layout)

        self._build_glove_controls()

        self.result_banner = Card("noticeCard")
        result_layout = QHBoxLayout(self.result_banner)
        result_layout.setContentsMargins(18, 14, 18, 14)
        self.result_status = StatusPill("等待检查", "quiet")
        self.result_text = QLabel("完成三项检查后才能进入个体化标定。")
        self.result_text.setWordWrap(True)
        self.next_button = action_button("进入个体化标定", primary=True)
        self.next_button.setEnabled(False)
        self.next_button.clicked.connect(self.proceed)
        result_layout.addWidget(self.result_status)
        result_layout.addWidget(self.result_text, 1)
        result_layout.addWidget(self.next_button)
        self.root.addWidget(self.result_banner)
        self.root.addStretch(1)

        worker.state_changed.connect(self.apply_state)
        worker.completed.connect(self._work_completed)
        worker.failed.connect(self._work_failed)

    def set_profile(self, profile: dict[str, Any]) -> None:
        self.profile = profile
        self.profile_label.setText(f"连接档案：{profile['name']}")
        self._reset_cards()

    def _reset_cards(self) -> None:
        self._all_ready = False
        self.next_button.setEnabled(False)
        self.result_status.set_status("等待检查", "quiet")
        self.result_text.setText("完成三项检查后才能进入个体化标定。")
        for card in self.cards.values():
            card.set_connection("unconfigured", "等待检查")

    def _build_glove_controls(self) -> None:
        panel = Card("toolbarCard")
        panel_layout = QVBoxLayout(panel)
        panel_layout.setContentsMargins(18, 14, 18, 14)
        panel_layout.setSpacing(10)
        title = QLabel("手套动作控制（SY-HR12）")
        title.setObjectName("toolbarTitle")
        panel_layout.addWidget(title)

        mode_row = QHBoxLayout()
        mode_row.addWidget(QLabel("模式"))
        self.glove_mode = QComboBox()
        for mode in Mode:
            self.glove_mode.addItem(MODE_LABELS[mode], mode.value)
        mode_row.addWidget(self.glove_mode)
        mode_row.addStretch(1)
        panel_layout.addLayout(mode_row)

        finger_row = QHBoxLayout()
        finger_row.addWidget(QLabel("对指手指（拇指自动包含）"))
        self.finger_combo = QComboBox()
        for name in FINGERS[1:]:  # 食指/中指/无名指/小指
            self.finger_combo.addItem(FINGER_LABELS[name], name)
        self.finger_combo.setCurrentIndex(0)  # 默认食指
        finger_row.addWidget(self.finger_combo)
        finger_row.addStretch(1)
        panel_layout.addLayout(finger_row)

        param_row = QHBoxLayout()
        param_row.addWidget(QLabel("屈曲力量"))
        self.flexion_force = QSpinBox()
        self.flexion_force.setRange(1, 9)
        self.flexion_force.setValue(3)
        param_row.addWidget(self.flexion_force)
        param_row.addWidget(QLabel("伸展力量"))
        self.extension_force = QSpinBox()
        self.extension_force.setRange(1, 9)
        self.extension_force.setValue(3)
        param_row.addWidget(self.extension_force)
        param_row.addWidget(QLabel("屈曲时长"))
        self.flexion_duration = QSpinBox()
        self.flexion_duration.setRange(1, 9)
        self.flexion_duration.setValue(3)
        param_row.addWidget(self.flexion_duration)
        param_row.addWidget(QLabel("伸展时长"))
        self.extension_duration = QSpinBox()
        self.extension_duration.setRange(1, 9)
        self.extension_duration.setValue(3)
        param_row.addWidget(self.extension_duration)
        param_row.addStretch(1)
        panel_layout.addLayout(param_row)

        button_row = QHBoxLayout()
        apply_btn = action_button("应用参数")
        apply_btn.clicked.connect(self._apply_glove_params)
        start_btn = action_button("开始", primary=True)
        start_btn.clicked.connect(lambda: self._submit_glove("start", {"confirm": True}))
        pause_btn = action_button("暂停")
        pause_btn.clicked.connect(lambda: self._submit_glove("pause", {}))
        poweroff_btn = QPushButton("软关机")
        poweroff_btn.setProperty("variant", "danger")
        poweroff_btn.clicked.connect(lambda: self._submit_glove("poweroff", {"confirm": True}))
        button_row.addWidget(apply_btn)
        button_row.addWidget(start_btn)
        button_row.addWidget(pause_btn)
        button_row.addWidget(poweroff_btn)
        button_row.addStretch(1)
        panel_layout.addLayout(button_row)

        self.root.addWidget(panel)
        self.glove_panel = panel

    def _selected_fingers(self) -> list[str]:
        return ["thumb", self.finger_combo.currentData()]

    def _apply_glove_params(self) -> None:
        self._submit_glove("mode", {"mode": self.glove_mode.currentData()})
        self._submit_glove("fingers", {"selected": self._selected_fingers()})
        self._submit_glove(
            "durations",
            {"flexion": self.flexion_duration.value(), "extension": self.extension_duration.value()},
        )
        self._submit_glove(
            "forces",
            {"flexion": self.flexion_force.value(), "extension": self.extension_force.value()},
        )

    def _submit_glove(self, action: str, payload: dict[str, Any]) -> None:
        command = GloveCommand(
            command_id=f"manual:{action}",
            action=action,
            trajectory_profile="manual",
            assist_level=0.0,
            hold_ms=0,
            lease_id="manual",
            payload=payload,
        )
        self.worker.submit("command_one", kind="glove", command=command)

    def connect_all(self) -> None:
        if self.profile is None:
            QMessageBox.warning(self, "缺少连接档案", "请先到设备设置页创建或选择连接档案。")
            return
        self.connect_button.setEnabled(False)
        self.connect_button.setText("正在依次检查…")
        for card in self.cards.values():
            card.set_connection("connecting", "正在进行只读连接检查")
        self.worker.submit("connect_all", devices=self.profile["devices"])

    def apply_state(self, snapshot: dict[str, Any]) -> None:
        devices = snapshot.get("devices", {})
        for kind, card in self.cards.items():
            slot = devices.get(kind)
            if slot:
                card.set_connection(slot["state"], slot["health"]["reason"])
        # 连接检查只要求「已连接、未故障」；真实设备信号可能尚未稳定（DEGRADED），
        # 由标定页进一步确认个体信号，而不是在这里卡死流程。
        connected_states = {"data_valid", "degraded"}
        self._all_ready = bool(devices) and all(
            devices.get(kind, {}).get("state") in connected_states for kind in self.cards
        )
        self.next_button.setEnabled(self._all_ready)
        if self._all_ready:
            self.result_status.set_status("3 / 3 已就绪", "good")
            self.result_text.setText("连接层检查完成。请进入标定确认个体信号是否可用于本次会话。")

    def _work_completed(self, action: str, payload: object) -> None:
        if action == "connect_all":
            self.connect_button.setText("重新检查全部")
            self.connect_button.setEnabled(True)
            self.worker.submit("preview_all")
        elif action == "preview_all" and isinstance(payload, dict):
            for kind, preview in payload.items():
                if kind in self.cards:
                    self.cards[kind].apply_preview(preview)
        elif action == "command_one":
            if payload is not None and getattr(payload, "ok", True) is False:
                self.result_status.set_status("命令失败", "bad")
                self.result_text.setText(str(getattr(payload, "fault_code", None) or "命令失败"))

    def _work_failed(self, action: str, message: str) -> None:
        if action == "command_one":
            self.result_status.set_status("命令失败", "bad")
            self.result_text.setText(message)
            return
        if action not in {"connect_all", "preview_all"}:
            return
        self.connect_button.setText("重新检查全部")
        self.connect_button.setEnabled(True)
        self.result_status.set_status("检查未通过", "bad")
        self.result_text.setText(message)


class CalibrationPage(BasePage):
    completed = Signal()

    def __init__(self) -> None:
        super().__init__()
        self._step = 0
        self._allowed = False
        self.timer = QTimer(self)
        self.timer.setInterval(650)
        self.timer.timeout.connect(self._advance)
        self.root.addWidget(
            PageTitle(
                "步骤 03 / 06",
                "个体化基线与意图标定",
                "先建立静息参考，再检查提示后的运动想象特征；当前版本只模拟流程，不生成患者模型。",
            )
        )
        warning = Card("simulationCard")
        warning_layout = QHBoxLayout(warning)
        warning_layout.setContentsMargins(18, 14, 18, 14)
        warning_layout.addWidget(StatusPill("模拟标定", "simulation"))
        warning_text = QLabel("用于验证页面、事件顺序和状态转换，不可作为 EEG 有效性结论。")
        warning_text.setWordWrap(True)
        warning_layout.addWidget(warning_text, 1)
        self.root.addWidget(warning)

        content = QGridLayout()
        task_card = Card()
        task_layout = QVBoxLayout(task_card)
        task_layout.setContentsMargins(24, 22, 24, 22)
        self.stage_label = QLabel("等待设备检查")
        self.stage_label.setObjectName("largeStage")
        self.instruction_label = QLabel("设备通过后，点击开始模拟标定。")
        self.instruction_label.setObjectName("pageDescription")
        self.instruction_label.setWordWrap(True)
        self.progress_label = QLabel("0 / 5")
        self.progress_label.setObjectName("calibrationCount")
        self.start_button = action_button("开始模拟标定", primary=True)
        self.start_button.setEnabled(False)
        self.start_button.clicked.connect(self.start)
        task_layout.addWidget(self.stage_label)
        task_layout.addWidget(self.instruction_label)
        task_layout.addStretch(1)
        task_layout.addWidget(self.progress_label)
        task_layout.addWidget(self.start_button)
        self.eeg_plot = SignalPlot("标定期 EEG 预览")
        content.addWidget(task_card, 0, 0)
        content.addWidget(self.eeg_plot, 0, 1)
        content.setColumnStretch(0, 2)
        content.setColumnStretch(1, 3)
        self.root.addLayout(content)
        self.root.addStretch(1)

    def set_allowed(self, allowed: bool) -> None:
        self._allowed = allowed
        self.start_button.setEnabled(allowed and not self.timer.isActive())
        if allowed:
            self.stage_label.setText("准备就绪")
            self.instruction_label.setText("确认对象保持舒适坐姿，按提示完成静息与运动想象。")

    def start(self) -> None:
        if not self._allowed:
            return
        self._step = 0
        self.start_button.setEnabled(False)
        self.timer.start()
        self._advance()

    def _advance(self) -> None:
        stages = [
            ("静息基线", "保持放松，不进行实际手部动作。"),
            ("任务提示", "观察即将进行的手部屈伸任务。"),
            ("运动想象", "想象患侧手完成提示动作。"),
            ("质量检查", "检查伪迹、信号质量和事件时间。"),
            ("标定完成", "已生成仅供软件联调的模拟会话状态。"),
        ]
        if self._step >= len(stages):
            self.timer.stop()
            self.progress_label.setText("5 / 5")
            self.completed.emit()
            return
        title, instruction = stages[self._step]
        self.stage_label.setText(title)
        self.instruction_label.setText(instruction)
        self.progress_label.setText(f"{self._step + 1} / 5")
        samples = [((index + self._step * 7) % 29 - 14) * 0.7 for index in range(180)]
        self.eeg_plot.set_samples(samples, 250, "模拟")
        self._step += 1


class TrainingPage(BasePage):
    start_requested = Signal()
    pause_requested = Signal(bool)
    repetition_completed = Signal()
    finish_requested = Signal(str)

    PHASE_DISPLAY: ClassVar[dict[str, tuple[str, str, str, str]]] = {
        "rest_baseline": ("静息基线", "等待", "等待", "采集动作前参考"),
        "cue": ("任务提示", "待判断", "静息", "呈现屈伸方向"),
        "intent_window": ("意图等待", "检测中", "可能活动", "只分析运动前 EEG"),
        "intent_frozen": ("意图冻结", "已冻结", "静息", "冻结本试次意图"),
        "safety_check": ("安全检查", "已冻结", "静息", "检查辅助命令是否安全"),
        "assist": ("辅助运动", "已冻结", "响应观察", "手套执行辅助"),
        "hold": ("保持", "不再更新", "持续观察", "记录运动中响应"),
        "release_recovery": ("释放恢复", "本试次完成", "恢复观察", "记录动作后窗口"),
        "completed": ("试次完成", "—", "—", "本试次结束"),
    }

    HAND_POSE: ClassVar[dict[str, tuple[float, float, str, str]]] = {
        "rest_baseline": (0.0, 0.0, "已释放", "静息期开放姿态"),
        "cue": (0.0, 0.0, "等待提示", "尚未形成辅助目标"),
        "intent_window": (0.05, 0.0, "意图等待", "只分析运动前 EEG；未发送动作"),
        "intent_frozen": (0.05, 0.0, "意图冻结", "意图已冻结"),
        "safety_check": (0.05, 0.0, "安全检查", "检查安全条件"),
        "assist": (0.42, 0.86, "辅助运动", "目标与当前姿态分层显示"),
        "hold": (0.82, 0.86, "接近到位", "保持辅助"),
        "release_recovery": (0.24, 0.0, "释放恢复", "目标已开放，当前姿态正在返回"),
        "completed": (0.0, 0.0, "已释放", "试次完成"),
    }

    def __init__(self, worker: DeviceWorker) -> None:
        super().__init__()
        self.worker = worker
        self._target = 10
        self._repetitions = 0
        self._running = False
        self._data_root = "data/sessions"
        self.root.addWidget(
            PageTitle(
                "步骤 04—05 / 06",
                "康复训练与结束恢复",
                "当前试次的 EEG 意图在实际运动开始前冻结；运动中和运动后的信号只用于效果观察与后续调整。",
            )
        )
        banner = Card("simulationCard")
        banner_layout = QHBoxLayout(banner)
        banner_layout.setContentsMargins(18, 14, 18, 14)
        banner_layout.addWidget(StatusPill("实时运行", "simulation"))
        self.mode_label = QLabel("由连接档案决定模拟或真实设备；动作命令经安全监督器下发。")
        self.mode_label.setWordWrap(True)
        banner_layout.addWidget(self.mode_label, 1)
        self.root.addWidget(banner)

        metrics = QGridLayout()
        self.stage_metric = MetricCard("当前环节", "尚未开始", "等待完成个体标定")
        self.intent_metric = MetricCard("意图判断", "—", "仅使用运动前 EEG 窗口")
        self.response_metric = MetricCard("肌电响应", "—", "单通道局部活动，不判断屈肌/伸肌")
        self.count_metric = MetricCard("完成次数", "0 / 10", "每次动作均保存事件时间")
        metrics.addWidget(self.stage_metric, 0, 0)
        metrics.addWidget(self.intent_metric, 0, 1)
        metrics.addWidget(self.response_metric, 0, 2)
        metrics.addWidget(self.count_metric, 0, 3)
        self.root.addLayout(metrics)

        plots = QGridLayout()
        self.eeg_plot = SignalPlot("EEG · 运动前意图窗口", "#0B8175")
        self.emg_plot = SignalPlot("sEMG · 辅助响应窗口", "#B2762C")
        self.virtual_hand = ParticleHandCard("P03-E 三维粒子手")
        for training_card in (self.eeg_plot, self.emg_plot, self.virtual_hand):
            training_card.setFixedHeight(330)
        plots.addWidget(self.eeg_plot, 0, 0)
        plots.addWidget(self.emg_plot, 0, 1)
        plots.addWidget(self.virtual_hand, 0, 2)
        plots.setColumnStretch(0, 3)
        plots.setColumnStretch(1, 3)
        plots.setColumnStretch(2, 3)

        controls = Card("toolbarCard")
        controls_layout = QHBoxLayout(controls)
        controls_layout.setContentsMargins(18, 14, 18, 14)
        self.readiness = QLabel("完成设备检查和个体标定后可开始")
        self.readiness.setObjectName("toolbarTitle")
        self.start_button = action_button("开始训练", primary=True)
        self.start_button.setEnabled(False)
        self.start_button.clicked.connect(self.start_requested)
        self.pause_button = action_button("暂停")
        self.pause_button.setEnabled(False)
        self.pause_button.clicked.connect(self._toggle_pause)
        self.end_button = QPushButton("结束本次训练")
        self.end_button.setProperty("variant", "danger")
        self.end_button.setEnabled(False)
        self.end_button.clicked.connect(lambda: self.finish_requested.emit("操作者结束训练"))
        controls_layout.addWidget(self.readiness, 1)
        controls_layout.addWidget(self.start_button)
        controls_layout.addWidget(self.pause_button)
        controls_layout.addWidget(self.end_button)
        self.root.addWidget(controls)
        self.root.addLayout(plots)
        self.root.addStretch(1)

        worker.runtime_event.connect(self._on_runtime_event)
        worker.completed.connect(self._on_worker_completed)

    def set_data_root(self, data_root: Any) -> None:
        self._data_root = str(data_root)

    def configure(self, context: dict[str, Any], ready: bool) -> None:
        self._target = int(context.get("target_repetitions", 10))
        self.virtual_hand.set_side(str(context.get("affected_side", "右侧")))
        self.virtual_hand.set_pose(0.0, 0.0, "已释放", "开放姿态；不是手指角度测量")
        self.count_metric.set_value(f"0 / {self._target}")
        self.start_button.setEnabled(ready and not self._running)
        self.readiness.setText("标定完成，可以开始训练" if ready else "尚未满足训练条件")

    def begin_runtime(self) -> None:
        self._repetitions = 0
        self._running = True
        self.start_button.setEnabled(False)
        self.pause_button.setEnabled(True)
        self.end_button.setEnabled(True)
        self.count_metric.set_value(f"0 / {self._target}")
        self.worker.submit(
            "start_session",
            session_id=f"session-{uuid.uuid4().hex[:12]}",
            data_root=self._data_root,
            metadata={"protocol": "recoverhand-training"},
            target_repetitions=self._target,
        )

    def set_paused(self, paused: bool) -> None:
        if paused:
            self.pause_button.setText("继续")
            self.stage_metric.set_value("已暂停", "运行时级暂停尚未实现；请用「结束训练」")
        else:
            self.pause_button.setText("暂停")

    def stop_runtime(self) -> None:
        self.worker.submit("stop_session")
        self._running = False
        self.pause_button.setEnabled(False)
        self.end_button.setEnabled(False)
        self.virtual_hand.set_pose(0.0, 0.0, "已释放", "训练结束后的释放姿态")

    def shutdown(self) -> None:
        self.virtual_hand.shutdown()

    def _toggle_pause(self) -> None:
        self.pause_requested.emit(True)

    def _on_runtime_event(self, event: dict[str, Any]) -> None:
        name = event.get("name")
        data = event.get("data") or {}
        if name == "trial.phase_changed":
            phase = data.get("current")
            display = self.PHASE_DISPLAY.get(phase)
            if display:
                stage, intent, response, detail = display
                self.stage_metric.set_value(stage, detail)
                self.intent_metric.set_value(intent)
                self.response_metric.set_value(response)
            pose = self.HAND_POSE.get(phase, (0.0, 0.0, "—", ""))
            actual, target, hand_state, mapping = pose
            self.virtual_hand.set_pose(actual, target, hand_state, f"{mapping}；不是手指角度测量")
        elif name == "intent.frozen":
            state = data.get("state", "uncertain")
            label = {"left": "左侧", "right": "右侧", "uncertain": "不确定"}.get(state, state)
            self.intent_metric.set_value(label, f"抓握量 {float(data.get('grip', 0.0)):.2f}")
        elif name == "data.eeg":
            samples = data.get("samples")
            if samples:
                self.eeg_plot.set_samples(list(samples[0]), data.get("sample_rate", 250), "真实 EEG")
        elif name == "data.emg":
            samples = data.get("samples")
            if samples:
                self.emg_plot.set_samples(list(samples[0]), data.get("sample_rate", 500), "真实 sEMG")
        elif name == "trial.completed":
            self._repetitions += 1
            self.count_metric.set_value(f"{self._repetitions} / {self._target}")
            self.repetition_completed.emit()
            if self._repetitions >= self._target:
                self.finish_requested.emit("达到设定重复次数")

    def _on_worker_completed(self, action: str, payload: object) -> None:
        if action == "session_finished" and self._running:
            self._running = False
            self.finish_requested.emit("会话结束")


class ReportPage(BasePage):
    completed = Signal()

    def __init__(self) -> None:
        super().__init__()
        self.root.addWidget(PageTitle("步骤 06 / 06", "训练记录与人工复核", "报告区分观察结果、算法输出和临床结论。"))
        summary = QGridLayout()
        self.patient = MetricCard("患者/研究对象", "—")
        self.side = MetricCard("患侧", "—")
        self.repetitions = MetricCard("完成次数", "—")
        self.mode = MetricCard("数据性质", "模拟")
        summary.addWidget(self.patient, 0, 0)
        summary.addWidget(self.side, 0, 1)
        summary.addWidget(self.repetitions, 0, 2)
        summary.addWidget(self.mode, 0, 3)
        self.root.addLayout(summary)

        interpretation = Card()
        layout = QVBoxLayout(interpretation)
        layout.setContentsMargins(24, 22, 24, 22)
        heading = QLabel("本次记录说明")
        heading.setObjectName("cardTitle")
        self.report_text = QLabel("尚无已完成会话。")
        self.report_text.setWordWrap(True)
        self.report_text.setObjectName("reportText")
        layout.addWidget(heading)
        layout.addWidget(self.report_text)
        self.root.addWidget(interpretation)
        finish = action_button("复核完成，返回首页", primary=True)
        finish.clicked.connect(self.completed)
        self.root.addWidget(finish, alignment=Qt.AlignmentFlag.AlignRight)
        self.root.addStretch(1)

    def set_context(self, context: dict[str, Any]) -> None:
        self.patient.set_value(context.get("patient_name") or "—", context.get("patient_code") or "未填写档案编号")
        self.side.set_value(context.get("affected_side") or "—")
        done = int(context.get("completed_repetitions", 0))
        target = int(context.get("target_repetitions", 0))
        self.repetitions.set_value(f"{done} / {target}")
        self.mode.set_value("模拟流程" if context.get("simulation", True) else "真实设备")
        self.report_text.setText(
            "本次记录来自研发模拟信号，只证明桌面流程、事件顺序和页面联动能够运行。"
            "不能据此评价患者意图识别能力、肌肉募集变化或康复效果。进入真实设备阶段后，"
            "此处将展示信号质量、试次有效率、动作前后 sEMG 指标、手套状态和需要人工复核的异常。"
        )


class SettingsPage(BasePage):
    profile_saved = Signal(object)

    def __init__(self, registry: DriverRegistry, store: ProfileStore) -> None:
        super().__init__()
        self.registry = registry
        self.store = store
        self.validator = DeviceManager(registry)
        self._profile_id: str | None = None
        self._locked = False
        self.driver_combos: dict[DeviceKind, QComboBox] = {}
        self.form_layouts: dict[DeviceKind, QFormLayout] = {}
        self.config_widgets: dict[DeviceKind, dict[str, QWidget]] = {}
        self.root.addWidget(
            PageTitle(
                "系统设置 / 设备连接档案",
                "设备设置与患者训练分离",
                "在这里选择驱动和连接参数；回到设备检查页后才执行连接。训练进行时配置自动锁定。",
            )
        )
        toolbar = Card("toolbarCard")
        toolbar_layout = QHBoxLayout(toolbar)
        toolbar_layout.setContentsMargins(18, 14, 18, 14)
        toolbar_layout.addWidget(QLabel("连接档案"))
        self.profile_combo = QComboBox()
        self.profile_combo.setMinimumWidth(240)
        self.profile_combo.currentIndexChanged.connect(self._profile_selected)
        self.profile_name = QLineEdit()
        self.profile_name.setPlaceholderText("档案名称")
        new_button = action_button("新建档案")
        new_button.clicked.connect(self.new_profile)
        self.save_button = action_button("保存档案", primary=True)
        self.save_button.clicked.connect(self.save_profile)
        toolbar_layout.addWidget(self.profile_combo)
        toolbar_layout.addWidget(self.profile_name, 1)
        toolbar_layout.addWidget(new_button)
        toolbar_layout.addWidget(self.save_button)
        self.root.addWidget(toolbar)

        grid = QGridLayout()
        labels = {
            DeviceKind.EEG: ("01", "EEG", "脑电设备驱动"),
            DeviceKind.EMG: ("02", "sEMG", "单通道双电极贴片"),
            DeviceKind.GLOVE: ("03", "Glove", "辅助手套执行设备"),
        }
        for column, kind in enumerate(DeviceKind):
            number, short, title = labels[kind]
            card = Card()
            layout = QVBoxLayout(card)
            layout.setContentsMargins(18, 17, 18, 17)
            header = QHBoxLayout()
            index = QLabel(number)
            index.setObjectName("deviceNumber")
            title_box = QVBoxLayout()
            eyebrow = QLabel(short)
            eyebrow.setObjectName("eyebrow")
            heading = QLabel(title)
            heading.setObjectName("cardTitle")
            title_box.addWidget(eyebrow)
            title_box.addWidget(heading)
            header.addWidget(index)
            header.addLayout(title_box)
            header.addStretch(1)
            layout.addLayout(header)
            combo = QComboBox()
            combo.setObjectName(f"{kind.value}DriverCombo")
            for info in registry.list(kind):
                suffix = "" if info.available else "（待接入）"
                combo.addItem(info.display_name + suffix, info.id)
                if not info.available:
                    combo.model().item(combo.count() - 1).setEnabled(False)
            combo.currentIndexChanged.connect(lambda _index, current_kind=kind: self._driver_changed(current_kind))
            layout.addWidget(combo)
            form_widget = QWidget()
            form = QFormLayout(form_widget)
            form.setContentsMargins(0, 8, 0, 0)
            form.setVerticalSpacing(12)
            layout.addWidget(form_widget)
            layout.addStretch(1)
            self.driver_combos[kind] = combo
            self.form_layouts[kind] = form
            self.config_widgets[kind] = {}
            grid.addWidget(card, 0, column)
        self.root.addLayout(grid)

        note = Card("noticeCard")
        note_layout = QVBoxLayout(note)
        note_layout.setContentsMargins(18, 15, 18, 15)
        note_layout.addWidget(QLabel("设置页安全边界"))
        note_text = QLabel(
            "保存档案不会自动连接设备，也不会启动手套。现有 ESP32 HTTP 驱动只读 /api/status；"
            "真实运动测试必须进入独立维护模式并确认手套未佩戴。"
        )
        note_text.setObjectName("mutedText")
        note_text.setWordWrap(True)
        note_layout.addWidget(note_text)
        self.root.addWidget(note)
        self.root.addStretch(1)
        self.reload_profiles()

    def set_locked(self, locked: bool) -> None:
        self._locked = locked
        self.profile_combo.setEnabled(not locked)
        self.profile_name.setEnabled(not locked)
        self.save_button.setEnabled(not locked)
        for combo in self.driver_combos.values():
            combo.setEnabled(not locked)
        for widgets in self.config_widgets.values():
            for widget in widgets.values():
                widget.setEnabled(not locked)

    def reload_profiles(self, selected_id: str | None = None) -> None:
        profiles = self.store.list()
        self.profile_combo.blockSignals(True)
        self.profile_combo.clear()
        for profile in profiles:
            self.profile_combo.addItem(profile["name"], profile["id"])
        self.profile_combo.blockSignals(False)
        if profiles:
            target = selected_id or profiles[0]["id"]
            index = self.profile_combo.findData(target)
            self.profile_combo.setCurrentIndex(max(index, 0))
            self.load_profile(self.store.get(self.profile_combo.currentData()))
        else:
            self.new_profile()

    def current_profile(self) -> dict[str, Any] | None:
        if self._profile_id is None:
            return None
        return self.store.get(self._profile_id)

    def new_profile(self) -> None:
        if self._locked:
            return
        self._profile_id = None
        self.profile_name.setText("新连接档案")
        for kind, combo in self.driver_combos.items():
            first_available = next(
                (index for index, info in enumerate(self.registry.list(kind)) if info.available),
                0,
            )
            combo.setCurrentIndex(first_available)
            self._driver_changed(kind)

    def load_profile(self, profile: dict[str, Any]) -> None:
        self._profile_id = profile["id"]
        self.profile_name.setText(profile["name"])
        for kind in DeviceKind:
            entry = profile["devices"].get(kind.value, {})
            combo = self.driver_combos[kind]
            index = combo.findData(entry.get("driver_id"))
            if index >= 0:
                combo.blockSignals(True)
                combo.setCurrentIndex(index)
                combo.blockSignals(False)
            self._driver_changed(kind, entry.get("config", {}))

    def _profile_selected(self, index: int) -> None:
        if index >= 0 and self.profile_combo.currentData():
            self.load_profile(self.store.get(self.profile_combo.currentData()))

    def _clear_form(self, form: QFormLayout) -> None:
        while form.rowCount():
            form.removeRow(0)

    def _driver_changed(self, kind: DeviceKind, values: dict[str, Any] | None = None) -> None:
        combo = self.driver_combos[kind]
        driver_id = combo.currentData()
        if not driver_id:
            return
        info = self.registry.info(driver_id)
        form = self.form_layouts[kind]
        self._clear_form(form)
        widgets: dict[str, QWidget] = {}
        values = values or {}
        for key, schema in info.config_schema.get("properties", {}).items():
            value = values.get(key, schema.get("default", ""))
            field_type = schema.get("type")
            if field_type == "boolean":
                widget: QWidget = QCheckBox("开启")
                widget.setChecked(bool(value))
            elif field_type == "integer":
                spin = QSpinBox()
                spin.setRange(int(schema.get("minimum", -1_000_000)), int(schema.get("maximum", 1_000_000)))
                spin.setValue(int(value or 0))
                widget = spin
            elif field_type == "number":
                decimal = QDoubleSpinBox()
                decimal.setDecimals(2)
                decimal.setRange(float(schema.get("minimum", -1_000_000)), float(schema.get("maximum", 1_000_000)))
                decimal.setValue(float(value or 0))
                widget = decimal
            else:
                line = QLineEdit(str(value))
                widget = line
            widget.setEnabled(not self._locked and info.available)
            widgets[key] = widget
            form.addRow(schema.get("title", key), widget)
        description = QLabel(info.description if info.available else info.unavailable_reason or "驱动不可用")
        description.setObjectName("mutedText")
        description.setWordWrap(True)
        form.addRow(description)
        self.config_widgets[kind] = widgets

    def _field_value(self, widget: QWidget) -> Any:
        if isinstance(widget, QCheckBox):
            return widget.isChecked()
        if isinstance(widget, QSpinBox):
            return widget.value()
        if isinstance(widget, QDoubleSpinBox):
            return widget.value()
        if isinstance(widget, QLineEdit):
            return widget.text()
        raise TypeError(f"不支持的配置控件: {type(widget).__name__}")

    def collect_devices(self) -> dict[str, Any]:
        devices: dict[str, Any] = {}
        for kind in DeviceKind:
            devices[kind.value] = {
                "driver_id": self.driver_combos[kind].currentData(),
                "config": {key: self._field_value(widget) for key, widget in self.config_widgets[kind].items()},
            }
        return devices

    def save_profile(self) -> None:
        if self._locked:
            return
        name = self.profile_name.text().strip()
        if not name:
            QMessageBox.warning(self, "无法保存", "连接档案名称不能为空。")
            return
        devices = self.collect_devices()
        validation = self.validator.validate_profile(devices)
        if not validation["valid"]:
            QMessageBox.warning(self, "配置不完整", str(validation["errors"]))
            return
        saved = self.store.save(name, devices, self._profile_id)
        self._profile_id = saved["id"]
        self.reload_profiles(saved["id"])
        self.profile_saved.emit(saved)
