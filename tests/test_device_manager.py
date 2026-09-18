import asyncio

import pytest
from recoverhand_host.bootstrap import build_device_manager, build_registry
from recoverhand_host.models import ConnectionState, DeviceKind, GloveCommand


def test_simulated_devices_can_complete_connection_lifecycle() -> None:
    async def scenario() -> None:
        manager = build_device_manager()
        cases = [
            (DeviceKind.EEG, "synthetic_eeg", {"sample_rate": 250, "channel_names": "C3,Cz,C4"}),
            (DeviceKind.EMG, "synthetic_emg", {"sample_rate": 250, "simulate_burst": True}),
            (DeviceKind.GLOVE, "simulated_glove", {"initial_position": 512}),
        ]
        for kind, driver_id, config in cases:
            discovered = await manager.discover(kind, driver_id, config)
            assert discovered["state"] == ConnectionState.DISCOVERED.value
            connected = await manager.connect(kind, driver_id, config)
            assert connected["state"] == ConnectionState.DATA_VALID.value
            assert connected["health"]["transport_ok"] is True
            preview = await manager.preview(kind)
            assert preview["kind"] == kind.value
            if kind == DeviceKind.GLOVE:
                assert preview["pose"]["actual_flexion"] == [0.0] * 5
                assert "不是手指角度测量" in preview["pose"]["mapping"]
        await manager.shutdown()

    asyncio.run(scenario())


def test_waveletech_emg_driver_is_available_to_main_session() -> None:
    registry = build_registry()
    info = registry.info("ble_bipolar_emg")

    assert info.available is True
    assert info.maturity == "experimental"
    assert info.config_schema["properties"]["device_name_filter"]["default"] == "EMG"
    driver = registry.create("ble_bipolar_emg")
    assert driver.kind == DeviceKind.EMG


def test_settings_lock_prevents_connection_changes() -> None:
    async def scenario() -> None:
        manager = build_device_manager()
        manager.set_settings_locked(True)
        with pytest.raises(ValueError, match="连接设置已锁定"):
            await manager.connect(DeviceKind.GLOVE, "simulated_glove", {"initial_position": 512})

    asyncio.run(scenario())


def test_profile_validation_requires_one_driver_per_device_kind() -> None:
    manager = build_device_manager()
    validation = manager.validate_profile({"eeg": {"driver_id": "synthetic_eeg", "config": {}}})
    assert validation["valid"] is False
    assert set(validation["errors"]) == {"emg", "glove"}


def test_command_dispatches_to_control_driver() -> None:
    async def scenario() -> None:
        manager = build_device_manager()
        await manager.connect(DeviceKind.GLOVE, "simulated_glove", {"initial_position": 512})
        ack = await manager.command(
            DeviceKind.GLOVE,
            GloveCommand(
                command_id="c1",
                action="group",
                trajectory_profile="",
                assist_level=0.5,
                hold_ms=0,
                lease_id="l1",
            ),
        )
        assert ack.ok is True
        await manager.shutdown()

    asyncio.run(scenario())


def test_command_rejects_non_control_device() -> None:
    async def scenario() -> None:
        manager = build_device_manager()
        await manager.connect(DeviceKind.EEG, "synthetic_eeg", {"sample_rate": 250, "channel_names": "C3,Cz,C4"})
        with pytest.raises(ValueError, match="不支持动作命令"):
            await manager.command(
                DeviceKind.EEG,
                GloveCommand(
                    command_id="c1",
                    action="group",
                    trajectory_profile="",
                    assist_level=0.0,
                    hold_ms=0,
                    lease_id="l1",
                ),
            )
        await manager.shutdown()

    asyncio.run(scenario())
