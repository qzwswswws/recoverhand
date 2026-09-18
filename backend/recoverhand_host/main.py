from __future__ import annotations

from contextlib import asynccontextmanager
from pathlib import Path
from typing import Any

from fastapi import FastAPI, HTTPException, WebSocket, WebSocketDisconnect
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field

from recoverhand_host.bootstrap import build_device_manager
from recoverhand_host.models import DeviceKind
from recoverhand_host.storage.profiles import ProfileStore

HOST_APP_ROOT = Path(__file__).resolve().parents[2]
manager = build_device_manager()
profile_store = ProfileStore(HOST_APP_ROOT / "data" / "recoverhand.db")


@asynccontextmanager
async def lifespan(_: FastAPI):
    profile_store.initialize()
    profile_store.seed_default()
    yield
    await manager.shutdown()


app = FastAPI(
    title="RecoverHand Host API",
    version="0.1.0",
    description="EEG、单通道 sEMG 与辅助手套的本地连接和状态服务。",
    lifespan=lifespan,
)
app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://127.0.0.1:5173", "http://localhost:5173"],
    allow_credentials=False,
    allow_methods=["*"],
    allow_headers=["*"],
)


class DeviceRequest(BaseModel):
    driver_id: str
    config: dict[str, Any] = Field(default_factory=dict)


class ProfileRequest(BaseModel):
    id: str | None = None
    name: str
    devices: dict[str, Any]


class ProfileValidationRequest(BaseModel):
    devices: dict[str, Any]


class SettingsLockRequest(BaseModel):
    locked: bool


def _bad_request(exc: Exception) -> HTTPException:
    return HTTPException(status_code=400, detail=str(exc))


@app.get("/healthz")
async def healthz() -> dict[str, str]:
    return {"status": "ok"}


@app.get("/api/v1/devices/drivers")
async def list_drivers(kind: DeviceKind | None = None) -> list[dict[str, Any]]:
    return [info.to_dict() for info in manager.registry.list(kind)]


@app.get("/api/v1/devices/state")
async def device_state() -> dict[str, Any]:
    return manager.snapshot()


@app.post("/api/v1/devices/{kind}/discover")
async def discover(kind: DeviceKind, request: DeviceRequest) -> dict[str, Any]:
    try:
        return await manager.discover(kind, request.driver_id, request.config)
    except Exception as exc:
        raise _bad_request(exc) from exc


@app.post("/api/v1/devices/{kind}/connect")
async def connect(kind: DeviceKind, request: DeviceRequest) -> dict[str, Any]:
    try:
        return await manager.connect(kind, request.driver_id, request.config)
    except Exception as exc:
        raise _bad_request(exc) from exc


@app.post("/api/v1/devices/{kind}/disconnect")
async def disconnect(kind: DeviceKind) -> dict[str, Any]:
    try:
        return await manager.disconnect(kind)
    except Exception as exc:
        raise _bad_request(exc) from exc


@app.get("/api/v1/devices/{kind}/health")
async def device_health(kind: DeviceKind) -> dict[str, Any]:
    return manager.snapshot()["devices"][kind.value]["health"]


@app.get("/api/v1/devices/{kind}/preview")
async def preview(kind: DeviceKind) -> dict[str, Any]:
    try:
        return await manager.preview(kind)
    except Exception as exc:
        raise _bad_request(exc) from exc


@app.post("/api/v1/settings-lock")
async def settings_lock(request: SettingsLockRequest) -> dict[str, Any]:
    return manager.set_settings_locked(request.locked)


@app.get("/api/v1/connection-profiles")
async def list_profiles() -> list[dict[str, Any]]:
    return profile_store.list()


@app.get("/api/v1/connection-profiles/{profile_id}")
async def get_profile(profile_id: str) -> dict[str, Any]:
    try:
        return profile_store.get(profile_id)
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


@app.post("/api/v1/connection-profiles")
async def save_profile(request: ProfileRequest) -> dict[str, Any]:
    validation = manager.validate_profile(request.devices)
    if not validation["valid"]:
        raise HTTPException(status_code=422, detail=validation)
    if not request.name.strip():
        raise HTTPException(status_code=422, detail="档案名称不能为空")
    return profile_store.save(request.name, request.devices, request.id)


@app.post("/api/v1/connection-profiles/validate")
async def validate_profile(request: ProfileValidationRequest) -> dict[str, Any]:
    return manager.validate_profile(request.devices)


@app.websocket("/ws/v1/device-state")
async def device_state_socket(websocket: WebSocket) -> None:
    await websocket.accept()
    queue = manager.subscribe()
    try:
        await websocket.send_json(manager.snapshot())
        while True:
            await websocket.send_json(await queue.get())
    except WebSocketDisconnect:
        pass
    finally:
        manager.unsubscribe(queue)


frontend_dist = HOST_APP_ROOT / "frontend" / "dist"
if frontend_dist.exists():
    app.mount("/", StaticFiles(directory=frontend_dist, html=True), name="frontend")
