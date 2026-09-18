import asyncio

import pytest
from recoverhand_host.devices.sy_hr12 import AE30_SERVICE_UUID, SyHr12GloveDriver
from recoverhand_host.devices.sy_hr12_protocol import (
    QUERY_STATE_FRAME,
    Mode,
    ProtocolError,
    checksum,
    duration_frame,
    finger_frame,
    force_frame,
    mode_frame,
    parse_state_snapshot,
    poweroff_frame,
    run_frame,
    validate_frame,
)
from recoverhand_host.models import GloveCommand


def _cmd(action: str, **payload: object) -> GloveCommand:
    return GloveCommand(
        command_id="c1",
        action=action,
        trajectory_profile="",
        assist_level=0.0,
        hold_ms=0,
        lease_id="l1",
        payload=dict(payload),
    )


# ---- 协议：帧构建与校验 ----
def test_exact_mode_frames() -> None:
    expected = {
        1: "a5 5a 02 07 06 01 f0",
        2: "a5 5a 02 07 06 02 ef",
        3: "a5 5a 02 07 06 03 ee",
        4: "a5 5a 02 07 06 04 ed",
        5: "a5 5a 02 07 06 05 ec",
        6: "a5 5a 02 07 06 06 eb",
    }
    for mode, frame_hex in expected.items():
        assert mode_frame(mode).hex(" ") == frame_hex
        validate_frame(mode_frame(mode))


def test_named_mode() -> None:
    assert mode_frame("passive") == mode_frame(Mode.PASSIVE)
    assert mode_frame("单指") == mode_frame(Mode.SINGLE_FINGER)


def test_parameter_frames() -> None:
    assert duration_frame(3, 4).hex(" ") == "a5 5a 02 08 07 03 04 e8"
    assert force_frame(2, 2).hex(" ") == "a5 5a 02 08 09 02 02 e9"
    with pytest.raises(ProtocolError):
        duration_frame(0, 4)
    with pytest.raises(ProtocolError):
        force_frame(2, 10)


def test_finger_frame() -> None:
    assert finger_frame(["thumb", "index"]).hex(" ") == "a5 5a 02 0b 08 01 01 00 00 00 e9"
    with pytest.raises(ProtocolError):
        finger_frame([])


def test_action_frames() -> None:
    assert run_frame(True).hex(" ") == "a5 5a 02 07 0a 01 ec"
    assert run_frame(False).hex(" ") == "a5 5a 02 07 0a 00 ed"
    assert poweroff_frame().hex(" ") == "a5 5a 02 07 04 00 f3"


def test_query_frame_matches_capture() -> None:
    assert QUERY_STATE_FRAME.hex(" ") == "a5 5a 01 0f 03 04 06 07 08 09 0a 0b 0c 0d 9d"


def test_parse_state_snapshot() -> None:
    frame = bytearray(53)
    frame[:5] = bytes.fromhex("a5 5a 01 35 03")
    frame[22] = 1
    frame[24] = 4
    frame[26:28] = bytes((3, 5))
    frame[29:34] = bytes((1, 0, 1, 0, 1))
    frame[35:37] = bytes((7, 8))
    frame[38] = 1
    frame[-1] = checksum(frame[:-1])
    state = parse_state_snapshot(bytes(frame))
    assert state.powered is True
    assert state.mode == 4
    assert state.flexion_duration == 3
    assert state.extension_duration == 5
    assert state.fingers == ("thumb", "middle", "little")
    assert state.flexion_force == 7
    assert state.extension_force == 8
    assert state.running is True


# ---- 驱动：动作映射 ----
def test_frame_for_maps_actions() -> None:
    assert SyHr12GloveDriver._frame_for(_cmd("mode", mode="passive")) == mode_frame(1)
    assert SyHr12GloveDriver._frame_for(_cmd("fingers", selected=["thumb"])) == finger_frame(["thumb"])
    assert SyHr12GloveDriver._frame_for(_cmd("durations", flexion=3, extension=4)) == duration_frame(3, 4)
    assert SyHr12GloveDriver._frame_for(_cmd("forces", flexion=2, extension=2)) == force_frame(2, 2)
    assert SyHr12GloveDriver._frame_for(_cmd("pause")) == run_frame(False)
    assert SyHr12GloveDriver._frame_for(_cmd("start", confirm=True)) == run_frame(True)
    assert SyHr12GloveDriver._frame_for(_cmd("poweroff", confirm=True)) == poweroff_frame()
    with pytest.raises(ProtocolError):
        SyHr12GloveDriver._frame_for(_cmd("start"))


# ---- 驱动：BLE 连接与命令（假 bleak）----
class _FakeCharacteristic:
    def __init__(self, uuid: str) -> None:
        self.uuid = uuid.lower()


class _FakeService:
    def __init__(self) -> None:
        self.characteristics = [
            _FakeCharacteristic("0000ae01-0000-1000-8000-00805f9b34fb"),
            _FakeCharacteristic("0000ae02-0000-1000-8000-00805f9b34fb"),
        ]


class _FakeServices:
    def get_service(self, uuid: str) -> _FakeService | None:
        return _FakeService() if uuid == AE30_SERVICE_UUID else None


class _FakeDevice:
    address = "00:FB:18:00:64:0B"
    name = "SY-HR12-15"


class _FakeScanner:
    async def discover(self, timeout: float, return_adv: bool) -> dict:
        return {}

    async def find_device_by_address(self, address: str, timeout: float) -> _FakeDevice:
        return _FakeDevice()

    async def find_device_by_name(self, name: str, timeout: float) -> _FakeDevice:
        return _FakeDevice()


class _FakeClient:
    def __init__(self, device: _FakeDevice, disconnected_callback: object = None) -> None:
        self.device = device
        self.disconnected_callback = disconnected_callback
        self.is_connected = False
        self.services = _FakeServices()
        self.writes: list[bytes] = []
        self.notify_callback = None

    async def connect(self, timeout: float | None = None) -> None:
        self.is_connected = True

    async def disconnect(self) -> None:
        self.is_connected = False

    async def start_notify(self, characteristic: object, callback: object) -> None:
        self.notify_callback = callback

    async def write_gatt_char(self, characteristic: object, frame: bytes, response: bool = False) -> None:
        self.writes.append(bytes(frame))


def test_driver_connect_and_command() -> None:
    async def scenario() -> None:
        clients: list[_FakeClient] = []

        def client_factory(device: _FakeDevice, disconnected_callback: object = None) -> _FakeClient:
            client = _FakeClient(device, disconnected_callback)
            clients.append(client)
            return client

        driver = SyHr12GloveDriver(scanner=_FakeScanner(), client_factory=client_factory)
        await driver.connect(
            {"device_name": "SY-HR12-15", "device_address": "00:FB:18:00:64:0B"}
        )
        assert driver._connected is True
        client = clients[0]
        assert len(client.writes) == 2  # QUERY VERSION + QUERY STATE

        ack = await driver.command(_cmd("pause"))
        assert ack.ok is True
        assert client.writes[-1] == run_frame(False)

        health = await driver.health()
        assert health.transport_ok is True
        assert health.control_ready is True

        await driver.disconnect()
        assert driver._connected is False

    asyncio.run(scenario())
