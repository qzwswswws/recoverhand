from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from recoverhand_host.models import RuntimeEvent


class SessionReplay:
    """确定性回放：按文件顺序重放 events.jsonl，重复读取得到相同结果。"""

    def __init__(self, session_id: str, root_dir: Path) -> None:
        self.session_id = session_id
        self.session_dir = Path(root_dir) / session_id

    def metadata(self) -> dict[str, Any]:
        return json.loads((self.session_dir / "metadata.json").read_text(encoding="utf-8"))

    def load_events(self) -> list[RuntimeEvent]:
        path = self.session_dir / "events.jsonl"
        if not path.exists():
            return []
        events: list[RuntimeEvent] = []
        for line in path.read_text(encoding="utf-8").splitlines():
            if not line.strip():
                continue
            payload = json.loads(line)
            events.append(
                RuntimeEvent(
                    name=payload["name"],
                    ts_ns=payload["ts_ns"],
                    source=payload["source"],
                    data=payload.get("data", {}),
                )
            )
        return events
