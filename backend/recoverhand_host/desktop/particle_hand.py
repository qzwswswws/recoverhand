from __future__ import annotations

import json
import os
import threading
from functools import partial
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any
from uuid import uuid4

from PySide6.QtCore import Qt, QTimer, QUrl, Signal
from PySide6.QtWidgets import QHBoxLayout, QLabel, QStackedWidget, QVBoxLayout

from .virtual_hand import PoseInput, VirtualHandView, normalize_pose
from .widgets import Card, StatusPill

try:
    from PySide6.QtWebEngineCore import QWebEngineSettings
    from PySide6.QtWebEngineWidgets import QWebEngineView
except ImportError:  # pragma: no cover - 仅用于没有 Qt WebEngine 的降级安装
    QWebEngineSettings = None  # type: ignore[assignment,misc]
    QWebEngineView = None  # type: ignore[assignment,misc]


class _QuietAssetHandler(SimpleHTTPRequestHandler):
    def log_message(self, format: str, *args: object) -> None:
        del format, args


class ParticleAssetServer:
    """只向本机随机端口提供粒子手静态资源。"""

    def __init__(self, asset_dir: Path) -> None:
        self.asset_dir = asset_dir
        self._server: ThreadingHTTPServer | None = None
        self._thread: threading.Thread | None = None

    def start(self) -> QUrl:
        if self._server is None:
            handler = partial(_QuietAssetHandler, directory=str(self.asset_dir))
            self._server = ThreadingHTTPServer(("127.0.0.1", 0), handler)
            self._thread = threading.Thread(
                target=self._server.serve_forever,
                name="recoverhand-particle-assets",
                daemon=True,
            )
            self._thread.start()
        return QUrl(f"http://127.0.0.1:{self._server.server_port}/renderer.html?embed=recoverhand")

    def stop(self) -> None:
        if self._server is None:
            return
        self._server.shutdown()
        self._server.server_close()
        if self._thread is not None:
            self._thread.join(timeout=1.0)
        self._thread = None
        self._server = None


