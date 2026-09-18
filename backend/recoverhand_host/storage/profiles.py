from __future__ import annotations

import json
import sqlite3
import uuid
from datetime import UTC, datetime
from pathlib import Path
from typing import Any


class ProfileStore:
    def __init__(self, database_path: Path) -> None:
        self.database_path = database_path

    def initialize(self) -> None:
        self.database_path.parent.mkdir(parents=True, exist_ok=True)
        with sqlite3.connect(self.database_path) as connection:
            connection.execute(
                """
                CREATE TABLE IF NOT EXISTS connection_profiles (
                    id TEXT PRIMARY KEY,
                    name TEXT NOT NULL,
                    devices_json TEXT NOT NULL,
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL
                )
                """
            )

    def seed_default(self) -> None:
        if self.list():
            return
        self.save(
            name="全模拟联调",
            devices={
                "eeg": {"driver_id": "synthetic_eeg", "config": {"sample_rate": 250, "channel_names": "C3,Cz,C4"}},
                "emg": {"driver_id": "synthetic_emg", "config": {"sample_rate": 250, "simulate_burst": True}},
                "glove": {"driver_id": "simulated_glove", "config": {"initial_position": 512}},
            },
        )

    def save(self, name: str, devices: dict[str, Any], profile_id: str | None = None) -> dict[str, Any]:
        now = datetime.now(UTC).isoformat()
        profile_id = profile_id or str(uuid.uuid4())
        with sqlite3.connect(self.database_path) as connection:
            existing = connection.execute(
                "SELECT created_at FROM connection_profiles WHERE id = ?", (profile_id,)
            ).fetchone()
            created_at = existing[0] if existing else now
            connection.execute(
                """
                INSERT INTO connection_profiles (id, name, devices_json, created_at, updated_at)
                VALUES (?, ?, ?, ?, ?)
                ON CONFLICT(id) DO UPDATE SET
                    name = excluded.name,
                    devices_json = excluded.devices_json,
                    updated_at = excluded.updated_at
                """,
                (profile_id, name.strip(), json.dumps(devices, ensure_ascii=False), created_at, now),
            )
        return self.get(profile_id)

    def list(self) -> list[dict[str, Any]]:
        with sqlite3.connect(self.database_path) as connection:
            rows = connection.execute(
                "SELECT id, name, devices_json, created_at, updated_at FROM connection_profiles ORDER BY updated_at DESC"
            ).fetchall()
        return [self._row(row) for row in rows]

    def get(self, profile_id: str) -> dict[str, Any]:
        with sqlite3.connect(self.database_path) as connection:
            row = connection.execute(
                "SELECT id, name, devices_json, created_at, updated_at FROM connection_profiles WHERE id = ?",
                (profile_id,),
            ).fetchone()
        if row is None:
            raise ValueError("连接档案不存在")
        return self._row(row)

    @staticmethod
    def _row(row: tuple[Any, ...]) -> dict[str, Any]:
        return {
            "id": row[0],
            "name": row[1],
            "devices": json.loads(row[2]),
            "created_at": row[3],
            "updated_at": row[4],
        }
