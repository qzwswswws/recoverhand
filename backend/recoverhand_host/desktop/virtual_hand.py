from __future__ import annotations

import math
from collections.abc import Sequence

from PySide6.QtCore import QPointF, QRectF, QSize, Qt, QTimer
from PySide6.QtGui import QColor, QPainter, QPainterPath, QPaintEvent, QPen
from PySide6.QtWidgets import QWidget

PoseInput = float | int | Sequence[float]


def normalize_pose(value: PoseInput) -> tuple[float, float, float, float, float]:
    if isinstance(value, (int, float)):
        values = [float(value)] * 5
    else:
        values = [float(item) for item in value]
    if len(values) != 5:
        raise ValueError("数字手姿态必须是单个屈曲量或五指屈曲量")
    return tuple(max(0.0, min(1.0, item)) for item in values)  # type: ignore[return-value]


class VirtualHandView(QWidget):
    """五指屈曲的二维数字镜像；只呈现来源数据，不推断解剖角度。"""

    def __init__(self) -> None:
        super().__init__()
        self.setMinimumSize(210, 220)
        self._display_pose = [0.0] * 5
        self._actual_pose = (0.0,) * 5
        self._target_pose = (0.0,) * 5
        self._has_pose = False
        self._side = "右侧"
        self._animation = QTimer(self)
        self._animation.setInterval(24)
        self._animation.timeout.connect(self._animate)

    @property
    def actual_pose(self) -> tuple[float, float, float, float, float]:
        return self._actual_pose

    @property
    def target_pose(self) -> tuple[float, float, float, float, float]:
        return self._target_pose

    def sizeHint(self) -> QSize:
        return QSize(250, 250)

    def set_side(self, side: str) -> None:
        self._side = "左侧" if side == "左侧" else "右侧"
        self.update()

    def set_pose(self, actual: PoseInput, target: PoseInput) -> None:
        self._actual_pose = normalize_pose(actual)
        self._target_pose = normalize_pose(target)
        self._has_pose = True
        if not self._animation.isActive():
            self._animation.start()
        self.update()

    def set_unavailable(self) -> None:
        self._has_pose = False
        self._animation.stop()
        self.update()

    def _animate(self) -> None:
        largest_delta = 0.0
        for index, destination in enumerate(self._actual_pose):
            delta = destination - self._display_pose[index]
            largest_delta = max(largest_delta, abs(delta))
            self._display_pose[index] += delta * 0.28
        if largest_delta < 0.003:
            self._display_pose = list(self._actual_pose)
            self._animation.stop()
        self.update()

    def paintEvent(self, event: QPaintEvent) -> None:
        del event
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        bounds = self.rect().adjusted(8, 5, -8, -5)
        scale = min(bounds.width() / 240.0, bounds.height() / 250.0)
        origin_x = bounds.left() + (bounds.width() - 240.0 * scale) / 2.0
        origin_y = bounds.top() + (bounds.height() - 250.0 * scale) / 2.0
        painter.translate(origin_x, origin_y)
        painter.scale(scale, scale)
        if self._side == "左侧":
            painter.translate(240.0, 0.0)
            painter.scale(-1.0, 1.0)

        if self._has_pose:
            self._draw_fingers(painter, self._target_pose, QColor(82, 190, 174, 175), 5.0, dashed=True)
            self._draw_palm(painter)
            self._draw_fingers(painter, self._display_pose, QColor("#0B8175"), 13.0)
        else:
            self._draw_palm(painter, muted=True)
            self._draw_fingers(painter, (0.0,) * 5, QColor("#AFC2BE"), 10.0)

    @staticmethod
    def _draw_palm(painter: QPainter, muted: bool = False) -> None:
        outline = QColor("#9FB7B2") if muted else QColor("#0B8175")
        fill = QColor("#EEF3F2") if muted else QColor("#DDF1ED")
        painter.setPen(QPen(outline, 3.0))
        painter.setBrush(fill)
        palm = QPainterPath()
        palm.addRoundedRect(QRectF(76.0, 105.0, 100.0, 105.0), 24.0, 24.0)
        painter.drawPath(palm)
        painter.drawRoundedRect(QRectF(96.0, 196.0, 60.0, 48.0), 13.0, 13.0)

    def _draw_fingers(
        self,
        painter: QPainter,
        pose: Sequence[float],
        color: QColor,
        width: float,
        dashed: bool = False,
    ) -> None:
        pen = QPen(color, width)
        pen.setCapStyle(Qt.PenCapStyle.RoundCap)
        pen.setJoinStyle(Qt.PenJoinStyle.RoundJoin)
        if dashed:
            pen.setStyle(Qt.PenStyle.DashLine)
        painter.setPen(pen)
        painter.setBrush(Qt.BrushStyle.NoBrush)

        bases = [(94.0, 111.0), (118.0, 106.0), (142.0, 108.0), (164.0, 119.0)]
        lengths = [
            (42.0, 31.0, 24.0),
            (49.0, 36.0, 27.0),
            (46.0, 34.0, 26.0),
            (37.0, 29.0, 23.0),
        ]
        for finger_index, (base, segments) in enumerate(zip(bases, lengths, strict=True), start=1):
            flexion = float(pose[finger_index])
            angles = (
                self._mix(-90.0, -63.0, flexion),
                self._mix(-90.0, -4.0, flexion),
                self._mix(-90.0, 54.0, flexion),
            )
            self._draw_chain(painter, QPointF(*base), segments, angles, color, width, dashed)

        thumb_flexion = float(pose[0])
        thumb_angles = (
            self._mix(-151.0, -78.0, thumb_flexion),
            self._mix(-163.0, -20.0, thumb_flexion),
        )
        self._draw_chain(
            painter,
            QPointF(79.0, 153.0),
            (35.0, 29.0),
            thumb_angles,
            color,
            width,
            dashed,
        )

    @staticmethod
    def _draw_chain(
        painter: QPainter,
        start: QPointF,
        lengths: Sequence[float],
        angles: Sequence[float],
        color: QColor,
        width: float,
        dashed: bool,
    ) -> None:
        point = start
        for length, angle in zip(lengths, angles, strict=True):
            radians = math.radians(angle)
            next_point = QPointF(point.x() + length * math.cos(radians), point.y() + length * math.sin(radians))
            painter.drawLine(point, next_point)
            if not dashed:
                painter.setBrush(color)
                painter.setPen(Qt.PenStyle.NoPen)
                painter.drawEllipse(point, width * 0.36, width * 0.36)
                joint_pen = QPen(color, width)
                joint_pen.setCapStyle(Qt.PenCapStyle.RoundCap)
                painter.setPen(joint_pen)
                painter.setBrush(Qt.BrushStyle.NoBrush)
            point = next_point

    @staticmethod
    def _mix(start: float, end: float, amount: float) -> float:
        return start + (end - start) * amount
