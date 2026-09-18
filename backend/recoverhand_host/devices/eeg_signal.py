"""脑电运动想象信号链：移植自 MIdemo 的 FeatureEngine + RuleDecoder 核心。

数学路径与 MIdemo 保持一致：
  因果滤波（50Hz 陷波 + 4-32Hz 带通）→ C3/C4 局部拉普拉斯 → Welch 频带功率
  → 相对基线的 ERD%（dB）→ 对侧 ERD 规则 + 抓握量。

完整 QC/伪迹门限/证据迟滞等细节由算法负责人在此基础上扩展；本模块只提供
「原始 EEG → 意图事件」的最小可靠基线，作为康复手上位机与 MIdemo 之间的独立实现。
"""

from __future__ import annotations

from typing import Any, Protocol

import numpy as np

try:
    from scipy.signal import butter, iirnotch, sosfilt, sosfilt_zi, tf2sos, welch
except ImportError:  # 可选依赖；未安装 scipy 时主应用仍可启动，仅脑电特征提取不可用。
    butter = iirnotch = sosfilt = sosfilt_zi = tf2sos = welch = None  # type: ignore[assignment]

# 与 MIdemo mi_config.json / continuous.py 对齐的默认参数。
DEFAULT_ELECTRODES = ["FC3", "FCz", "FC4", "C3", "Cz", "C4", "CP3", "CP4"]

DEFAULT_ANALYSIS: dict[str, Any] = {
    "line_notch_enabled": True,
    "line_frequency_hz": 50.0,
    "line_notch_q": 5.0,
    "filter_order": 4,
    "analysis_bandpass_hz": [4.0, 32.0],
    "mu_band_hz": [8.0, 13.0],
    "beta_band_hz": [13.0, 30.0],
    "evidence_erd_threshold_pct": -10.0,
    "erd_min_specificity_db": 0.5,
}

DEFAULT_DECODE: dict[str, Any] = {
    "sampling_rate": 250.0,
    "window_seconds": 1.0,
    "hop_seconds": 0.1,
    "baseline_window_seconds": 2.0,
    "warmup_seconds": 3.0,
    "control_band": "mu",
    "full_grip_db": 3.0,
}

MODEL_VERSION = "midemo-rule-v0"


def _require_scipy() -> None:
    if butter is None:
        raise RuntimeError(
            "未安装 scipy；脑电特征提取需要 scipy，请在 host_app 目录执行 "
            ".\\\\.venv\\\\Scripts\\\\python.exe -m pip install -e \".[eeg]\""
        )


class CausalFilter:
    """因果滤波（无未来信息泄漏），MIdemo CausalFilter 的移植。"""

    def __init__(self, fs: float, analysis: dict[str, Any]) -> None:
        _require_scipy()
        stages = []
        if analysis["line_notch_enabled"]:
            b, a = iirnotch(analysis["line_frequency_hz"], analysis["line_notch_q"], fs=fs)
            stages.append(tf2sos(b, a))
        stages.append(
            butter(
                analysis["filter_order"],
                analysis["analysis_bandpass_hz"],
                btype="bandpass",
                fs=fs,
                output="sos",
            )
        )
        self.sos = np.concatenate(stages)
        self.state = None

    def process(self, values: np.ndarray) -> np.ndarray:
        if self.state is None:
            self.state = sosfilt_zi(self.sos)[:, :, None] * values[0][None, None, :]
        result, self.state = sosfilt(self.sos, values, axis=0, zi=self.state)
        return result


def band_powers(
    values: np.ndarray, fs: float, electrodes: list[str], analysis: dict[str, Any]
) -> dict[str, np.ndarray]:
    """C3/C4 局部拉普拉斯后，计算 μ/β 频带功率（各一个标量/侧）。"""
    _require_scipy()
    index = {name: electrodes.index(name) for name in electrodes}
    local = np.column_stack(
        [
            values[:, index["C3"]] - values[:, [index[x] for x in ("FC3", "Cz", "CP3")]].mean(axis=1),
            values[:, index["C4"]] - values[:, [index[x] for x in ("FC4", "Cz", "CP4")]].mean(axis=1),
        ]
    )
    freq, psd = welch(
        local, fs=fs, axis=0, nperseg=min(len(local), round(fs)), detrend="constant"
    )
    result: dict[str, np.ndarray] = {}
    for band in ("mu", "beta"):
        low, high = analysis[f"{band}_band_hz"]
        mask = (freq >= low) & (freq <= high)
        result[band] = np.trapezoid(psd[mask], freq[mask], axis=0)
    return result


