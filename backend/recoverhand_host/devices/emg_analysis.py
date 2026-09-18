"""肌电响应分析：把 sEMG 预览流变成「是否出现主动响应」与响应指标。

这是算法工作节点的三条缝之一（脑电意图 / 肌电响应 / 手部运动映射）。
实现 ``EmgResponseAnalyzer`` 协议即可替换；``EnvelopeEmgAnalyzer`` 是滑动 RMS
基线 + 幅度阈值的基线版，供算法负责人对照与迭代。
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field
from typing import Any, Protocol


class EmgResponseAnalyzer(Protocol):
    """肌电响应分析器：喂入 sEMG 预览，判断主动响应并产出指标。"""

    def update(self, preview: dict[str, Any]) -> None:
        ...

    def reset(self) -> None:
        ...

    def responded(self) -> bool:
        ...

    def metrics(self) -> dict[str, Any]:
        ...


@dataclass
class EnvelopeEmgAnalyzer:
    """基线：滑动 RMS 基线 + 幅度阈值判响应。

    ``threshold_uv`` 是相对基线的 RMS 增量阈值（µV）；超过即判为出现响应。
    单通道腕部 sEMG 的运动伪迹大，阈值与衰减系数都留作可调。
    """

    threshold_uv: float = 10.0
    baseline_decay: float = 0.9

    _baseline_rms: float | None = field(default=None, init=False)
    _peak_uv: float = field(default=0.0, init=False)
    _responded: bool = field(default=False, init=False)

    def update(self, preview: dict[str, Any]) -> None:
        samples = preview.get("samples")
        if not samples:
            return
        flat = [float(value) for channel in samples for value in channel]
        if not flat:
            return
        rms = math.sqrt(sum(value * value for value in flat) / len(flat))
        peak = max(abs(value) for value in flat)
        self._peak_uv = max(self._peak_uv, peak)
        if self._baseline_rms is None:
            self._baseline_rms = rms
        else:
            self._baseline_rms = (
                self.baseline_decay * self._baseline_rms + (1 - self.baseline_decay) * rms
            )
        if self._baseline_rms is not None and rms > self._baseline_rms + self.threshold_uv:
            self._responded = True

    def reset(self) -> None:
        self._baseline_rms = None
        self._peak_uv = 0.0
        self._responded = False

    def responded(self) -> bool:
        return self._responded

    def metrics(self) -> dict[str, Any]:
        return {
            "baseline_rms_uv": self._baseline_rms,
            "peak_uv": self._peak_uv,
            "responded": self._responded,
        }
