from __future__ import annotations

import sys
from pathlib import Path

from PySide6.QtWidgets import QApplication

from .window import EmgMonitorWindow


def main() -> None:
    app = QApplication.instance() or QApplication(sys.argv)
    app.setApplicationName("RecoverHand 原始肌电监视器")
    app.setStyle("Fusion")
    theme_path = Path(__file__).with_name("theme.qss")
    app.setStyleSheet(theme_path.read_text(encoding="utf-8"))
    window = EmgMonitorWindow()
    window.show()
    raise SystemExit(app.exec())
