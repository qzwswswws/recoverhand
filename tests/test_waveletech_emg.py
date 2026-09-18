import asyncio
import struct
from dataclasses import dataclass

import pytest
from recoverhand_host.devices.waveletech_emg import (
    NOTIFY_UUID,
    SERVICE_UUID,
    UNVERIFIED_TIME_WRITE_UUID,
    EmgDataPacket,
    EmgProtocolError,
    EmgStatusPacket,
    EmgTimePacket,
    WaveletechEmgDriver,
    parse_notification,
)


def encode_int24(value: int) -> bytes:
    return value.to_bytes(3, byteorder="big", signed=True)


def data_packet(sequence: int, values: list[int]) -> bytes:
    assert len(values) == 6
    return bytes([0xD3, sequence]) + b"".join(encode_int24(value) for value in values)


def status_packet(sequence: int) -> bytes:
    payload = bytearray(20)
    payload[0] = 0xC0
    payload[1] = sequence
    payload[2] = 87
    payload[3:9] = bytes.fromhex("010203040506")
    payload[9:11] = (3012).to_bytes(2, "big")
    payload[11:13] = (-25).to_bytes(2, "big", signed=True)
    payload[16:20] = (0xF1234567).to_bytes(4, "big")
    return bytes(payload)


def test_parse_emg_data_packet_uses_signed_big_endian_and_microvolts() -> None:
    packet = parse_notification(data_packet(9, [0, 60, -60, 120, -120, 12_345]))

    assert isinstance(packet, EmgDataPacket)
    assert packet.sequence == 9
    assert packet.samples_uv == pytest.approx((0, 1, -1, 2, -2, 205.75))


def test_parse_status_and_time_packets() -> None:
    status = parse_notification(status_packet(10))
    time_packet = parse_notification(b"TIME000001A056048660")

    assert isinstance(status, EmgStatusPacket)
    assert status.sequence == 10
    assert status.battery_percent == 87
    assert status.mac == "01:02:03:04:05:06"
    assert status.battery_voltage_mv == 3012
    assert status.temperature_c == -2.5
    assert status.timestamp_low32_ms == 0xF1234567
    assert isinstance(time_packet, EmgTimePacket)
    assert time_packet.timestamp_ms == int("000001A056048660", 16)


def test_parse_rejects_unknown_or_malformed_packets() -> None:
    with pytest.raises(EmgProtocolError, match="20 字节"):
        parse_notification(b"short")
    with pytest.raises(EmgProtocolError, match="未知通知包类型"):
        parse_notification(bytes([0xAA]) + bytes(19))
    with pytest.raises(EmgProtocolError, match="TIME 响应"):
        parse_notification(b"TIME" + b"GGGGGGGGGGGGGGGG")


@dataclass
class FakeDevice:
    address: str = "AA:BB:CC:DD:EE:FF"
    name: str = "EMGR-0036"


@dataclass
class FakeAdvertisement:
    local_name: str = "EMGR-0036"
    rssi: int = -48
    manufacturer_data: dict[int, bytes] | None = None

    def __post_init__(self) -> None:
        if self.manufacturer_data is None:
            self.manufacturer_data = {1: bytes.fromhex("AABBCCDDEEFF")}


class FakeScanner:
    async def discover(
        self, timeout: float, return_adv: bool
    ) -> dict[str, tuple[FakeDevice, FakeAdvertisement]]:
        assert timeout > 0
        assert return_adv is True
        return {"device": (FakeDevice(), FakeAdvertisement())}


class UnavailableScanner:
    async def discover(self, timeout: float, return_adv: bool) -> object:
        raise OSError(22, "device not ready", None, -2147020577)


class FakeService:
    def get_characteristic(self, uuid: str) -> object | None:
        return object() if uuid == NOTIFY_UUID else None


class FakeServices:
    def get_service(self, uuid: str) -> FakeService | None:
        return FakeService() if uuid == SERVICE_UUID else None

    def get_characteristic(self, uuid: str) -> object | None:
        return object() if uuid == UNVERIFIED_TIME_WRITE_UUID else None


