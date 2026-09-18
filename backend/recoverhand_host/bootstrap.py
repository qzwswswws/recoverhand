from __future__ import annotations

from recoverhand_host.devices.eeg_cyton import BrainFlowCytonDriver
from recoverhand_host.devices.glove_http import BenchHttpGloveDriver
from recoverhand_host.devices.manager import DeviceManager
from recoverhand_host.devices.registry import DriverRegistry
from recoverhand_host.devices.simulated import (
    SimulatedGloveDriver,
    SyntheticEegDriver,
    SyntheticEmgDriver,
)
from recoverhand_host.devices.sy_hr12 import SyHr12GloveDriver
from recoverhand_host.devices.waveletech_emg import WaveletechEmgDriver
from recoverhand_host.models import DeviceKind, DriverInfo


def _number(title: str, default: float, minimum: float | None = None) -> dict:
    schema = {"type": "number", "title": title, "default": default}
    if minimum is not None:
        schema["minimum"] = minimum
    return schema


def build_registry() -> DriverRegistry:
    registry = DriverRegistry()
    registry.register(
        DriverInfo(
            id="synthetic_eeg",
            kind=DeviceKind.EEG,
            display_name="模拟 EEG",
            description="生成 μ 节律样例，用于不接设备时联调。",
            maturity="simulator",
            config_schema={
                "type": "object",
                "properties": {
                    "sample_rate": {"type": "integer", "title": "采样率 (Hz)", "default": 250, "minimum": 100},
                    "channel_names": {"type": "string", "title": "通道名（逗号分隔）", "default": "C3,Cz,C4"},
                },
            },
        ),
        SyntheticEegDriver,
    )
    registry.register(
        DriverInfo(
            id="brainflow_cyton",
            kind=DeviceKind.EEG,
            display_name="OpenBCI Cyton / BrainFlow",
            description="真实 8 通道脑电；BrainFlow 采集 + MIdemo μ 带 ERD 意图基线。",
            maturity="experimental",
            config_schema={
                "type": "object",
                "properties": {
                    "serial_port": {"type": "string", "title": "串口", "default": "COM10"},
                    "board_id": {"type": "integer", "title": "BrainFlow Board ID", "default": 0},
                },
                "required": ["serial_port"],
            },
        ),
        BrainFlowCytonDriver,
    )
    registry.register(
        DriverInfo(
            id="synthetic_emg",
            kind=DeviceKind.EMG,
            display_name="模拟单通道 sEMG",
            description="模拟腕部附近双电极贴片的差分信号和活动包络。",
            maturity="simulator",
            config_schema={
                "type": "object",
                "properties": {
                    "sample_rate": {"type": "integer", "title": "采样率 (Hz)", "default": 250, "minimum": 100},
                    "simulate_burst": {"type": "boolean", "title": "模拟肌肉活动段", "default": True},
                },
            },
        ),
        SyntheticEmgDriver,
    )
    registry.register(
        DriverInfo(
            id="ble_bipolar_emg",
            kind=DeviceKind.EMG,
            display_name="唯理 BLE 双电极 sEMG 贴片",
            description="真实单通道双电极贴片；支持原始样本落盘，可进入康复会话。",
            maturity="experimental",
            config_schema={
                "type": "object",
                "properties": {
                    "device_name_filter": {
                        "type": "string",
                        "title": "蓝牙名称筛选",
                        "default": "EMG",
                    },
                    "device_identifier": {
                        "type": "string",
                        "title": "设备标识/地址（可选）",
                        "default": "",
                    },
                    "scan_timeout_seconds": _number("扫描超时 (s)", 5.0, 1.0),
                    "connect_timeout_seconds": _number("连接超时 (s)", 10.0, 1.0),
                    "stream_start_timeout_seconds": _number("首包超时 (s)", 3.0, 0.5),
                    "preview_seconds": _number("预览窗口 (s)", 1.0, 0.1),
                },
            },
        ),
        WaveletechEmgDriver,
    )
    registry.register(
        DriverInfo(
            id="simulated_glove",
            kind=DeviceKind.GLOVE,
            display_name="模拟辅助手套",
            description="固定在释放状态的手套模拟器，不产生真实动作。",
            maturity="simulator",
            config_schema={
                "type": "object",
                "properties": {
                    "initial_position": {"type": "integer", "title": "模拟初始位置", "default": 512, "minimum": 0, "maximum": 1023},
                },
            },
        ),
        SimulatedGloveDriver,
    )
    registry.register(
        DriverInfo(
            id="bench_http_glove",
            kind=DeviceKind.GLOVE,
            display_name="ESP32 手套台架 HTTP（实验性）",
            description="读取 /api/status 并下发动作命令；armed 时自动维持心跳租约。",
            maturity="experimental",
            config_schema={
                "type": "object",
                "properties": {
                    "base_url": {"type": "string", "title": "设备地址", "default": "http://192.168.4.1"},
                    "timeout_seconds": _number("读取超时 (s)", 1.2, 0.2),
                    "heartbeat_interval_seconds": _number("心跳间隔 (s)", 0.5, 0.1),
                },
                "required": ["base_url"],
            },
        ),
        BenchHttpGloveDriver,
    )
    registry.register(
        DriverInfo(
            id="sy_hr12_glove",
            kind=DeviceKind.GLOVE,
            display_name="SY-HR12 蓝牙康复手套",
            description="真实蓝牙手套（AE30 控制通道）：模式/五指/时长/力量/开始暂停/软关机。",
            maturity="experimental",
            config_schema={
                "type": "object",
                "properties": {
                    "device_name": {
                        "type": "string",
                        "title": "设备名",
                        "default": "SY-HR12-15",
                    },
                    "device_address": {
                        "type": "string",
                        "title": "设备地址（可选）",
                        "default": "00:FB:18:00:64:0B",
                    },
                    "scan_timeout_seconds": _number("扫描超时 (s)", 6.0, 1.0),
                    "connect_timeout_seconds": _number("连接超时 (s)", 12.0, 1.0),
                    "poll_interval_seconds": _number("状态轮询间隔 (s)", 0.75, 0.1),
                    "write_delay_seconds": _number("命令间隔 (s)", 0.05, 0.0),
                },
            },
        ),
        SyHr12GloveDriver,
    )
    return registry


def build_device_manager() -> DeviceManager:
    return DeviceManager(build_registry())
