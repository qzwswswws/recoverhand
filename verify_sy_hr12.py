"""验证 SY-HR12 蓝牙手套的真实连接与状态读回。

默认只读：扫描、连接、健康检查、读取状态。加 ``--send-pause`` 才会发一条
「暂停」命令验证写通道。安全约束：机制未卸载时不要发送任何运动命令。
"""

from __future__ import annotations

import argparse
import asyncio
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent / "backend"))

from recoverhand_host.devices.sy_hr12 import SyHr12GloveDriver
from recoverhand_host.models import GloveCommand


async def _run(send_pause: bool) -> int:
    driver = SyHr12GloveDriver()
    config = {
        "device_name": "SY-HR12-15",
        "device_address": "00:FB:18:00:64:0B",
        "scan_timeout_seconds": 6.0,
        "connect_timeout_seconds": 12.0,
        "poll_interval_seconds": 0.75,
    }

    print("== 1. 扫描 ==")
    try:
        devices = await driver.discover(config)
    except Exception as exc:  # noqa: BLE001
        print(f"  扫描失败：{exc}")
        return 1
    if devices:
        for device in devices:
            print(f"  找到 {device['name']} ({device['id']}) rssi={device['rssi']}")
    else:
        print("  未扫描到；将直接按地址/名称连接")

    print("== 2. 连接 ==")
    try:
        await driver.connect(config)
    except Exception as exc:  # noqa: BLE001
        print(f"  连接失败：{exc}")
        return 1
    print("  已连接")

    print("== 3. 健康状态 ==")
    health = await driver.health()
    print(
        f"  transport={health.transport_ok} stream={health.stream_ok} "
        f"signal={health.signal_ok} control={health.control_ready}"
    )
    print(f"  原因：{health.reason}")

    print("== 4. 读取状态 ==")
    await driver.start_stream()
    await asyncio.sleep(1.6)  # 等状态轮询填充
    try:
        preview = await driver.preview()
    except Exception as exc:  # noqa: BLE001
        print(f"  读状态失败：{exc}")
        await driver.disconnect()
        return 1
    print(f"  固件：{preview.get('firmware')}")
    print(f"  模式：{preview.get('mode_label')}（值 {preview.get('mode')}）")
    print(f"  手指：{[_f for _f in preview.get('fingers', [])]}")
    print(f"  运行中：{preview.get('running')}")
    print(f"  力量：屈曲 {preview.get('flexion_force')} / 伸展 {preview.get('extension_force')}")
    print(f"  时长：屈曲 {preview.get('flexion_duration')} / 伸展 {preview.get('extension_duration')}")

    if send_pause:
        print("== 5. 发送『暂停』（非运动） ==")
        ack = await driver.command(
            GloveCommand(
                command_id="verify:pause",
                action="pause",
                trajectory_profile="verify",
                assist_level=0.0,
                hold_ms=0,
                lease_id="verify",
                payload={},
            )
        )
        print(f"  结果：ok={ack.ok} fault={ack.fault_code}")

    await driver.stop_stream()
    await driver.disconnect()
    print("== 已断开，验证完成 ==")
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(description="验证 SY-HR12 蓝牙手套")
    parser.add_argument("--send-pause", action="store_true", help="额外发一条『暂停』验证写通道")
    args = parser.parse_args()
    return asyncio.run(_run(args.send_pause))


if __name__ == "__main__":
    raise SystemExit(main())
