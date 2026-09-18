from recoverhand_host.models import AssistCommand, CommandAck
from recoverhand_host.runtime.event_bus import EventBus
from recoverhand_host.runtime.supervisor import SafetySupervisor


def _command() -> AssistCommand:
    return AssistCommand(
        command_id="c1",
        trial_id="t1",
        action="group",
        assist_level=0.5,
        hold_ms=500,
        lease_id="l1",
    )


def test_authorize_arms_and_emits_event() -> None:
    bus = EventBus()
    supervisor = SafetySupervisor(bus)
    event = supervisor.authorize(_command())
    assert supervisor.armed is True
    assert event.name == "safety.command_authorized"
    assert event.data["lease_id"] == "l1"


def test_failed_ack_forces_release() -> None:
    bus = EventBus()
    supervisor = SafetySupervisor(bus)
    supervisor.authorize(_command())
    event = supervisor.on_command_ack(CommandAck(command_id="c1", ok=False, fault_code="堵转"))
    assert supervisor.armed is False
    assert event is not None
    assert event.name == "safety.release"


def test_ok_ack_renews_heartbeat() -> None:
    bus = EventBus()
    supervisor = SafetySupervisor(bus, heartbeat_timeout_s=0.05)
    supervisor.authorize(_command())
    assert supervisor.on_command_ack(CommandAck(command_id="c1", ok=True)) is None
    assert supervisor.armed is True


def test_heartbeat_prevents_watchdog_release() -> None:
    bus = EventBus()
    supervisor = SafetySupervisor(bus, heartbeat_timeout_s=0.1)
    supervisor.authorize(_command())
    supervisor.note_heartbeat()
    assert supervisor.check_watchdog() is None
    assert supervisor.armed is True


def test_watchdog_releases_after_timeout() -> None:
    now = 0

    def fake_now() -> int:
        return now

    bus = EventBus()
    supervisor = SafetySupervisor(bus, heartbeat_timeout_s=1.0, now=fake_now)
    supervisor.authorize(_command())  # _last_heartbeat_ns = 0
    now = 2_000_000_000  # 推进 2 秒，跨过 1 秒阈值
    event = supervisor.check_watchdog()
    assert event is not None
    assert event.name == "safety.release"
    assert supervisor.armed is False
