from recoverhand_host.storage.profiles import ProfileStore


def test_profile_store_round_trip(tmp_path) -> None:
    store = ProfileStore(tmp_path / "profiles.db")
    store.initialize()
    saved = store.save(
        "台架开发",
        {
            "eeg": {"driver_id": "synthetic_eeg", "config": {}},
            "emg": {"driver_id": "synthetic_emg", "config": {}},
            "glove": {"driver_id": "bench_http_glove", "config": {"base_url": "http://192.168.4.1"}},
        },
    )
    loaded = store.get(saved["id"])
    assert loaded["name"] == "台架开发"
    assert loaded["devices"]["glove"]["driver_id"] == "bench_http_glove"


def test_default_profile_is_seeded_only_once(tmp_path) -> None:
    store = ProfileStore(tmp_path / "profiles.db")
    store.initialize()
    store.seed_default()
    store.seed_default()
    profiles = store.list()
    assert len(profiles) == 1
    assert profiles[0]["name"] == "全模拟联调"
