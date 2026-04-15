from __future__ import annotations

import json
import os
import sqlite3
from datetime import datetime
from pathlib import Path
from typing import Any, Optional


def _default_db_path() -> Path:
    return Path(os.getenv("STOA_STATE_DB") or (Path(__file__).with_name(".stoa_state.db")))


class DeviceStateStore:
    def __init__(self, db_path: Optional[str] = None) -> None:
        self.db_path = Path(db_path) if db_path else _default_db_path()
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self._init_db()

    def _connect(self) -> sqlite3.Connection:
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        return conn

    def _init_db(self) -> None:
        with self._connect() as conn:
            conn.executescript(
                """
                CREATE TABLE IF NOT EXISTS device_records (
                    device_id TEXT PRIMARY KEY,
                    payload_json TEXT NOT NULL,
                    updated_at TEXT NOT NULL
                );
                CREATE TABLE IF NOT EXISTS device_actions (
                    action_id TEXT PRIMARY KEY,
                    device_id TEXT NOT NULL,
                    action_status TEXT NOT NULL,
                    payload_json TEXT NOT NULL,
                    updated_at TEXT NOT NULL
                );
                CREATE TABLE IF NOT EXISTS device_action_queue (
                    device_id TEXT NOT NULL,
                    position INTEGER NOT NULL,
                    action_id TEXT NOT NULL,
                    PRIMARY KEY(device_id, position)
                );
                CREATE TABLE IF NOT EXISTS device_preferences (
                    scope_key TEXT PRIMARY KEY,
                    device_id TEXT NOT NULL,
                    updated_at TEXT NOT NULL
                );
                """
            )
            conn.commit()

    def save_device(self, payload: dict[str, Any]) -> None:
        device_id = payload["device_id"]
        with self._connect() as conn:
            conn.execute(
                """
                INSERT INTO device_records(device_id, payload_json, updated_at)
                VALUES(?, ?, ?)
                ON CONFLICT(device_id) DO UPDATE SET
                    payload_json=excluded.payload_json,
                    updated_at=excluded.updated_at
                """,
                (device_id, json.dumps(payload, ensure_ascii=False), datetime.now().isoformat()),
            )
            conn.commit()

    def delete_device(self, device_id: str) -> None:
        with self._connect() as conn:
            conn.execute("DELETE FROM device_records WHERE device_id = ?", (device_id,))
            conn.commit()

    def load_devices(self) -> dict[str, dict[str, Any]]:
        with self._connect() as conn:
            rows = conn.execute("SELECT device_id, payload_json FROM device_records").fetchall()
        items: dict[str, dict[str, Any]] = {}
        for row in rows:
            try:
                items[row["device_id"]] = json.loads(row["payload_json"])
            except Exception:
                continue
        return items

    def save_action(self, payload: dict[str, Any]) -> None:
        action_id = payload["action_id"]
        with self._connect() as conn:
            conn.execute(
                """
                INSERT INTO device_actions(action_id, device_id, action_status, payload_json, updated_at)
                VALUES(?, ?, ?, ?, ?)
                ON CONFLICT(action_id) DO UPDATE SET
                    device_id=excluded.device_id,
                    action_status=excluded.action_status,
                    payload_json=excluded.payload_json,
                    updated_at=excluded.updated_at
                """,
                (
                    action_id,
                    payload["device_id"],
                    payload.get("status") or "",
                    json.dumps(payload, ensure_ascii=False),
                    datetime.now().isoformat(),
                ),
            )
            conn.commit()

    def load_actions(self) -> dict[str, dict[str, Any]]:
        with self._connect() as conn:
            rows = conn.execute("SELECT action_id, payload_json FROM device_actions").fetchall()
        items: dict[str, dict[str, Any]] = {}
        for row in rows:
            try:
                items[row["action_id"]] = json.loads(row["payload_json"])
            except Exception:
                continue
        return items

    def replace_queue(self, device_id: str, action_ids: list[str]) -> None:
        with self._connect() as conn:
            conn.execute("DELETE FROM device_action_queue WHERE device_id = ?", (device_id,))
            for index, action_id in enumerate(action_ids):
                conn.execute(
                    "INSERT INTO device_action_queue(device_id, position, action_id) VALUES(?, ?, ?)",
                    (device_id, index, action_id),
                )
            conn.commit()

    def delete_queue(self, device_id: str) -> None:
        with self._connect() as conn:
            conn.execute("DELETE FROM device_action_queue WHERE device_id = ?", (device_id,))
            conn.commit()

    def load_queues(self) -> dict[str, list[str]]:
        with self._connect() as conn:
            rows = conn.execute(
                "SELECT device_id, position, action_id FROM device_action_queue ORDER BY device_id, position"
            ).fetchall()
        queues: dict[str, list[str]] = {}
        for row in rows:
            queues.setdefault(row["device_id"], []).append(row["action_id"])
        return queues

    def save_preference(self, scope_key: str, device_id: str) -> None:
        with self._connect() as conn:
            conn.execute(
                """
                INSERT INTO device_preferences(scope_key, device_id, updated_at)
                VALUES(?, ?, ?)
                ON CONFLICT(scope_key) DO UPDATE SET
                    device_id=excluded.device_id,
                    updated_at=excluded.updated_at
                """,
                (scope_key, device_id, datetime.now().isoformat()),
            )
            conn.commit()

    def load_preferences(self) -> dict[str, str]:
        with self._connect() as conn:
            rows = conn.execute("SELECT scope_key, device_id FROM device_preferences").fetchall()
        return {row["scope_key"]: row["device_id"] for row in rows}

    def delete_preferences_for_device(self, device_id: str) -> None:
        with self._connect() as conn:
            conn.execute("DELETE FROM device_preferences WHERE device_id = ?", (device_id,))
            conn.commit()
