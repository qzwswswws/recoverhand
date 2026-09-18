import asyncio
import json
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from typing import Any

from recoverhand_host.devices.glove_http import (
    BenchHttpGloveDriver,
    build_command_body,
    interpret_ack,
)
from recoverhand_host.models import GloveCommand


def _cmd(action: str, **kwargs: Any) -> GloveCommand:
    return GloveCommand(
        command_id="c1",
        action=action,
        trajectory_profile="",
        assist_level=float(kwargs.get("assist_level", 0.0)),
        hold_ms=0,
        lease_id="l1",
        payload=kwargs.get("payload", {}),
    )


# ---- 纯函数：命令映射 ----
def test_build_command_body_maps_actions() -> None:
    assert build_command_body("group", 0.0) == "group:0"
    assert build_command_body("group", 0.5) == "group:50"
    assert build_command_body("group", 1.0) == "group:100"
    assert build_command_body("group_arm") == "group_arm:POWER6V5A"
    assert build_command_body("jog", payload={"delta": -3}) == "jog-3"
    assert build_command_body("select", payload={"id": 4}) == "select:4"
    assert build_command_body("setid", payload={"old": 1, "new": 2}) == "setid:1:2:ONLYONE"


def test_interpret_ack_arm_and_release() -> None:
    assert interpret_ack("arm", {"armed": True, "mode": "single", "message": "ok"}) == (True, None)
    ok, fault = interpret_ack("arm", {"armed": False, "mode": "safe", "message": "启用失败"})
    assert ok is False and fault == "启用失败"
    assert interpret_ack("release", {"all_released": True})[0] is True
    assert interpret_ack("release", {"all_released": False, "message": "未确认"})[0] is False


# ---- 固件模拟器：供 HTTP 集成测试 ----
class _FirmwareState:
    def __init__(self) -> None:
        self.armed = False
        self.mode = "safe"
        self.online_count = 5
        self.all_released = True
        self.group_requested = 0
        self.message = "ready"


def _status(state: _FirmwareState) -> dict[str, Any]:
    return {
        "armed": state.armed,
        "mode": state.mode,
        "online_count": state.online_count,
        "all_released": state.all_released,
        "group_requested": state.group_requested,
        "message": state.message,
        "servos": [],
    }


class _Handler(BaseHTTPRequestHandler):
    state: _FirmwareState

    def do_GET(self) -> None:
        if self.path == "/api/status":
            self._reply(_status(self.state))

    def do_POST(self) -> None:
        if self.headers.get("X-Hand-Control") != "1":
            self.send_response(400)
            self.end_headers()
            return
        length = int(self.headers.get("Content-Length", 0))
        body = self.rfile.read(length).decode()
        self._apply(body)
        self._reply(_status(self.state))

    def _apply(self, body: str) -> None:
        state = self.state
        if body == "arm":
            state.armed, state.mode, state.message = True, "single", "已启用"
        elif body == "group_arm:POWER6V5A":
            state.armed, state.mode, state.message = True, "group", "已联动启用"
        elif body.startswith("group:"):
            if state.armed and state.mode == "group":
                state.group_requested = int(body.split(":", 1)[1])
                state.message = "移动中"
            else:
                state.armed, state.mode, state.message = False, "safe", "五指目标被拒绝"
        elif body == "release":
            state.armed, state.mode, state.all_released, state.message = False, "safe", True, "已释放"

    def _reply(self, payload: dict[str, Any]) -> None:
        body = json.dumps(payload).encode()
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, *args: Any) -> None:
        pass


def test_driver_arm_release_and_heartbeat_lease() -> None:
    async def scenario() -> None:
        server = ThreadingHTTPServer(("127.0.0.1", 0), _Handler)
        _Handler.state = _FirmwareState()
        port = server.server_address[1]
        threading.Thread(target=server.serve_forever, daemon=True).start()
        try:
            driver = BenchHttpGloveDriver(heartbeat_interval_s=0.05)
            await driver.connect({"base_url": f"http://127.0.0.1:{port}"})

            arm_ack = await driver.command(_cmd("arm"))
            assert arm_ack.ok is True
            assert driver._lease_active is True

            release_ack = await driver.command(_cmd("release"))
            assert release_ack.ok is True
            assert driver._lease_active is False

            await driver.disconnect()
        finally:
            server.shutdown()
            server.server_close()

    asyncio.run(scenario())


def test_driver_rejects_group_without_arm() -> None:
    async def scenario() -> None:
        server = ThreadingHTTPServer(("127.0.0.1", 0), _Handler)
        _Handler.state = _FirmwareState()
        port = server.server_address[1]
        threading.Thread(target=server.serve_forever, daemon=True).start()
        try:
            driver = BenchHttpGloveDriver()
            await driver.connect({"base_url": f"http://127.0.0.1:{port}"})

            ack = await driver.command(_cmd("group", assist_level=0.5))
            assert ack.ok is False
            assert ack.fault_code == "五指目标被拒绝"

            await driver.disconnect()
        finally:
            server.shutdown()
            server.server_close()

    asyncio.run(scenario())
