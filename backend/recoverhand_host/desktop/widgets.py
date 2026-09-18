from __future__ import annotations

from typing import Any

import pyqtgraph as pg
from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QFrame,
    QHBoxLayout,
    QLabel,
    QProgressBar,
    QVBoxLayout,
    QWidget,
)

from .virtual_hand import PoseInput, VirtualHandView


def refresh_style(widget: QWidget) -> None:
    widget.style().unpolish(widget)
    widget.style().polish(widget)
    widget.update()


class StatusPill(QLabel):
    def __init__(self, text: str = "未配置", tone: str = "quiet") -> None:
        super().__init__(text)
        self.setObjectName("statusPill")
        self.set_tone(tone)
        self.setAlignment(Qt.AlignmentFlag.AlignCenter)

    def set_status(self, text: str, tone: str) -> None:
        self.setText(text)
        self.set_tone(tone)

    def set_tone(self, tone: str) -> None:
        self.setProperty("tone", tone)
        refresh_style(self)


class PageTitle(QWidget):
    def __init__(self, step: str, title: str, description: str) -> None:
        super().__init__()
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(7)
        eyebrow = QLabel(step)
        eyebrow.setObjectName("eyebrow")
        heading = QLabel(title)
        heading.setObjectName("pageTitle")
        body = QLabel(description)
        body.setObjectName("pageDescription")
        body.setWordWrap(True)
        layout.addWidget(eyebrow)
        layout.addWidget(heading)
        layout.addWidget(body)


class Card(QFrame):
    def __init__(self, object_name: str = "card") -> None:
        super().__init__()
        self.setObjectName(object_name)
        self.setFrameShape(QFrame.Shape.NoFrame)


class MetricCard(Card):
    def __init__(self, label: str, value: str, detail: str = "") -> None:
        super().__init__("metricCard")
        layout = QVBoxLayout(self)
        layout.setContentsMargins(18, 16, 18, 16)
        layout.setSpacing(5)
        caption = QLabel(label)
        caption.setObjectName("metricLabel")
        self.value_label = QLabel(value)
        self.value_label.setObjectName("metricValue")
        self.detail_label = QLabel(detail)
        self.detail_label.setObjectName("metricDetail")
        self.detail_label.setWordWrap(True)
        layout.addWidget(caption)
        layout.addWidget(self.value_label)
        layout.addWidget(self.detail_label)

    def set_value(self, value: str, detail: str | None = None) -> None:
        self.value_label.setText(value)
        if detail is not None:
            self.detail_label.setText(detail)


class SignalPlot(Card):
    def __init__(self, title: str, color: str = "#0B8175") -> None:
        super().__init__("plotCard")
        layout = QVBoxLayout(self)
        layout.setContentsMargins(14, 12, 14, 12)
        layout.setSpacing(7)
        header = QHBoxLayout()
        self.title_label = QLabel(title)
        self.title_label.setObjectName("plotTitle")
        self.meta_label = QLabel("等待数据")
        self.meta_label.setObjectName("plotMeta")
        header.addWidget(self.title_label)
        header.addStretch(1)
        header.addWidget(self.meta_label)
        self.plot = pg.PlotWidget(background="transparent")
        self.plot.setMinimumHeight(135)
        self.plot.setMouseEnabled(x=False, y=False)
        self.plot.hideButtons()
        self.plot.showGrid(x=False, y=True, alpha=0.12)
        self.plot.getPlotItem().hideAxis("left")
        self.plot.getPlotItem().hideAxis("bottom")
        self.curve = self.plot.plot(pen=pg.mkPen(color=color, width=1.7))
        layout.addLayout(header)
        layout.addWidget(self.plot)

    def set_samples(self, samples: list[float], sample_rate: float, meta: str = "") -> None:
        self.curve.setData(samples)
        suffix = f" · {meta}" if meta else ""
        self.meta_label.setText(f"{sample_rate:g} Hz{suffix}")


