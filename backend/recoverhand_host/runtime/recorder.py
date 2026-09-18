from __future__ import annotations

import json
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from recoverhand_host.models import RuntimeEvent


class SessionRecorder:
    """会话记录器：一个会话一个目录，元数据在开始时冻结，事件逐行落盘。

    每次 ``record_event`` 都立即 flush，保证界面退出或进程异常也不丢最后一段
    记录。落盘布局：

    .. code-block:: text

        <root>/<session_id>/
            metadata.json    # 会话开始即冻结（设备档案/算法版本/阈值/参数）
            events.jsonl     # 逐行 RuntimeEvent，顺序即时间顺序
            finalized.json   # 会话结束标记
    """

    def __init__(self, session_id: str, root_dir: Path) -> None:
        self.session_id = session_id
        self.root_dir = Path(root_dir)
        self.session_dir = self.root_dir / session_id
        self._events_file = None
        self._started = False

    def start(self, metadata: dict[str, Any]) -> None:
        if self._started:
            raise RuntimeError("会话记录已开始")
        self.session_dir.mkdir(parents=True, exist_ok=True)
        frozen = {
            **dict(metadata),
            "session_id": self.session_id,
            "started_at": datetime.now(UTC).isoformat(),
        }
        self._write_json(self.session_dir / "metadata.json", frozen)
        self._events_file = (self.session_dir / "events.jsonl").open("a", encoding="utf-8")
        self._started = True

    def record_event(self, event: RuntimeEvent) -> None:
        if not self._started:
            raise RuntimeError("会话记录尚未开始")
        line = json.dumps(event.to_dict(), ensure_ascii=False, separators=(",", ":"))
        self._events_file.write(line + "\n")
        self._events_file.flush()

    def finalize(self) -> None:
        if not self._started:
            return
        self._write_json(
            self.session_dir / "finalized.json",
            {"finalized_at": datetime.now(UTC).isoformat()},
        )
        self._events_file.close()
        self._events_file = None
        self._started = False

    @staticmethod
    def _write_json(path: Path, payload: dict[str, Any]) -> None:
        path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
