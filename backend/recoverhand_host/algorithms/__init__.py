"""算法工作节点：三条可独立调试、可替换的生理电/运动算法缝。

这里是算法负责人（脑电-肌电-手部动作-算法协同）的工作入口，与 Qt 界面解耦：

- **脑电意图** ``IntentExtractor`` / ``MiIntentExtractor``（基线：μ 带 ERD 对侧规则）
- **肌电响应** ``EmgResponseAnalyzer`` / ``EnvelopeEmgAnalyzer``（基线：滑动 RMS + 阈值）
- **手部运动映射** ``AssistStrategy`` / ``TwoFingerAssistStrategy``（基线：两指拿捏，grip→力量）

三条缝都实现为 Protocol + 一个基线实现，替换只需写一个符合协议的对象，
注入 ``SessionRuntime.run(...)`` 即可，无需改动运行时或界面。
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