class VirtualHandCard(Card):
    def __init__(self, title: str = "数字手镜像", mapping: str = "等待姿态数据") -> None:
        super().__init__("plotCard")
        layout = QVBoxLayout(self)
        layout.setContentsMargins(14, 12, 14, 12)
        layout.setSpacing(7)
        header = QHBoxLayout()
        title_label = QLabel(title)
        title_label.setObjectName("plotTitle")
        self.status = StatusPill("等待数据", "quiet")
        header.addWidget(title_label)
        header.addStretch(1)
        header.addWidget(self.status)
        self.hand = VirtualHandView()
        self.mapping_label = QLabel(mapping)
        self.mapping_label.setObjectName("handMapping")
        self.mapping_label.setWordWrap(True)
        legend = QLabel("实线：当前映射　╍╍ 目标姿态")
        legend.setObjectName("handLegend")
        layout.addLayout(header)
        layout.addWidget(self.hand, 1)
        layout.addWidget(legend)
        layout.addWidget(self.mapping_label)

    def set_side(self, side: str) -> None:
        self.hand.set_side(side)

    def set_pose(self, actual: PoseInput, target: PoseInput, state: str, mapping: str) -> None:
        self.hand.set_pose(actual, target)
        self.status.set_status(state, "good" if state in {"到位", "已释放"} else "working")
        self.mapping_label.setText(mapping)

    def set_unavailable(self, reason: str) -> None:
        self.hand.set_unavailable()
        self.status.set_status("无姿态", "quiet")
        self.mapping_label.setText(reason)


class DeviceStatusCard(Card):
    def __init__(
        self,
        index: str,
        eyebrow: str,
        title: str,
        description: str,
        with_plot: bool,
        with_hand: bool = False,
    ) -> None:
        super().__init__()
        layout = QVBoxLayout(self)
        layout.setContentsMargins(18, 17, 18, 17)
        layout.setSpacing(12)
        header = QHBoxLayout()
        number = QLabel(index)
        number.setObjectName("deviceNumber")
        titles = QVBoxLayout()
        titles.setSpacing(2)
        small = QLabel(eyebrow)
        small.setObjectName("eyebrow")
        heading = QLabel(title)
        heading.setObjectName("cardTitle")
        titles.addWidget(small)
        titles.addWidget(heading)
        self.status = StatusPill()
        header.addWidget(number)
        header.addLayout(titles)
        header.addStretch(1)
        header.addWidget(self.status)
        self.description = QLabel(description)
        self.description.setObjectName("mutedText")
        self.description.setWordWrap(True)
        self.quality = QProgressBar()
        self.quality.setRange(0, 100)
        self.quality.setValue(0)
        self.quality.setFormat("等待检查")
        layout.addLayout(header)
        layout.addWidget(self.description)
        layout.addWidget(self.quality)
        self.signal_plot = SignalPlot("信号预览") if with_plot else None
        if self.signal_plot is not None:
            layout.addWidget(self.signal_plot)
        self.hand_preview = VirtualHandCard("数字手镜像") if with_hand else None
        if self.hand_preview is not None:
            self.hand_preview.set_unavailable("设备尚未提供数字手姿态")
            layout.addWidget(self.hand_preview)

    def set_connection(self, state: str, reason: str) -> None:
        labels = {
            "unconfigured": ("未配置", "quiet", 0),
            "connecting": ("检查中", "working", 30),
            "data_valid": ("数据有效", "good", 100),
            "degraded": ("连接降级", "warning", 55),
            "fault": ("需要处理", "bad", 0),
            "disconnected": ("已断开", "quiet", 0),
        }
        text, tone, value = labels.get(state, (state, "quiet", 0))
        self.status.set_status(text, tone)
        self.quality.setValue(value)
        self.quality.setFormat(reason)

    def apply_preview(self, preview: dict[str, Any]) -> None:
        if self.signal_plot is not None and preview.get("samples"):
            samples = preview["samples"][0]
            meta = ""
            if preview.get("signal_quality") is not None:
                meta = f"质量 {float(preview['signal_quality']) * 100:.0f}%"
            self.signal_plot.set_samples(samples, preview.get("sample_rate", 0), meta)
        if preview.get("position") is not None:
            released = "已释放" if preview.get("released") else "状态未知"
            self.description.setText(
                f"执行器位置 {preview['position']} · 目标 {preview.get('target', '—')} · 释放状态：{released}；"
                "未配置拉力传感器"
            )
        if self.hand_preview is not None:
            pose = preview.get("pose")
            if isinstance(pose, dict) and pose.get("actual_flexion") is not None:
                side = pose.get("side")
                if side:
                    self.hand_preview.set_side(str(side))
                self.hand_preview.set_pose(
                    pose["actual_flexion"],
                    pose.get("target_flexion", pose["actual_flexion"]),
                    "已释放" if preview.get("released") else "姿态更新",
                    str(pose.get("mapping", "姿态来源未标注")),
                )
            else:
                self.hand_preview.set_unavailable("设备仅返回执行器状态，尚无可验证的手姿态映射")