class ParticleHandCard(Card):
    """MIdemo P03-E 粒子手的 Qt 容器，并保留二维无 WebGL 降级显示。"""

    ready_changed = Signal(bool, str)
    frame_presented = Signal(object)

    def __init__(self, title: str = "P03-E 三维粒子手") -> None:
        super().__init__("plotCard")
        self._asset_dir = Path(__file__).resolve().parent / "assets" / "particle_hand"
        self._asset_server = ParticleAssetServer(self._asset_dir)
        self._started = False
        self._ready = False
        self._closed = False
        self._logical_side = "right"
        self._renderer_side = "left"
        self._sequence = 0
        self._latest_frame: dict[str, Any] | None = None

        layout = QVBoxLayout(self)
        layout.setContentsMargins(14, 12, 14, 12)
        layout.setSpacing(7)
        header = QHBoxLayout()
        heading = QLabel(title)
        heading.setObjectName("plotTitle")
        self.status = StatusPill("等待加载", "quiet")
        header.addWidget(heading)
        header.addStretch(1)
        header.addWidget(self.status)
        layout.addLayout(header)

        self.stack = QStackedWidget()
        self.stack.setObjectName("particleHandStack")
        self.stack.setMinimumHeight(190)
        self.fallback = VirtualHandView()
        self.hand = self.fallback
        self.stack.addWidget(self.fallback)
        self.web_view: QWebEngineView | None = None
        can_use_webengine = QWebEngineView is not None and os.environ.get("QT_QPA_PLATFORM") != "offscreen"
        if can_use_webengine:
            self.web_view = QWebEngineView()
            self.web_view.setObjectName("particleHandSurface")
            self.web_view.setMinimumHeight(0)
            self.web_view.setContextMenuPolicy(Qt.ContextMenuPolicy.NoContextMenu)
            self.web_view.setFocusPolicy(Qt.FocusPolicy.NoFocus)
            if QWebEngineSettings is not None:
                settings = self.web_view.settings()
                settings.setAttribute(QWebEngineSettings.WebAttribute.WebGLEnabled, True)
                settings.setAttribute(QWebEngineSettings.WebAttribute.Accelerated2dCanvasEnabled, True)
            self.web_view.loadFinished.connect(self._on_load_finished)
            self.stack.addWidget(self.web_view)
        layout.addWidget(self.stack, 1)

        self.legend = QLabel("粒子手：当前映射姿态　·　目标姿态与来源见下方")
        self.legend.setObjectName("handLegend")
        self.mapping_label = QLabel("尚未收到训练姿态")
        self.mapping_label.setObjectName("handMapping")
        self.mapping_label.setWordWrap(True)
        layout.addWidget(self.legend)
        layout.addWidget(self.mapping_label)

        if self.web_view is None:
            self._degrade("当前环境未启用 Qt WebEngine，使用二维备用显示")

    @property
    def renderer_ready(self) -> bool:
        return self._ready

    def start(self) -> None:
        if self._started or self._closed or self.web_view is None:
            return
        self._started = True
        self.status.set_status("3D加载中", "working")
        self.web_view.setUrl(self._asset_server.start())

    def set_side(self, side: str) -> None:
        self._logical_side = "left" if side in {"左侧", "left"} else "right"
        # P03-E 基础模型在固定正视相机下的视觉手性相反；逻辑患侧不能随之交换。
        self._renderer_side = "right" if self._logical_side == "left" else "left"
        self.fallback.set_side("左侧" if self._logical_side == "left" else "右侧")

    def set_pose(self, actual: PoseInput, target: PoseInput, state: str, mapping: str) -> None:
        actual_pose = normalize_pose(actual)
        target_pose = normalize_pose(target)
        self.fallback.set_pose(actual_pose, target_pose)
        actual_scalar = sum(actual_pose) / 5.0
        target_scalar = sum(target_pose) / 5.0
        self._sequence += 1
        self._latest_frame = {
            "seq": self._sequence,
            "command_id": f"recoverhand-{uuid4()}",
            "hand_side": self._renderer_side,
            "grip_target_01": actual_scalar,
            "wave": 0.0,
            "clarity": 1.12,
            "contact_stiffness": 1.0,
        }
        self.mapping_label.setText(
            f"{state}　·　患侧 {'左' if self._logical_side == 'left' else '右'}　·　"
            f"当前映射 {actual_scalar * 100:.0f}%　·　目标 {target_scalar * 100:.0f}%\n{mapping}"
        )
        self.start()
        if self._ready:
            self._dispatch_latest()

    def _on_load_finished(self, ok: bool) -> None:
        if not ok or self.web_view is None:
            self._degrade("P03-E 页面加载失败，已切换二维备用显示")
            return
        probe = (
            "JSON.stringify({webgl2:!!document.createElement('canvas').getContext('webgl2'),"
            "ready:!!(window.particleHand&&window.particleHand.ready)})"
        )
        self.web_view.page().runJavaScript(probe, self._on_probe_result)

    def _on_probe_result(self, raw: object) -> None:
        try:
            result = json.loads(str(raw))
        except (TypeError, ValueError, json.JSONDecodeError):
            self._degrade("无法读取 P03-E 就绪状态，已切换二维备用显示")
            return
        if not result.get("webgl2") or not result.get("ready") or self.web_view is None:
            self._degrade("WebGL2 或粒子手 API 不可用，已切换二维备用显示")
            return
        install_ack = (
            "window.__recoverHandLastAck=null;"
            "if(!window.__recoverHandAckInstalled){"
            "window.addEventListener('particlehand:presented',e=>{window.__recoverHandLastAck=e.detail;});"
            "window.__recoverHandAckInstalled=true;}"
            "particleHand.setCamera({yaw:-0.45,pitch:-0.25,zoom:12.6,autoOrbit:false});"
        )
        self.web_view.page().runJavaScript(install_ack)
        self._ready = True
        self.stack.setCurrentWidget(self.web_view)
        self.status.set_status("3D就绪", "good")
        self.ready_changed.emit(True, "P03-E WebGL2 已就绪")
        self._dispatch_latest()

    def _dispatch_latest(self) -> None:
        if not self._ready or self.web_view is None or self._latest_frame is None:
            return
        frame = dict(self._latest_frame)
        sequence = int(frame["seq"])
        payload = json.dumps(frame, ensure_ascii=False, separators=(",", ":"))
        self.status.set_status("3D更新中", "working")
        self.web_view.page().runJavaScript(f"particleHand.applyFeedbackFrame({payload});")
        QTimer.singleShot(140, lambda: self._poll_ack(sequence, 0))

    def _poll_ack(self, sequence: int, attempt: int) -> None:
        if not self._ready or self.web_view is None or sequence != self._sequence:
            return
        self.web_view.page().runJavaScript(
            "JSON.stringify(window.__recoverHandLastAck)",
            lambda raw: self._on_ack_result(sequence, attempt, raw),
        )

    def _on_ack_result(self, sequence: int, attempt: int, raw: object) -> None:
        if sequence != self._sequence or not self._ready:
            return
        ack: dict[str, Any] | None = None
        if raw:
            try:
                parsed = json.loads(str(raw))
                if isinstance(parsed, dict):
                    ack = parsed
            except (TypeError, ValueError, json.JSONDecodeError):
                ack = None
        if ack is not None and int(ack.get("seq", -1)) == sequence:
            if ack.get("webgl_context_lost"):
                self._degrade("WebGL 上下文已丢失，已切换二维备用显示")
                return
            applied = float(ack.get("applied_at_performance_ms", 0.0))
            submitted = float(ack.get("render_submitted_at_performance_ms", applied))
            ack["apply_to_render_ms"] = max(0.0, submitted - applied)
            self.status.set_status("3D已绘制", "good")
            self.frame_presented.emit(ack)
            return
        if attempt < 4:
            QTimer.singleShot(140, lambda: self._poll_ack(sequence, attempt + 1))
        else:
            self.status.set_status("绘制回执延迟", "warning")

    def _degrade(self, reason: str) -> None:
        self._ready = False
        self.stack.setCurrentWidget(self.fallback)
        self.status.set_status("二维备用", "warning")
        self.ready_changed.emit(False, reason)

    def shutdown(self) -> None:
        if self._closed:
            return
        self._closed = True
        self._ready = False
        if self.web_view is not None:
            self.web_view.stop()
            self.web_view.setUrl(QUrl("about:blank"))
        self._asset_server.stop()
