# RecoverHand 开发环境配置说明

## 1. 开发包用途与边界

本压缩包用于 RecoverHand Windows 上位机的界面、会话运行时、算法协议、模拟设备、实验性真实设备适配器、三维粒子手和独立肌电监视器开发。默认连接档案仍为模拟模式；真实驱动可用于受控联调，但当前软件不能用于无人监督训练或评价康复效果。

压缩包不包含现成虚拟环境、患者数据或运行数据库。首次配置需要从 PyPI 下载 Python 依赖；配置完成后，模拟模式运行不依赖外部服务器。P03-E 静态资源由程序绑定到本机 `127.0.0.1` 随机端口，仅供 Qt WebEngine 加载。

## 2. 推荐环境

- Windows 10/11 64 位；
- Python 3.11 64 位，推荐 python.org 发行版；
- 可用的显卡驱动和 WebGL2；
- 首次安装约需 1 GB 可用空间，Qt WebEngine 占其中主要部分；
- 可以访问 PyPI，或已经配置单位内部的 Python 镜像源。

当前经过验证的组合为 Windows 11 x64、Python 3.11.7、PySide6 6.8.3。项目把 PySide6 限定在 6.8 系列，以避开开发机上已出现的 6.9+ 与 Anaconda ICU DLL 冲突。

## 3. 最快启动方式

1. 把 ZIP 完整解压到普通可写的短目录，例如 `D:\RecoverHand-dev`；不要直接在压缩包预览窗口内运行；
2. 双击 `run_recoverhand.cmd`；
3. 如果 `.venv` 不存在，脚本会自动调用 `setup_dev.cmd` 创建环境、安装依赖并运行测试；
4. 配置完成后会启动 RecoverHand。以后双击同一脚本即可直接启动。

如需验证唯理肌电贴，关闭主上位机后双击 `run_emg_monitor.cmd`。脚本会检查并安装 `emg` 可选依赖，然后启动独立波形窗口。

首次安装时间取决于网络速度。命令行方式如下：

```bat
setup_dev.cmd
run_recoverhand.cmd
```

## 4. 脚本说明

| 文件 | 用途 |
|---|---|
| `setup_dev.cmd` | 查找 64 位 Python 3.11、创建 `.venv`、按约束文件安装开发依赖并自检 |
| `run_recoverhand.cmd` | 启动 Qt Widgets 上位机；首次运行会自动配置环境 |
| `run_emg_monitor.cmd` | 启动独立原始肌电监视器；缺少 Bleak 时只补装 `emg` 可选依赖 |
| `verify_dev.cmd` | 检查 Qt WebEngine/PyQtGraph，运行 pytest、Ruff 和 compileall |
| `tools/package_dev.ps1` | 从源码重新生成干净的开发 ZIP 和 SHA-256 文件 |

默认配置只安装模拟开发所需组件。如果要使用 BrainFlow EEG 可选依赖，或提前配置唯理 BLE sEMG 开发环境，可执行：

```bat
setup_dev.cmd devices
```

这只安装可选 SDK。唯理 sEMG 的只读通知协议已实现于独立监视器，但时间同步 Write 特征、腕部贴位和临床信号质量仍须实机验证；其他真实设备协议、通道映射或安全控制也不会因此自动通过验证。

## 5. 常用开发命令

在开发包根目录打开 PowerShell 或 Windows Terminal：

```powershell
.\.venv\Scripts\python.exe -m recoverhand_host.desktop
.\.venv\Scripts\python.exe -m recoverhand_host.emg_monitor
.\.venv\Scripts\python.exe -m pytest -q
.\.venv\Scripts\python.exe -m ruff check backend tests
.\.venv\Scripts\python.exe -m compileall -q backend tests
```

目录职责：

```text
backend/recoverhand_host/   Python 业务核心、运行时、算法接口、设备抽象与 Qt 桌面界面
tests/                      状态机、设备、存储、API 和桌面冒烟测试
frontend/                   早期 React/FastAPI 兼容性参考，不是默认入口
docs/decision_records/      打包时附带的关键架构决策记录
data/                       首次运行后生成的本机 SQLite 数据，不随包分发
```

## 6. 配置与数据

- Python 依赖范围在 `pyproject.toml`；开发包验证版本在 `constraints-dev-win-py311.txt`。
- 主上位机设备连接档案从“系统设置”页面维护；独立肌电监视器不读写连接档案。
- 模拟运行会在 `data/recoverhand.db` 创建本地 SQLite 文件。
- 独立肌电监视器当前不保存原始信号；关闭窗口后波形缓存随进程释放。
- 更换开发机或需要重建环境时，关闭程序后删除 `.venv`，再运行 `setup_dev.cmd`。不要把真实患者数据放进开发包或提交到源码仓库。

## 7. 常见问题

### 提示未找到 64 位 Python 3.11

安装 Python 3.11 x64，并启用 Python Launcher。用以下命令确认：

```bat
py -3.11 --version
```

### 依赖下载失败

首次安装需要访问 PyPI。检查代理、TLS 证书、单位镜像源和磁盘空间，然后重新运行 `setup_dev.cmd`。脚本可以安全重复执行。

如果错误信息提到 `Windows Long Path` 或某个 PySide6 图片文件不存在，说明解压路径过深。把包移动并重新解压到 `C:\RecoverHand-dev` 或 `D:\RecoverHand-dev`，再执行配置。不要继续复用安装到一半的 `.venv`。

### 程序启动时报 Qt 或 ICU DLL 错误

优先使用 python.org 的独立 Python 3.11，不要在已激活的 Anaconda Prompt 中启动。关闭终端后，从资源管理器双击脚本；必要时删除 `.venv` 后重建。

### 肌电监视器提示 Windows 蓝牙扫描失败

确认 Windows 快捷设置中的蓝牙开关已打开、贴片已安装 CR2025 电池且指示灯慢闪。设备管理器中仅显示蓝牙适配器“正常”并不等于无线电开关已打开；如果仍失败，重新启动蓝牙支持服务或电脑后再试。

### 三维手显示为二维备用或帧率异常

更新显卡驱动，确认没有通过禁用 GPU 的远程桌面环境运行，然后重新启动程序。正常情况下 P03-E 状态显示“3D已绘制”；WebGL2 不可用时程序会明确切换为二维备用，不影响页面继续浏览。

### 如何确认开发包没有损坏

将 ZIP 与同名 `.sha256` 文件放在同一目录，在 PowerShell 中执行：

```powershell
(Get-FileHash .\RecoverHand-dev-v0.2.0-20260914-win64.zip -Algorithm SHA256).Hash
```

结果应与 `.sha256` 文件中的哈希一致。解压后再运行 `verify_dev.cmd` 做代码和依赖自检。
