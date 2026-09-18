# 上位机前端需求清单（供前端开发者）

## 一、项目背景

康复手闭环训练系统上位机：**EEG 判断运动意图 → 辅助手套执行受限运动 → 腕部单通道 sEMG 观察响应**，面向医护监督下的神经损伤手功能康复研究。

闭环分两层：试次内快速闭环（EEG 意图冻结 → 安全检查 → 手套辅助 → EMG 响应 → 释放），试次间慢速闭环（综合评价 → 调整下一试次参数）。

## 二、技术栈与目录

- Python 3.11 + **PySide6（Qt Widgets）+ pyqtgraph** + SQLite。
- 目录（`backend/recoverhand_host/`）：
  - `runtime/` — 会话内核（纯 Python、无 Qt）：时钟/事件总线/试次状态机/安全监督器/记录回放。
  - `devices/` — 设备驱动：EEG(`eeg_cyton`)、EMG(`waveletech_emg`)、手套(`sy_hr12`)、模拟器(`simulated`)。
  - `algorithms/` — 算法工作节点（三条可替换缝，见 §四）。
  - `desktop/` — **Qt 界面（前端，你的工作区）**。
  - `models.py` — 帧/事件模型。

## 三、分工边界（务必遵守）

- **后端/算法（另一位负责人）**：`runtime/`、`devices/`、`algorithms/`，以及真实设备联调。
- **前端（你）**：`desktop/` 的布局与显示细节；**只通过 §五 的接口消费后端，不直接调度硬件、不直接调用手套驱动**。

## 四、三条算法缝（后端负责人会替换，前端无需关心内部）

`algorithms/` 提供三条「Protocol + 基线实现」的可替换缝：脑电意图 `IntentExtractor`、肌电响应 `EmgResponseAnalyzer`、手部运动映射 `AssistStrategy`。前端展示它们的**输出**即可，不要把算法写进界面。

## 五、前端如何拿数据（已就绪的接口）

1. **运行时事件（Qt 信号）**：`DeviceWorker.runtime_event`（`Signal(object)`），每条是一个 `RuntimeEvent` 字典。事件名：
   - `session.started` / `session.stopped`
   - `trial.started` / `trial.phase_changed`（`data.current` 为相位名）/ `trial.completed`（`data` 含 `intent_state`、`emg_responded`）
   - `intent.frozen`（`data.state`/`grip`）
   - `safety.command_authorized` / `command.ack` / `safety.release`
   - `data.eeg` / `data.emg` / `data.glove`（设备预览）
2. **运行时快照**：`SessionRuntime.snapshot()`（当前试次相位、监督器状态）。
3. **训练生命周期**：`DeviceWorker` 的 `start_session` / `stop_session` 命令；会话结束后发 `completed("session_finished", snapshot)`。
4. **设备命令**：`DeviceWorker` 的 `command_one`（`kind` + `GloveCommand`），用于手套控制面板。

## 六、前端需求清单（按优先级）

### P0 —— 已接入、需打磨显示细节

1. **训练页订阅真实数据**：已把 QTimer 模拟换成订阅 `runtime_event`。待打磨：波形缩放/颜色/量纲标签、虚拟手姿态映射的真实度。
2. **设备检查页手套控制面板**：已做（模式/对指手指/力量/时长 + 应用参数/开始/暂停/软关机）。待改：**按「是否选中 `sy_hr12_glove` 驱动」启用/隐藏该面板**，避免在模拟或 ESP32 驱动下误操作。

### P1 —— 待实现

3. **运行时级「暂停/继续」**：试次状态机目前没有暂停态，暂停按钮只切 UI 状态。需与后端协商加 `pause/resume` 语义后接上。
4. **相位时长配置 UI**：把 `phase_durations`（静息/提示/意图窗口/辅助/保持/释放的秒数）做成设置项，传入 `start_session`。
5. **标定页接真实 EEG**：当前标定页仍是模拟；需订阅真实 EEG 做静息基线/意图特征，替代 `CalibrationPage._advance` 的模拟。
6. **报告页展示会话记录**：读取 `data/sessions/<session_id>/`（`metadata.json` + `events.jsonl`），展示每试次意图/响应/结果，并支持确定性回放。

### P2 —— 体验与健壮性

7. **设备检查状态呈现**：真实设备刚连上会有约 1 秒「正在读取状态」空档（`health().signal_ok` 短暂为 False），界面不要因此误报故障，用「连接降级→数据有效」的过渡呈现。
8. **断线/错误提示与重连引导**：BLE 断线、串口被占用（OpenBCI 提示）、命令失败（`fault_code`）都应有清晰提示。

## 七、安全约束（前端必须遵守）

1. **手套戴在手上时禁止发送运动命令**；界面在发「开始/软关机」前必须二次确认（后端 `start`/`poweroff` 已要求 `confirm=true`）。
2. 所有运动命令经后端安全监督器；**前端不直接调用手套驱动**。
3. 记录的是原始数据与事件时间；前端去基线只影响显示，不影响记录内容。
4. 软件停止不能替代机械快拆或独立断电；真实设备阶段必须等待固件释放确认。

## 八、运行与验证

```bash
cd host_app
.\.venv\Scripts\python.exe -m pytest -q            # 62 passed
.\.venv\Scripts\python.exe -m ruff check backend tests
run_recoverhand.cmd                                 # 启动上位机
python debug_algorithms.py all                      # 算法工作节点（后端用）
python verify_sy_hr12.py [--send-pause]             # 手套 BLE 验证（后端用）
```

依赖：`pip install -e ".[dev,eeg,emg]"`（PySide6/pyqtgraph/numpy 为主依赖；brainflow/scipy 在 `eeg`、bleak 在 `emg`）。
