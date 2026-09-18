# 算法接入说明

`recoverhand_host.algorithms` 汇总 EEG 意图、sEMG 响应和辅助动作映射的可替换协议。基线实现用于联调和回归测试，不表示算法已经具备临床有效性。

## 1. EEG 意图提取

```python
class IntentExtractor(Protocol):
    def push(self, raw: np.ndarray) -> None: ...
    def lock_baseline(self) -> None: ...
    def predict(self) -> dict[str, Any]: ...
```

`raw` 的形状为 `(样本数, 通道数)`。`predict()` 的输出至少包含：

```python
{
    "state": "left" | "right" | "uncertain",
    "grip": float,          # 0..1
    "confidence": float,
    "method": str,
    "model_version": str,
}
```

基线实现为 `MiIntentExtractor`。它由 `BrainFlowCytonDriver` 在连接时构造，而不是直接传给 `SessionRuntime.run(...)`。当前真实标定页尚未触发 `lock_baseline()`；完整接入需要把标定结果传入 EEG 驱动，或为运行时补充统一的提取器注入入口。

## 2. sEMG 响应分析

```python
class EmgResponseAnalyzer(Protocol):
    def update(self, preview: dict[str, Any]) -> None: ...
    def reset(self) -> None: ...
    def responded(self) -> bool: ...
    def metrics(self) -> dict[str, Any]: ...
```

`preview["samples"]` 当前采用二维列表，即使设备是单通道也为 `[[...]]`；`sample_rate` 使用 Hz。运行时只在辅助和保持阶段调用 `update()`，每个试次结束后调用 `reset()`。

基线实现 `EnvelopeEmgAnalyzer` 使用滑动 RMS 和相对基线阈值。目前 `trial.completed` 只记录 `responded()`，`metrics()` 还没有写入试次结果。

## 3. 辅助动作映射

```python
class AssistStrategy(Protocol):
    def assist_actions(
        self, intent: dict[str, Any] | None
    ) -> list[tuple[str, dict[str, Any]]]: ...

    def release_actions(self) -> list[tuple[str, dict[str, Any]]]: ...
```

每一项为 `(action, payload)`。动作由设备适配器解释，运行时负责顺序发送、记录应答和故障处理。策略不直接持有设备驱动，也不改变当前试次已经冻结的意图。

基线实现为 `TwoFingerAssistStrategy`。其中动作名称和参数属于当前实验性手套协议映射，不构成最终产品接口承诺。

## 4. 最小接入示例

```python
from recoverhand_host.runtime.session_runtime import SessionRuntime

runtime = SessionRuntime(session_id="demo", data_root=data_root)
runtime.start({"algorithm_version": "example-1"})

await runtime.run(
    eeg=eeg_driver,
    emg=emg_driver,
    glove=glove_driver,
    target_repetitions=10,
    emg_analyzer=CustomEmgAnalyzer(),
    assist_strategy=CustomAssistStrategy(),
)

runtime.stop("完成")
```

桌面入口通过 `DeviceWorker` 启动运行时，工作线程会转发 `assist_strategy`、`emg_analyzer` 和 `phase_durations`。

## 5. 独立验证

```powershell
python debug_algorithms.py intent
python debug_algorithms.py emg
python debug_algorithms.py motion
python debug_algorithms.py all
```

`intent` 子命令使用合成白噪，只验证滤波、基线和解码链路能否执行。随机偏向某一侧不代表识别效果。真实算法评价需要使用具有事件标记、通道说明和采集条件的 EEG 数据。

相关自动化测试：

- `tests/test_eeg_signal.py`
- `tests/test_emg_analysis.py`
- `tests/test_runtime_closed_loop.py`
- `tests/test_runtime_run.py`
