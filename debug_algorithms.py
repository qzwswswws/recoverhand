"""算法工作节点：独立调试三条算法缝，不依赖 GUI。

用法：
    python debug_algorithms.py motion   # 手部运动映射
    python debug_algorithms.py emg      # 肌电响应分析
    python debug_algorithms.py intent   # 脑电意图提取
    python debug_algorithms.py all      # 全部

这是算法负责人的调试入口；把你要迭代的算法替换成自己的实现后，直接在这里
跑通，再注入 ``SessionRuntime.run(...)`` 进闭环，界面由另一位开发者并行推进。
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent / "backend"))

import numpy as np
from recoverhand_host.algorithms import (
    EnvelopeEmgAnalyzer,
    MiIntentExtractor,
    TwoFingerAssistStrategy,
)


def demo_motion() -> None:
    """手部运动映射：给定脑电意图 → 输出手套命令序列。"""
    print("== 手部运动映射（两指拿捏，grip→力量） ==")
    strategy = TwoFingerAssistStrategy()
    for grip in (0.0, 0.5, 1.0):
        intent = {"state": "right", "grip": grip}
        print(f"意图 grip={grip:.1f}：")
        for action, payload in strategy.assist_actions(intent):
            print(f"    {action}  {payload}")
    print(f"释放：{strategy.release_actions()}\n")


def demo_emg() -> None:
    """肌电响应分析：喂一段带爆发的合成 sEMG，看阈值判响应。"""
    print("== 肌电响应分析（滑动 RMS 基线 + 阈值） ==")
    analyzer = EnvelopeEmgAnalyzer(threshold_uv=10.0)
    rng = np.random.default_rng(0)
    # 静息段 → 爆发段 → 静息段，250 Hz
    rest = rng.normal(0, 2.0, 500)
    burst = rng.normal(0, 60.0, 500)
    stream = np.concatenate([rest, burst, rest])
    for index in range(0, len(stream), 50):
        window = stream[index : index + 50]
        analyzer.update({"samples": [window.tolist()], "sample_rate": 250})
    print("指标：", {k: (round(v, 2) if isinstance(v, float) else v) for k, v in analyzer.metrics().items()})
    print(f"是否判为响应：{analyzer.responded()}\n")


def demo_intent() -> None:
    """脑电意图提取：合成白噪 EEG，走一遍滤波/基线/解码流程。"""
    print("== 脑电意图提取（μ 带 ERD 对侧规则，基线实现） ==")
    extractor = MiIntentExtractor(fs=250.0)
    raw = np.random.default_rng(1).normal(0, 20, size=(750, 8))
    extractor.push(raw)
    extractor.lock_baseline()
    result = extractor.predict()
    print("意图事件：", result)
    print("（合成白噪无真实 μ 节律，结果无意义、可能随机偏向一侧；替换成你的算法后在此验证）\n")


def main() -> int:
    parser = argparse.ArgumentParser(description="算法工作节点")
    parser.add_argument("target", nargs="?", default="all", choices=["motion", "emg", "intent", "all"])
    args = parser.parse_args()

    if args.target in {"motion", "all"}:
        demo_motion()
    if args.target in {"emg", "all"}:
        demo_emg()
    if args.target in {"intent", "all"}:
        demo_intent()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
