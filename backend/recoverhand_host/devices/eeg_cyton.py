from __future__ import annotations

import time
from collections.abc import Callable
from typing import Any

import numpy as np

from recoverhand_host.devices.base import DeviceDriver
from recoverhand_host.devices.eeg_signal import MiIntentExtractor
from recoverhand_host.models import DeviceHealth, DeviceKind


class BrainFlowCytonDriver(DeviceDriver):
    """OpenBCI Cyton（ADS1299）真实脑电驱动：BrainFlow 采集 + MIdemo 信号链。

    BrainFlow 作为可选依赖惰性导入；未安装时 ``connect`` 给出明确安装提示。
    输出与 ``SyntheticEegDriver`` 对齐，额外附带 ``intent`` 字段（方向 + 抓握量）。
    """

    kind = DeviceKind.EEG

    def __init__(
        self,
        brainflow_module: dict[str, Any] | None = None,
        extractor_factory: Callable[[float], MiIntentExtractor] | None = None,
    ) -> None:
        self._brainflow = brainflow_module
        self._extractor_factory = extractor_factory or (lambda fs: MiIntentExtractor(fs=fs))
        self._connected = False
        self._config: dict[str, Any] = {}
        self._board: Any = None
        self._board_id: int | None = None
        self._sampling_rate = 250.0
        self._eeg_channels: list[int] = list(range(8))
        self._extractor: MiIntentExtractor | None = None
        self._streaming = False
        self._sequence = 0
        self._last_error = "尚未连接"

    def _load_brainflow(self) -> dict[str, Any]:
        if self._brainflow is not None:
            return self._brainflow
        try:
            from brainflow.board_shim import BoardIds, BoardShim, BrainFlowInputParams
        except ImportError as exc:
            raise RuntimeError(
                "未安装 BrainFlow；请在 host_app 目录执行 "
                ".\\\\.venv\\\\Scripts\\\\python.exe -m pip install -e \".[eeg]\""
            ) from exc
        self._brainflow = {
            "BoardIds": BoardIds,
            "BoardShim": BoardShim,
            "BrainFlowInputParams": BrainFlowInputParams,
        }
        return self._brainflow

    async def discover(self, config: dict[str, Any]) -> list[dict[str, Any]]:
        port = str(config.get("serial_port", "")).strip()
        return [{"id": port or "Cyton", "name": f"OpenBCI Cyton @ {port or '未指定串口'}", "rssi": None}]

    async def connect(self, config: dict[str, Any]) -> None:
        self._config = dict(config)
        brainflow = self._load_brainflow()
        BoardIds = brainflow["BoardIds"]
        BoardShim = brainflow["BoardShim"]
        BrainFlowInputParams = brainflow["BrainFlowInputParams"]
        board_id = int(config.get("board_id", BoardIds.CYTON_BOARD.value))
        params = BrainFlowInputParams()
        serial_port = str(config.get("serial_port", "")).strip()
        if not serial_port:
            raise ValueError("Cyton 模式必须填写串口号，例如 COM10")
        params.serial_port = serial_port
        BoardShim.enable_dev_board_logger()
        try:
            board = BoardShim(board_id, params)
            board.prepare_session()
        except Exception as exc:
            raise RuntimeError(f"脑电板卡连接失败: {exc}") from exc
        self._board = board
        self._board_id = board_id
        self._sampling_rate = float(BoardShim.get_sampling_rate(board_id))
        self._eeg_channels = [int(v) for v in BoardShim.get_eeg_channels(board_id)]
        self._extractor = self._extractor_factory(self._sampling_rate)
        self._connected = True
        self._last_error = "脑电板卡已准备，等待启动采集"

    async def start_stream(self) -> None:
        if self._board is None:
            raise RuntimeError("脑电板卡尚未连接")
        if self._streaming:
            return
        self._board.start_stream(45_000)
        self._streaming = True

    async def stop_stream(self) -> None:
        if self._streaming and self._board is not None:
            self._board.stop_stream()
        self._streaming = False

    async def disconnect(self) -> None:
        await self.stop_stream()
        if self._board is not None:
            try:
                self._board.release_session()
            except Exception:  # noqa: BLE001, S110 - 释放失败不影响断开流程
                pass
        self._board = None
        self._extractor = None
        self._connected = False

    async def health(self) -> DeviceHealth:
        if not self._connected or self._board is None:
            return DeviceHealth(reason=self._last_error)
        if not self._streaming:
            return DeviceHealth(transport_ok=True, stream_ok=False, reason="板卡已连接但未采集")
        latest = self._pull_latest()
        has_samples = latest.size > 0
        finite = has_samples and bool(np.all(np.isfinite(latest)))
        signal_ok = has_samples and finite and float(np.nanmax(np.ptp(latest, axis=0))) > 0.0
        reason = (
            "脑电数据流有效" if signal_ok
            else "板卡已连接但样本无效或通道平坦；请检查电极接触"
        )
        return DeviceHealth(
            transport_ok=True,
            stream_ok=has_samples,
            time_sync_ok=False,
            signal_ok=signal_ok,
            control_ready=False,
            reason=reason,
        )

    def _pull_latest(self, seconds: float = 2.0) -> np.ndarray:
        if self._board is None or not self._streaming:
            return np.empty((0, len(self._eeg_channels)), dtype=float)
        samples = max(1, int(seconds * self._sampling_rate))
        data = np.asarray(self._board.get_current_board_data(samples), dtype=float)
        if data.ndim != 2 or data.shape[0] == 0:
            return np.empty((0, len(self._eeg_channels)), dtype=float)
        channels = [c for c in self._eeg_channels if c < data.shape[0]]
        if not channels:
            return np.empty((0, len(self._eeg_channels)), dtype=float)
        return data[channels].T  # (n_samples, n_channels)

    async def preview(self) -> dict[str, Any]:
        if not self._connected or self._board is None:
            raise RuntimeError("脑电板卡尚未连接")
        latest = self._pull_latest()
        self._sequence += 1
        intent: dict[str, Any] = {}
        if latest.size and self._extractor is not None:
            self._extractor.push(latest)
            intent = self._extractor.predict()
        channel_names = ["FC3", "FCz", "FC4", "C3", "Cz", "C4", "CP3", "CP4"][: len(self._eeg_channels)]
        return {
            "kind": self.kind.value,
            "sample_rate": self._sampling_rate,
            "channel_names": channel_names,
            "samples": latest.T.tolist(),
            "host_time": time.time(),
            "device_time": None,
            "sequence": self._sequence,
            "quality": {name: 0.0 for name in channel_names},
            "intent": intent,
            "notice": "真实 Cyton 脑电；意图为运动前窗口的 μ 带 ERD 规则，仅作基线",
        }
