import asyncio

from httpx import ASGITransport, AsyncClient
from recoverhand_host.main import app, manager, profile_store


def test_settings_api_vertical_slice(tmp_path) -> None:
    async def scenario() -> None:
        profile_store.database_path = tmp_path / "api.db"
        profile_store.initialize()
        profile_store.seed_default()
        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            assert (await client.get("/healthz")).json() == {"status": "ok"}

            drivers = (await client.get("/api/v1/devices/drivers")).json()
            assert {driver["id"] for driver in drivers} >= {
                "synthetic_eeg",
                "synthetic_emg",
                "simulated_glove",
                "brainflow_cyton",
                "ble_bipolar_emg",
                "bench_http_glove",
            }
            emg_driver = next(driver for driver in drivers if driver["id"] == "ble_bipolar_emg")
            assert emg_driver["available"] is True
            assert emg_driver["maturity"] == "experimental"

            profiles = (await client.get("/api/v1/connection-profiles")).json()
            assert any(profile["name"] == "全模拟联调" for profile in profiles)

            simulated = {
                "eeg": ("synthetic_eeg", {"sample_rate": 250, "channel_names": "C3,Cz,C4"}),
                "emg": ("synthetic_emg", {"sample_rate": 250, "simulate_burst": True}),
                "glove": ("simulated_glove", {"initial_position": 512}),
            }
            for kind, (driver_id, config) in simulated.items():
                response = await client.post(
                    f"/api/v1/devices/{kind}/connect",
                    json={"driver_id": driver_id, "config": config},
                )
                assert response.status_code == 200, response.text
                assert response.json()["state"] == "data_valid"

                preview = await client.get(f"/api/v1/devices/{kind}/preview")
                assert preview.status_code == 200, preview.text
                assert preview.json()["kind"] == kind

            state = (await client.get("/api/v1/devices/state")).json()
            assert all(slot["state"] == "data_valid" for slot in state["devices"].values())
        await manager.shutdown()

    asyncio.run(scenario())
