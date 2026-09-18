# RecoverHand 康复手上位机

RecoverHand 是面向医护/研究人员的 Windows 原生上位机原型。当前主界面使用 Python 3.11、PySide6 Qt Widgets/QSS 与 PyQtGraph；设备抽象、会话运行时、算法协议和 SQLite 连接档案保持为可测试的 Python 模块。早期 React/FastAPI 页面仅作兼容性参考，不再是默认入口。

## 当前产品流程（v0.2）

原生界面已经串起一轮完整的研发会话骨架。默认连接档案使用模拟设备；实验性真实驱动可在设置页选择，但“驱动可连接”不等于已经通过人体训练验证。

1. 填写患者或匿名研究对象、患侧、协议与重复次数；
2. 按连接档案检查 EEG、腕部单个双电极 sEMG 贴片和辅助手套；
3. 执行静息基线、任务提示、运动想象和信号质量检查；当前标定页仍为模拟；
4. 由 `SessionRuntime` 以“静息—提示—意图窗口—意图冻结—安全检查—辅助—保持—释放恢复”推进试次；
5. 在辅助和保持阶段调用 `EmgResponseAnalyzer`，把响应判定写入试次结果；
6. 通过 `AssistStrategy` 把冻结意图转换为设备动作，并记录命令应答；
7. 在 Qt 内嵌 MIdemo P03-E WebGL2 粒子手，显示当前映射姿态；
8. 保存冻结元数据、运行时事件和结束标记，支持确定性事件回放。

所有页面可以浏览，但会话动作受统一状态机约束，不能从首页直接跳过设备检查或标定开始训练。设备 I/O、BLE 回调和会话运行时在独立 Qt 线程的固定 asyncio 循环中执行，运行时事件转发到 Qt 主线程显示。

## 研发与安全边界

- 默认档案启用三个模拟器，不连接人体信号，也不发送真实运动命令。
- OpenBCI/BrainFlow EEG、唯理 BLE 单通道 sEMG 和实验性辅助手套适配器已经进入设备注册表；真实设备仍需逐项完成连接、标定、同步、断线和安全验证。
- 真实 EEG 驱动已有 μ 带 ERD 基线提取器，但标定页尚未触发个体基线锁定，不能把当前输出视为有效识别结果。
- sEMG 已有原始采集和响应分析协议；当前试次摘要只记录是否响应，完整指标、贴位重复性和运动伪迹对照仍待补齐。
- 运行时的 `safety.release` 是软件状态事件，不等同于辅助手套已经完成物理释放；软件中止路径还需要设备应答和实际状态确认。
- 模拟 EEG/sEMG 数字只能验证软件流程，不能解释为意图识别结果、患者主动参与或康复效果。
- 粒子手是反馈呈现，不是患者实际关节角度、握力或康复效果。
- 软件停止不能替代机械快拆、独立断电和固件本地安全状态机。

更完整的页面现状、接口和交接验收条件见 [`FRONTEND_REQUIREMENTS.md`](FRONTEND_REQUIREMENTS.md)，算法协议见 [`backend/recoverhand_host/algorithms/README.md`](backend/recoverhand_host/algorithms/README.md)。

## 结构

```text
host_app/
├─ backend/recoverhand_host/
│  ├─ desktop/       # Qt 页面、P03-E 粒子手、QSS 与设备工作线程
│  ├─ emg_monitor/   # 独立原始肌电波形监视器
│  ├─ devices/       # 驱动接口、注册表、状态管理和模拟器
│  ├─ runtime/       # 统一时钟、事件总线、试次、安全监督、记录与回放
│  ├─ algorithms/    # EEG、sEMG 与辅助动作的可替换协议入口
│  ├─ storage/       # SQLite 连接档案
│  ├─ session.py     # 会话状态机与转换约束
│  ├─ models.py      # 标准帧、命令、结果、事件和统一健康状态
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

监视器只连接唯理单通道 BLE 贴片，显示 1/2/4 秒原始 μV 滚动波形、电量、温度、窗口 RMS、峰值和通知丢包。BLE 在独立常驻事件循环中采集，界面约以 25 FPS 刷新；Y 轴采用平滑自动量程，避免普通逐帧自动缩放引起跳动。监视器本身不滤波、不识别动作、不写入数据文件，也不向候选时间同步特征发送命令。

主上位机已可通过设备档案选择真实 sEMG 驱动，并由会话记录器保存 `data.emg` 事件。独立监视器继续承担贴位、传输和原始波形诊断；训练界面只呈现闭环所需的波形、质量和响应结果。

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

- EEG：确认 BrainFlow Board ID、串口发现、通道映射、设备时间戳、事件标记、信号质量来源和个体基线锁定。
- sEMG：唯理肌电贴使用 250 Hz 单通道通知流；实机阶段仍需确认 Write 特征、时钟同步、模拟抗混叠滤波、腕部贴位、运动伪迹和个体阈值。
- 手套：确认最终传输方式、实际位置/速度反馈、故障码、控制租约、限位、看门狗、停止/释放和机械快拆。没有独立传感证据时，执行器位置不能解释为拉力或患者关节角度。

事件驱动的采集/推理/控制骨架和会话记录已经建立。真实设备阶段仍需完成标定接入、运行时暂停、sEMG 指标入库、异常释放的设备确认以及报告页回放。
