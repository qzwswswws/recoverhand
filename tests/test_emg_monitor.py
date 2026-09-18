import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtCore import QObject, Signal
from PySide6.QtWidgets import QApplication
from recoverhand_host.emg_monitor.window import EmgMonitorWindow


class FakeMonitorWorker(QObject):
    scan_completed = Signal(object)
    connection_changed = Signal(bool, str)
    preview_ready = Signal(object)
    health_changed = Signal(object)
    failed = Signal(str, str)

    def __init__(self) -> None:
        super().__init__()
        self.commands: list[tuple[str, dict]] = []
        self.started = False
        self.stopped = False

    def start(self) -> None:
        self.started = True

    def submit(self, action: str, config: dict | None = None) -> None:
        self.commands.append((action, dict(config or {})))

    def stop(self) -> None:
        self.stopped = True

    def wait(self, _milliseconds: int) -> bool:
        return True


def test_emg_monitor_scans_connects_and_renders_raw_preview() -> None:
    app = QApplication.instance() or QApplication([])
    worker = FakeMonitorWorker()
    window = EmgMonitorWindow(worker=worker)  # type: ignore[arg-type]
    try:
        assert worker.started is True
        window.scan()
        assert worker.commands[-1][0] == "scan"

        worker.scan_completed.emit([{"id": "AA:BB:CC:DD:EE:FF", "name": "EMGR-0036", "rssi": -45}])
        app.processEvents()
        assert window.devices.currentData() == "AA:BB:CC:DD:EE:FF"

        window.toggle_connection()
        action, config = worker.commands[-1]
        assert action == "connect"
        assert config["device_identifier"] == "AA:BB:CC:DD:EE:FF"
        worker.connection_changed.emit(True, "已连接")
        app.processEvents()

        worker.preview_ready.emit(
            {
                "samples": [[float(index - 50) for index in range(100)]],
                "sample_rate": 250.0,
                "battery_percent": 82,
                "packet_loss": 0.001,
                "signal_quality": 0.99,
                "temperature_c": 31.2,
                "diagnostics": {
                    "received_sequence_packets": 18,
                    "missing_sequence_packets": 1,
                    "invalid_packets": 0,
                    "queue_drops": 0,
                },
            }
        )
        app.processEvents()

        assert len(window.curve.getData()[1]) == 100
        assert window.metric_values["battery"].text() == "82%"
        assert window.metric_values["loss"].text() == "0.100%"
        assert "250 Hz" in window.plot_meta.text()
    finally:
        window.close()
        app.processEvents()
        assert worker.stopped is True