def decode_intent(
    erd_c3: float,
    erd_c4: float,
    *,
    threshold: float,
    margin: float,
    full_grip_db: float,
) -> dict[str, Any]:
    """对侧 ERD 规则：把 μ 带 ERD% 映射为方向、侧向性与抓握量。

    ``erd_c3/erd_c4`` 为相对基线的 dB 值（负值代表 ERD/功率下降）。
    """
    lateral = erd_c4 - erd_c3
    state, support = "uncertain", None
    if erd_c3 <= threshold and lateral >= margin:
        state, support = "right", erd_c3
    elif erd_c4 <= threshold and lateral <= -margin:
        state, support = "left", erd_c4
    grip = 0.0
    if state != "uncertain" and support is not None:
        grip = float(np.clip(-support / full_grip_db, 0.0, 1.0))
    return {
        "state": state,
        "grip": grip,
        "laterality_db": lateral,
        "confidence": 1.0 if state != "uncertain" else 0.0,
        "method": "contralateral_erd_rule",
        "model_version": MODEL_VERSION,
    }


class IntentExtractor(Protocol):
    """脑电意图提取器：原始 EEG 帧 → 意图事件。算法负责人实现此协议即可替换。"""

    def push(self, raw: np.ndarray) -> None:
        ...

    def lock_baseline(self) -> None:
        ...

    def predict(self) -> dict[str, Any]:
        ...


class MiIntentExtractor:
    """持续接收原始 EEG 帧，锁定基线后输出意图事件（基线实现）。"""

    def __init__(
        self,
        fs: float | None = None,
        electrodes: list[str] | None = None,
        analysis: dict[str, Any] | None = None,
        decode: dict[str, Any] | None = None,
    ) -> None:
        self.fs = float(fs or DEFAULT_DECODE["sampling_rate"])
        self.electrodes = list(electrodes or DEFAULT_ELECTRODES)
        self.analysis = {**DEFAULT_ANALYSIS, **(analysis or {})}
        self.cfg = {**DEFAULT_DECODE, **(decode or {})}
        self.window = round(self.fs * self.cfg["window_seconds"])
        self.warm = round(self.fs * self.cfg["warmup_seconds"])
        self.baseline_size = round(self.fs * self.cfg["baseline_window_seconds"])
        self.capacity = round(self.fs * max(8.0, self.cfg["baseline_window_seconds"] + 1.0))
        self.filter = CausalFilter(self.fs, self.analysis)
        self._filtered = np.empty((0, len(self.electrodes)))
        self._count = 0
        self._baseline: dict[str, np.ndarray] | None = None

    def push(self, raw: np.ndarray) -> None:
        """接收原始样本块，形状 (n_samples, n_channels)。"""
        if raw.shape[1] != len(self.electrodes):
            raise ValueError(f"通道数应为 {len(self.electrodes)}，实际 {raw.shape[1]}")
        values = np.nan_to_num(raw, nan=0.0, posinf=0.0, neginf=0.0)
        filtered = self.filter.process(values)
        self._filtered = np.concatenate([self._filtered, filtered])[-self.capacity :]
        self._count += raw.shape[0]

    def lock_baseline(self) -> None:
        if len(self._filtered) < self.baseline_size:
            self._baseline = None
            return
        self._baseline = band_powers(
            self._filtered[-self.baseline_size :], self.fs, self.electrodes, self.analysis
        )

    def predict(self) -> dict[str, Any]:
        if self._baseline is None or len(self._filtered) < self.window:
            return decode_intent(0.0, 0.0, threshold=1e9, margin=1e9, full_grip_db=1.0)
        power = band_powers(
            self._filtered[-self.window :], self.fs, self.electrodes, self.analysis
        )
        band = self.cfg["control_band"]
        erd = 10 * np.log10(power[band] / self._baseline[band])
        threshold = 10 * np.log10(1 + self.analysis["evidence_erd_threshold_pct"] / 100)
        margin = self.analysis["erd_min_specificity_db"]
        return decode_intent(
            float(erd[0]),
            float(erd[1]),
            threshold=threshold,
            margin=margin,
            full_grip_db=self.cfg["full_grip_db"],
        )