class FakeClient:
    def __init__(self, device: FakeDevice, **kwargs: object) -> None:
        self.device = device
        self.disconnected_callback = kwargs["disconnected_callback"]
        self.is_connected = False
        self.services = FakeServices()
        self.stopped = False

    async def connect(self) -> None:
        self.is_connected = True

    async def disconnect(self) -> None:
        self.is_connected = False

    async def start_notify(self, uuid: str, callback: object) -> None:
        assert uuid == NOTIFY_UUID
        callback(None, bytearray(data_packet(20, [0, 60, -60, 120, -120, 180])))
        callback(None, bytearray(status_packet(21)))
        callback(None, bytearray(data_packet(22, [180, 120, 60, 0, -60, -120])))

    async def stop_notify(self, uuid: str) -> None:
        assert uuid == NOTIFY_UUID
        self.stopped = True


def test_driver_discovers_streams_and_tracks_interleaved_sequence_numbers() -> None:
    async def scenario() -> None:
        driver = WaveletechEmgDriver(scanner=FakeScanner(), client_factory=FakeClient)
        config = {
            "device_name_filter": "0036",
            "scan_timeout_seconds": 0.1,
            "stream_start_timeout_seconds": 0.5,
            "preview_seconds": 1.0,
        }
        discovered = await driver.discover(config)
        assert discovered == [
            {
                "id": "AA:BB:CC:DD:EE:FF",
                "name": "EMGR-0036",
                "rssi": -48,
                "manufacturer_data": {"1": "AABBCCDDEEFF"},
            }
        ]

        await driver.connect(config)
        await driver.start_stream()
        health = await driver.health()
        preview = await driver.preview()

        assert health.transport_ok is True
        assert health.stream_ok is True
        assert health.signal_ok is True
        assert health.time_sync_ok is False
        assert preview["sample_rate"] == 250.0
        assert preview["unit"] == "µV"
        assert len(preview["samples"][0]) == 12
        assert preview["battery_percent"] == 87
        assert preview["packet_loss"] == 0.0
        assert preview["diagnostics"]["received_sequence_packets"] == 3
        assert preview["time_write_characteristic_detected"] is True

        # 状态包仍在到达时也不能掩盖肌电数据流停止。
        driver._last_emg_monotonic = 0.0
        assert (await driver.health()).stream_ok is False

        await driver.disconnect()

    asyncio.run(scenario())


def test_driver_turns_windows_adapter_error_into_operator_message() -> None:
    async def scenario() -> None:
        driver = WaveletechEmgDriver(scanner=UnavailableScanner(), client_factory=FakeClient)
        with pytest.raises(RuntimeError, match="请确认蓝牙已开启"):
            await driver.discover({"scan_timeout_seconds": 0.1})

    asyncio.run(scenario())


def test_driver_records_raw_samples_to_file(tmp_path) -> None:
    async def scenario() -> None:
        driver = WaveletechEmgDriver(scanner=FakeScanner(), client_factory=FakeClient)
        config = {
            "device_name_filter": "0036",
            "scan_timeout_seconds": 0.1,
            "stream_start_timeout_seconds": 0.5,
            "preview_seconds": 1.0,
        }
        raw_path = tmp_path / "emg.raw"
        await driver.connect(config)
        driver.start_raw_recording(raw_path)
        await driver.start_stream()

        for _ in range(10):
            if len(driver._samples) >= 12:
                break
            await asyncio.sleep(0)

        driver.stop_raw_recording()
        assert len(driver._samples) == 12
        data = raw_path.read_bytes()
        assert len(data) == 12 * 4  # 12 个 float32
        samples = struct.unpack("<12f", data)
        assert samples[0] == pytest.approx(0.0)
        assert samples[5] == pytest.approx(3.0)
        await driver.disconnect()

    asyncio.run(scenario())
