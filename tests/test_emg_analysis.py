from recoverhand_host.devices.emg_analysis import EnvelopeEmgAnalyzer


def test_envelope_analyzer_detects_burst() -> None:
    analyzer = EnvelopeEmgAnalyzer(threshold_uv=10.0)
    analyzer.update({"samples": [[0.0] * 50], "sample_rate": 250})
    assert analyzer.responded() is False
    analyzer.update({"samples": [[100.0] * 50], "sample_rate": 250})
    assert analyzer.responded() is True
    assert analyzer.metrics()["responded"] is True


def test_envelope_analyzer_reset() -> None:
    analyzer = EnvelopeEmgAnalyzer(threshold_uv=10.0)
    analyzer.update({"samples": [[0.0] * 50], "sample_rate": 250})
    analyzer.update({"samples": [[100.0] * 50], "sample_rate": 250})
    assert analyzer.responded() is True
    analyzer.reset()
    assert analyzer.responded() is False
    assert analyzer.metrics()["baseline_rms_uv"] is None
