import asyncio

import numpy as np
from recoverhand_host.devices.eeg_cyton import BrainFlowCytonDriver
from recoverhand_host.devices.eeg_signal import (
    DEFAULT_ANALYSIS,
    CausalFilter,
    MiIntentExtractor,
    decode_intent,
)


def test_causal_filter_produces_finite_output() -> None:
    filt = CausalFilter(250.0, DEFAULT_ANALYSIS)
    raw = np.random.default_rng(1).normal(0, 20, size=(500, 8))
    filtered = filt.process(raw)
    assert filtered.shape == raw.shape
    assert np.all(np.isfinite(filtered))


def test_decode_intent_rule() -> None:
    right = decode_intent(-3.0, 0.0, threshold=-0.458, margin=0.5, full_grip_db=3.0)
    assert right["state"] == "right"
    assert right["grip"] > 0.0

    left = decode_intent(0.0, -3.0, threshold=-0.458, margin=0.5, full_grip_db=3.0)
    assert left["state"] == "left"

    uncertain = decode_intent(0.0, 0.0, threshold=-0.458, margin=0.5, full_grip_db=3.0)
    assert uncertain["state"] == "uncertain"
    assert uncertain["grip"] == 0.0


def test_intent_extractor_returns_structured_result() -> None:
    extractor = MiIntentExtractor(fs=250.0)
    raw = np.random.default_rng(0).normal(0, 20, size=(750, 8))
    extractor.push(raw)
    extractor.lock_baseline()
    result = extractor.predict()

    assert set(result) >= {"state", "grip", "laterality_db", "confidence", "method", "model_version"}
    assert result["state"] in {"left", "right", "uncertain"}
    assert 0.0 <= result["grip"] <= 1.0


class _FakeBoardIds:
    CYTON_BOARD = type("Enum", (), {"value": 0})()


class _FakeBoardShim:
    def __init__(self, board_id: int, params: object) -> None:
        self.board_id = board_id
        self.params = params

    def prepare_session(self) -> None:
        pass

    def start_stream(self, samples: int) -> None:
        pass

    def stop_stream(self) -> None:
        pass

    def release_session(self) -> None:
        pass

    def get_current_board_data(self, samples: int) -> np.ndarray:
        return np.zeros((8, samples), dtype=float)

    @staticmethod
    def enable_dev_board_logger() -> None:
        pass

    @staticmethod
    def get_sampling_rate(board_id: int) -> int:
        return 250

    @staticmethod
    def get_eeg_channels(board_id: int) -> list[int]:
        return [0, 1, 2, 3, 4, 5, 6, 7]


class _FakeInputParams:
    serial_port: str = ""


def test_driver_preview_returns_intent_with_fake_brainflow() -> None:
    brainflow = {
        "BoardIds": _FakeBoardIds,
        "BoardShim": _FakeBoardShim,
        "BrainFlowInputParams": _FakeInputParams,
    }

    async def scenario() -> None:
        driver = BrainFlowCytonDriver(brainflow_module=brainflow)
        await driver.connect({"serial_port": "COM10", "board_id": 0})
        await driver.start_stream()
        preview = await driver.preview()
        assert preview["kind"] == "eeg"
        assert preview["sample_rate"] == 250.0
        assert "intent" in preview
        assert preview["intent"]["state"] == "uncertain"
        await driver.disconnect()

    asyncio.run(scenario())
