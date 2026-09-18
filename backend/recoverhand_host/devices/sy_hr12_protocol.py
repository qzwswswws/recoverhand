"""SY-HR12 蓝牙康复手套协议：帧构建、校验与状态解析。

移植自独立虚拟遥控项目 `sy_hr12_remote/sy_hr12/protocol.py`，与本上位机解耦。
帧格式：``A5 5A <kind> <length> <command> <payload...> <checksum>``，
校验和满足「整帧字节和低 8 位 == 0xFF」。
"""

from __future__ import annotations

from collections.abc import Iterable, Mapping
from dataclasses import asdict, dataclass
from enum import IntEnum


class ProtocolError(ValueError):
    pass


class Mode(IntEnum):
    PASSIVE = 1
    MIRROR = 2
    SINGLE_FINGER = 3
    OPPOSITION = 4
    GRASP = 5
    STRETCH = 6


MODE_LABELS = {
    Mode.PASSIVE: "被动",
    Mode.MIRROR: "镜像",
    Mode.SINGLE_FINGER: "单指",
    Mode.OPPOSITION: "对指",
    Mode.GRASP: "拿捏",
    Mode.STRETCH: "牵伸",
}

MODE_ALIASES = {
    "passive": Mode.PASSIVE,
    "被动": Mode.PASSIVE,
    "mirror": Mode.MIRROR,
    "镜像": Mode.MIRROR,
    "single": Mode.SINGLE_FINGER,
    "single_finger": Mode.SINGLE_FINGER,
    "single-finger": Mode.SINGLE_FINGER,
    "单指": Mode.SINGLE_FINGER,
    "opposition": Mode.OPPOSITION,
    "对指": Mode.OPPOSITION,
    "grasp": Mode.GRASP,
    "拿捏": Mode.GRASP,
    "stretch": Mode.STRETCH,
    "牵伸": Mode.STRETCH,
}

FINGERS = ("thumb", "index", "middle", "ring", "little")
FINGER_LABELS = {
    "thumb": "大拇指",
    "index": "食指",
    "middle": "中指",
    "ring": "无名指",
    "little": "小拇指",
}


@dataclass(slots=True)
class DeviceState:
    powered: bool | None = None
    mode: int | None = None
    flexion_duration: int | None = None
    extension_duration: int | None = None
    fingers: tuple[str, ...] = ()
    flexion_force: int | None = None
    extension_force: int | None = None
    running: bool | None = None
    raw_hex: str | None = None

    def to_dict(self) -> dict:
        result = asdict(self)
        if self.mode in Mode._value2member_map_:
            mode = Mode(self.mode)
            result["mode_name"] = mode.name.lower()
            result["mode_label"] = MODE_LABELS[mode]
        else:
            result["mode_name"] = None
            result["mode_label"] = None
        result["fingers"] = list(self.fingers)
        return result


def checksum(data: bytes | bytearray | Iterable[int]) -> int:
    return (0xFF - (sum(data) & 0xFF)) & 0xFF


def build_frame(command: int, payload: Iterable[int] = (), *, kind: int = 0x02) -> bytes:
    values = bytes(payload)
    if not 0 <= command <= 0xFF:
        raise ProtocolError("command must fit in one byte")
    length = 6 + len(values)
    if length > 0xFF:
        raise ProtocolError("frame is too long")
    frame = bytearray((0xA5, 0x5A, kind, length, command))
    frame.extend(values)
    frame.append(checksum(frame))
    return bytes(frame)


def validate_frame(frame: bytes) -> None:
    if len(frame) < 6 or frame[:2] != b"\xA5\x5A":
        raise ProtocolError("invalid frame header")
    if frame[3] != len(frame):
        raise ProtocolError(f"length byte is {frame[3]}, actual length is {len(frame)}")
    if (sum(frame) & 0xFF) != 0xFF:
        raise ProtocolError("checksum mismatch")


def normalize_mode(value: Mode | int | str) -> Mode:
    if isinstance(value, Mode):
        return value
    if isinstance(value, str):
        text = value.strip().lower().replace(" ", "_")
        if text.isdecimal():
            value = int(text)
        else:
            try:
                return MODE_ALIASES[text]
            except KeyError as exc:
                raise ProtocolError(f"unknown mode: {value}") from exc
    try:
        return Mode(int(value))
    except (TypeError, ValueError) as exc:
        raise ProtocolError(f"mode must be 1..6 or a known name, got {value!r}") from exc


def _level(value: int, name: str) -> int:
    value = int(value)
    if not 1 <= value <= 9:
        raise ProtocolError(f"{name} must be in range 1..9")
    return value


def mode_frame(mode: Mode | int | str) -> bytes:
    return build_frame(0x06, (normalize_mode(mode).value,))


def duration_frame(flexion: int, extension: int) -> bytes:
    return build_frame(
        0x07,
        (_level(flexion, "flexion duration"), _level(extension, "extension duration")),
    )


def force_frame(flexion: int, extension: int) -> bytes:
    return build_frame(
        0x09,
        (_level(flexion, "flexion force"), _level(extension, "extension force")),
    )


def normalize_fingers(
    selected: Iterable[str] | Mapping[str, bool],
) -> tuple[str, ...]:
    if isinstance(selected, Mapping):
        unknown = set(selected) - set(FINGERS)
        if unknown:
            raise ProtocolError(f"unknown fingers: {sorted(unknown)}")
        chosen = {name for name, enabled in selected.items() if enabled}
    else:
        chosen = {str(name).strip().lower() for name in selected}
        unknown = chosen - set(FINGERS)
        if unknown:
            raise ProtocolError(f"unknown fingers: {sorted(unknown)}")
    if not chosen:
        raise ProtocolError("at least one finger must be selected")
    return tuple(name for name in FINGERS if name in chosen)


def finger_frame(selected: Iterable[str] | Mapping[str, bool]) -> bytes:
    chosen = set(normalize_fingers(selected))
    return build_frame(0x08, (int(name in chosen) for name in FINGERS))


def run_frame(running: bool) -> bytes:
    return build_frame(0x0A, (int(bool(running)),))


def poweroff_frame() -> bytes:
    return build_frame(0x04, (0,))


QUERY_STATE_FRAME = build_frame(
    0x03, (0x04, 0x06, 0x07, 0x08, 0x09, 0x0A, 0x0B, 0x0C, 0x0D), kind=0x01
)
QUERY_VERSION_FRAME = build_frame(0x00, kind=0x01)


def parse_state_snapshot(frame: bytes) -> DeviceState:
    validate_frame(frame)
    if len(frame) != 53 or frame[:5] != bytes.fromhex("A5 5A 01 35 03"):
        raise ProtocolError("not a 53-byte state snapshot")
    fingers = tuple(name for name, value in zip(FINGERS, frame[29:34]) if value)
    return DeviceState(
        powered=bool(frame[22]),
        mode=frame[24],
        flexion_duration=frame[26],
        extension_duration=frame[27],
        fingers=fingers,
        flexion_force=frame[35],
        extension_force=frame[36],
        running=bool(frame[38]),
        raw_hex=frame.hex(" "),
    )
