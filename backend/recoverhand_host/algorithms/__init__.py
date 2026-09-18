"""算法工作节点：三条可独立调试、可替换的生理电/运动算法接口。

这些接口与 Qt 界面解耦：

- **脑电意图** ``IntentExtractor`` / ``MiIntentExtractor``（基线：μ 带 ERD 对侧规则）
- **肌电响应** ``EmgResponseAnalyzer`` / ``EnvelopeEmgAnalyzer``（基线：滑动 RMS + 阈值）
- **手部运动映射** ``AssistStrategy`` / ``TwoFingerAssistStrategy``（基线：两指拿捏，grip→力量）

三条接口都实现为 Protocol + 一个基线实现。肌电响应和动作策略可直接注入
``SessionRuntime.run(...)``；脑电意图提取器当前由 EEG 驱动构造。
"""

from __future__ import annotations

from recoverhand_host.devices.eeg_signal import IntentExtractor, MiIntentExtractor
from recoverhand_host.devices.emg_analysis import EmgResponseAnalyzer, EnvelopeEmgAnalyzer
from recoverhand_host.runtime.session_runtime import AssistStrategy, TwoFingerAssistStrategy

__all__ = [
    "AssistStrategy",
    "EmgResponseAnalyzer",
    "EnvelopeEmgAnalyzer",
    "IntentExtractor",
    "MiIntentExtractor",
    "TwoFingerAssistStrategy",
]
