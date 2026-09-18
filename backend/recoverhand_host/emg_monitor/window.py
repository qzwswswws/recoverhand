from __future__ import annotations

import math
from typing import Any

import numpy as np
import pyqtgraph as pg
from PySide6.QtCore import Qt
from PySide6.QtGui import QCloseEvent
from PySide6.QtWidgets import (
    QCheckBox,
    QComboBox,
    QFrame,
    QGridLayout,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QMainWindow,
    QMessageBox,
    QPushButton,
    QVBoxLayout,
    QWidget,
)

from .worker import EmgMonitorWorker


class EmgMonitorWindow(QMainWindow):
    def __init__(self, worker: EmgMonitorWorker | None = None) -> None:
        super().__init__()
        self.setWindowTitle("RecoverHand · 原始肌电监视器")
        self.setMinimumSize(980, 680)
        self.resize(1260, 780)
        self.worker = worker or EmgMonitorWorker()
        self._connected = False
        self._paused = False
        self._latest_preview: dict[str, Any] | None = None
        self._y_center: float | None = None
        self._y_half_span: float | None = None
        self._build_ui()
        self._connect_worker()
        self.worker.start()

    def _build_ui(self) -> None:
        shell = QWidget()
        shell.setObjectName("shell")
        root = QVBoxLayout(shell)
        root.setContentsMargins(28, 24, 28, 24)
        root.setSpacing(16)

        title_row = QHBoxLayout()
        title_box = QVBoxLayout()
        eyebrow = QLabel("RECOVERHAND · DEVICE LAB")
        eyebrow.setObjectName("eyebrow")
        title = QLabel("原始肌电信号监视器")
        title.setObjectName("title")
        subtitle = QLabel("唯理 BLE 单通道贴片 · 250 Hz · 仅用于设备与贴位验证，不进入康复训练判断")
        subtitle.setObjectName("subtitle")
        title_box.addWidget(eyebrow)
        title_box.addWidget(title)
        title_box.addWidget(subtitle)
        self.status = QLabel("等待扫描")
        self.status.setObjectName("statusPill")
        self.status.setProperty("tone", "quiet")
        self.status.setAlignment(Qt.AlignmentFlag.AlignCenter)
        title_row.addLayout(title_box, 1)
        title_row.addWidget(self.status)
        root.addLayout(title_row)

        controls = QFrame()
        controls.setObjectName("card")
        control_layout = QGridLayout(controls)
        control_layout.setContentsMargins(18, 16, 18, 16)
        control_layout.setHorizontalSpacing(12)
        control_layout.setVerticalSpacing(8)
        control_layout.addWidget(QLabel("名称筛选"), 0, 0)
        self.name_filter = QLineEdit("EMG")
        self.name_filter.setPlaceholderText("例如 EMGR-0036")
        control_layout.addWidget(self.name_filter, 1, 0)
        control_layout.addWidget(QLabel("发现的设备"), 0, 1)
        self.devices = QComboBox()
        self.devices.setMinimumWidth(320)
        self.devices.addItem("请先扫描", None)
        control_layout.addWidget(self.devices, 1, 1)
        control_layout.addWidget(QLabel("显示窗口"), 0, 2)
        self.window_seconds = QComboBox()
        for seconds in (1, 2, 4):
            self.window_seconds.addItem(f"{seconds} 秒", seconds)
        self.window_seconds.setCurrentIndex(2)
        self.window_seconds.currentIndexChanged.connect(self._refresh_latest)
        control_layout.addWidget(self.window_seconds, 1, 2)
        self.scan_button = QPushButton("扫描贴片")
        self.scan_button.clicked.connect(self.scan)
        self.connect_button = QPushButton("连接并开始")
        self.connect_button.setObjectName("primaryButton")
        self.connect_button.clicked.connect(self.toggle_connection)
        control_layout.addWidget(self.scan_button, 1, 3)
        control_layout.addWidget(self.connect_button, 1, 4)
        root.addWidget(controls)

        plot_card = QFrame()
        plot_card.setObjectName("card")
        plot_layout = QVBoxLayout(plot_card)
        plot_layout.setContentsMargins(18, 16, 18, 14)
        plot_header = QHBoxLayout()
        plot_title = QLabel("原始差分波形")
        plot_title.setObjectName("sectionTitle")
        self.plot_meta = QLabel("等待数据")
        self.plot_meta.setObjectName("muted")
        self.auto_scale = QCheckBox("平滑自动量程")
        self.auto_scale.setChecked(True)
        self.pause_display = QCheckBox("暂停显示")
        self.pause_display.toggled.connect(self._set_paused)
        plot_header.addWidget(plot_title)
        plot_header.addWidget(self.plot_meta)
        plot_header.addStretch(1)
        plot_header.addWidget(self.auto_scale)
        plot_header.addWidget(self.pause_display)
        plot_layout.addLayout(plot_header)

        self.plot = pg.PlotWidget(background="#101B24")
        self.plot.setMinimumHeight(390)
        self.plot.showGrid(x=True, y=True, alpha=0.16)
        self.plot.setLabel("left", "原始幅值", units="µV")
        self.plot.setLabel("bottom", "相对时间", units="s")
        self.plot.setMouseEnabled(x=False, y=True)
        self.plot.hideButtons()
        self.curve = self.plot.plot(pen=pg.mkPen("#54D6C6", width=1.35))
        self.curve.setClipToView(True)
        self.curve.setDownsampling(auto=True, method="peak")
        plot_layout.addWidget(self.plot)
        root.addWidget(plot_card, 1)

        metrics = QFrame()
        metrics.setObjectName("metricsCard")
        metrics_layout = QGridLayout(metrics)
        metrics_layout.setContentsMargins(18, 14, 18, 14)
        self.metric_values: dict[str, QLabel] = {}
        metric_definitions = (
            ("rms", "窗口 RMS", "— µV"),
            ("peak", "窗口峰值", "— µV"),
            ("battery", "设备电量", "—"),
            ("loss", "通知丢包", "—"),
            ("quality", "传输质量", "—"),
            ("temperature", "设备温度", "—"),
        )
        for column, (key, label, initial) in enumerate(metric_definitions):
            caption = QLabel(label)
            caption.setObjectName("metricCaption")
            value = QLabel(initial)
            value.setObjectName("metricValue")
            metrics_layout.addWidget(caption, 0, column)
            metrics_layout.addWidget(value, 1, column)
            self.metric_values[key] = value
        root.addWidget(metrics)

        self.diagnostics = QLabel(
            "本程序只显示厂家上传的原始单通道数据；不滤波、不识别动作、不保存患者数据。"
        )
        self.diagnostics.setObjectName("notice")
        self.diagnostics.setWordWrap(True)
        root.addWidget(self.diagnostics)
        self.setCentralWidget(shell)

    def _connect_worker(self) -> None:
        self.worker.scan_completed.connect(self._scan_completed)
        self.worker.connection_changed.connect(self._connection_changed)
        self.worker.preview_ready.connect(self._preview_ready)
        self.worker.health_changed.connect(self._health_changed)
        self.worker.failed.connect(self._failed)

    def _set_status(self, text: str, tone: str) -> None:
        self.status.setText(text)
        self.status.setProperty("tone", tone)
        self.status.style().unpolish(self.status)
        self.status.style().polish(self.status)

    def _base_config(self) -> dict[str, Any]:
        return {
            "device_name_filter": self.name_filter.text().strip(),
            "scan_timeout_seconds": 5.0,
            "connect_timeout_seconds": 10.0,
            "stream_start_timeout_seconds": 3.0,
            "preview_seconds": 4.0,
        }

    def scan(self) -> None:
        if self._connected:
            return
        self.scan_button.setEnabled(False)
        self.devices.clear()
        self.devices.addItem("正在扫描…", None)
        self._set_status("正在扫描", "working")
        self.worker.submit("scan", self._base_config())

    def toggle_connection(self) -> None:
        if self._connected:
            self.connect_button.setEnabled(False)
            self._set_status("正在断开", "working")
            self.worker.submit("disconnect")
            return
        identifier = self.devices.currentData()
        if not identifier:
            QMessageBox.information(self, "尚未选择设备", "请先扫描并选择一个唯理肌电贴。")
            return
        config = self._base_config()
        config["device_identifier"] = str(identifier)
        self.connect_button.setEnabled(False)
        self.scan_button.setEnabled(False)
        self._set_status("正在连接", "working")
        self.worker.submit("connect", config)

    def _scan_completed(self, payload: object) -> None:
        devices = list(payload) if isinstance(payload, list) else []
        self.devices.clear()
        for device in devices:
            name = str(device.get("name") or "未知设备")
            identifier = str(device.get("id") or "")
            rssi = device.get("rssi")
            suffix = f" · {rssi} dBm" if rssi is not None else ""
            self.devices.addItem(f"{name} · {identifier}{suffix}", identifier)
        self.scan_button.setEnabled(True)
        self.connect_button.setEnabled(bool(devices))
        if devices:
            self._set_status(f"发现 {len(devices)} 个贴片", "good")
        else:
            self.devices.addItem("未发现匹配设备", None)
            self._set_status("未发现贴片", "warning")

    def _connection_changed(self, connected: bool, reason: str) -> None:
        self._connected = connected
        self.connect_button.setEnabled(True)
        self.connect_button.setText("断开连接" if connected else "连接并开始")
        self.scan_button.setEnabled(not connected)
        self.devices.setEnabled(not connected)
        self.name_filter.setEnabled(not connected)
        self._set_status("数据流有效" if connected else "已断开", "good" if connected else "quiet")
        self.diagnostics.setText(reason)

    def _preview_ready(self, payload: object) -> None:
        if not isinstance(payload, dict):
            return
        self._latest_preview = payload
        self._refresh_latest()

    def _refresh_latest(self) -> None:
        if self._paused or not self._latest_preview:
            return
        preview = self._latest_preview
        channels = preview.get("samples") or []
        if not channels or not channels[0]:
            return
        sample_rate = float(preview.get("sample_rate") or 250.0)
        window_seconds = int(self.window_seconds.currentData() or 4)
        values = np.asarray(channels[0], dtype=float)
        values = values[-int(sample_rate * window_seconds) :]
        x_values = (np.arange(values.size, dtype=float) - max(values.size - 1, 0)) / sample_rate
        self.curve.setData(x_values, values)
        self.plot.setXRange(-window_seconds, 0, padding=0)
        if self.auto_scale.isChecked():
            self._apply_smooth_y_range(values)

        rms = math.sqrt(float(np.mean(np.square(values)))) if values.size else 0.0
        peak = float(np.max(np.abs(values))) if values.size else 0.0
        self.metric_values["rms"].setText(f"{rms:.2f} µV")
        self.metric_values["peak"].setText(f"{peak:.2f} µV")
        battery = preview.get("battery_percent")
        self.metric_values["battery"].setText(f"{battery}%" if battery is not None else "等待状态包")
        self.metric_values["loss"].setText(f"{float(preview.get('packet_loss', 0)) * 100:.3f}%")
        self.metric_values["quality"].setText(f"{float(preview.get('signal_quality', 0)) * 100:.1f}%")
        temperature = preview.get("temperature_c")
        self.metric_values["temperature"].setText(
            f"{float(temperature):.1f} °C" if temperature is not None else "等待状态包"
        )
        self.plot_meta.setText(f"{sample_rate:g} Hz · {values.size} 点 · 原始 µV")
        diagnostics = preview.get("diagnostics") or {}
        self.diagnostics.setText(
            "设备时钟未校准；质量分数仅表示传输连续性。"
            f"通知 {diagnostics.get('received_sequence_packets', 0)}，"
            f"缺失 {diagnostics.get('missing_sequence_packets', 0)}，"
            f"无效 {diagnostics.get('invalid_packets', 0)}，"
            f"队列丢弃 {diagnostics.get('queue_drops', 0)}。"
        )

    def _apply_smooth_y_range(self, values: np.ndarray[Any, np.dtype[np.float64]]) -> None:
        finite = values[np.isfinite(values)]
        if not finite.size:
            return
        target_center = float(np.median(finite))
        target_span = max(10.0, float(np.percentile(np.abs(finite - target_center), 99)) * 1.35)
        if self._y_center is None or self._y_half_span is None:
            self._y_center = target_center
            self._y_half_span = target_span
        else:
            self._y_center = self._y_center * 0.88 + target_center * 0.12
            self._y_half_span = self._y_half_span * 0.88 + target_span * 0.12
        self.plot.setYRange(
            self._y_center - self._y_half_span,
            self._y_center + self._y_half_span,
            padding=0,
        )

    def _set_paused(self, paused: bool) -> None:
        self._paused = paused
        if not paused:
            self._refresh_latest()

    def _health_changed(self, payload: object) -> None:
        if not isinstance(payload, dict) or not self._connected:
            return
        if not payload.get("stream_ok"):
            self._set_status("数据流异常", "bad")
        elif not payload.get("time_sync_ok"):
            self._set_status("数据流有效 · 未校时", "warning")

    def _failed(self, action: str, message: str) -> None:
        self.scan_button.setEnabled(not self._connected)
        self.connect_button.setEnabled(True)
        self._set_status("需要处理", "bad")
        self.diagnostics.setText(message)
        if action in {"scan", "connect"}:
            QMessageBox.warning(self, "肌电设备操作失败", message)

    def closeEvent(self, event: QCloseEvent) -> None:
        self.worker.stop()
        self.worker.wait(8_000)
        event.accept()
