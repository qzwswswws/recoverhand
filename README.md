# RecoverHand 康复手上位机

RecoverHand 是面向医护/研究人员的 Windows 原生上位机原型。当前主界面使用 Python 3.11、PySide6 Qt Widgets/QSS 与 PyQtGraph；业务状态机、设备抽象和 SQLite 连接档案继续保持为可测试的 Python 模块。早期 React/FastAPI 页面保留为兼容性参考，不再是默认入口。

## 当前产品流程（v0.2）

原生界面已经串起一轮完整的研发模拟会话：

1. 填写患者或匿名研究对象、患侧、协议与重复次数；
2. 按连接档案检查 EEG、腕部单个双电极 sEMG 贴片和辅助手套；
3. 执行静息基线、任务提示、运动想象和信号质量检查；
4. 以“静息—提示—意图等待—辅助运动—保持—释放恢复”推进训练试次；
5. 明确区分运动前 EEG 意图窗口与运动中/运动后 sEMG 响应窗口；
6. 在 Qt 内嵌 MIdemo P03-E WebGL2 粒子手，显示当前映射姿态并列出目标值；
7. 结束、释放确认、形成记录并由操作者复核。

所有页面可以浏览，但会话动作受统一状态机约束，不能从首页直接跳过设备检查或标定开始训练。设备 I/O 在独立 Qt 线程中执行，避免阻塞界面。

## 研发与安全边界

- 默认档案仍只启用三个无硬件模拟器，不连接人体信号，也不发送真实运动命令。
- 唯理 BLE 单通道 sEMG 先由独立原始信号监视器验证，不进入主上位机训练流程。
- ESP32 手套 HTTP 驱动目前只读 `/api/status`；设置页没有手套运动按钮。
- OpenBCI/BrainFlow 仍是接口占位；唯理 BLE sEMG 已实现厂家 20 字节协议解析，但设备时钟写入和信号质量阈值仍待实机验证。
- 模拟 EEG/sEMG 数字只能验证软件流程，不能解释为意图识别结果、患者主动参与或康复效果。
- 粒子手当前接受 `0–1` 模拟屈曲量；它是反馈呈现，不是患者实际关节角度、握力或康复效果。
- 软件停止不能替代机械快拆、独立断电和固件本地安全状态机。

## 结构

```text
host_app/
├─ backend/recoverhand_host/
│  ├─ desktop/       # Qt 页面、P03-E 粒子手、QSS 与设备工作线程
│  ├─ emg_monitor/   # 独立原始肌电波形监视器
│  ├─ devices/       # 驱动接口、注册表、状态管理和模拟器
│  ├─ storage/       # SQLite 连接档案
│  ├─ session.py     # 会话状态机与转换约束
│  ├─ models.py      # 标准帧、手套状态和统一健康状态
│  └─ main.py        # 早期 FastAPI 接口（可选兼容层）
├─ frontend/         # 早期 React 页面（非默认入口）
├─ tests/            # 状态机、设备、存储、API 与桌面流程测试
├─ run_recoverhand.cmd
├─ run_emg_monitor.cmd
└─ data/             # 运行时 SQLite，不纳入版本管理
```

## 安装与启动

PowerShell：

```powershell
Set-Location D:\workspace2\OCnotebook\projrct\recoverhand\host_app
python -m venv .venv
.\.venv\Scripts\python.exe -m pip install -e ".[dev,emg]"
.\.venv\Scripts\python.exe -m recoverhand_host.desktop
```

安装完成后也可以双击 `run_recoverhand.cmd`。当前 Windows/Anaconda 环境已验证 PySide6 6.8.3；依赖范围暂时锁定在 6.8 系列，避免 6.9+ 与本机 ICU DLL 冲突。

## 独立原始肌电监视器

双击 `run_emg_monitor.cmd`，或执行：

```powershell
.\.venv\Scripts\python.exe -m recoverhand_host.emg_monitor
```

监视器只连接唯理单通道 BLE 贴片，显示 1/2/4 秒原始 μV 滚动波形、电量、温度、窗口 RMS、峰值和通知丢包。BLE 在独立常驻事件循环中采集，界面约以 25 FPS 刷新；Y 轴采用平滑自动量程，避免普通逐帧自动缩放引起跳动。程序当前不滤波、不识别动作、不写入数据文件，也不向时间同步候选特征发送命令。

主上位机仍使用模拟 EMG。是否把真实原始波形或仅把响应特征放入主界面，等待贴位、伪迹和信号质量实测后再决定。

训练页通过内嵌 `QWebEngineView` 加载 P03-E 粒子手，不会打开外部浏览器。静态资源仅绑定本机 `127.0.0.1` 的随机端口；WebGL2、页面或绘制回执失败时自动回退到二维手。嵌入模式采用面向小尺寸反馈卡片的性能档，保留 12,000 个手部粒子、骨骼蒙皮与接触约束，降低像素填充和辉光后处理开销；独立开发页面的高画质参数不变。粒子手资产来源、哈希及 Apache-2.0 许可证位于 `desktop/assets/particle_hand/`。

## 验证

```powershell
Set-Location D:\workspace2\OCnotebook\projrct\recoverhand\host_app
.\.venv\Scripts\python.exe -m pytest -q
.\.venv\Scripts\python.exe -m ruff check backend tests
.\.venv\Scripts\python.exe -m compileall -q backend tests
```

## 真实设备接入规则

每个真实设备驱动必须实现 `discover / connect / disconnect / health / start_stream / stop_stream / preview`，并提供配置定义供设置页动态生成表单。连接档案只描述“如何连接”，不代表设备已经可用于训练。

- EEG：确认 BrainFlow Board ID、串口发现、通道映射、设备时间戳、事件标记和信号质量来源。
- sEMG：唯理肌电贴使用 250 Hz 单通道通知流，当前只进入独立监视器；实机阶段仍需确认 Write 特征、时钟同步、模拟抗混叠滤波、腕部贴位和个体阈值。
- 手套：确认最终传输方式、位置/速度反馈、故障码、控制租约、限位、看门狗、停止/释放和机械快拆。未验证拉力传感器前，不能用舵机位置估算“力”。

真实设备阶段还需要将当前模拟训练时序改为事件驱动的采集/推理/控制管线，并把每次会话的设备档案、算法版本、阈值和事件时间完整冻结到记录中。
