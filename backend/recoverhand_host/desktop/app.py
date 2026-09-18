from __future__ import annotations

import sys
from pathlib import Path

from PySide6.QtCore import QCoreApplication, Qt
from PySide6.QtGui import QFont
from PySide6.QtWidgets import QApplication

from .main_window import MainWindow


def main() -> int:
    QCoreApplication.setOrganizationName("RecoverHand")
    QCoreApplication.setApplicationName("RecoverHand Host")
    QApplication.setAttribute(Qt.ApplicationAttribute.AA_ShareOpenGLContexts)
    QApplication.setAttribute(Qt.ApplicationAttribute.AA_UseHighDpiPixmaps)
    app = QApplication(sys.argv)
    app.setFont(QFont("Microsoft YaHei UI", 10))
    desktop_dir = Path(__file__).resolve().parent
    app.setStyleSheet((desktop_dir / "theme.qss").read_text(encoding="utf-8"))
    host_app_root = Path(__file__).resolve().parents[3]
    window = MainWindow(host_app_root)
    window.show()
    return app.exec()


if __name__ == "__main__":
    raise SystemExit(main())
