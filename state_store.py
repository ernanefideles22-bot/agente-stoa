from __future__ import annotations

import json
import os
import time
from dataclasses import asdict, is_dataclass
from datetime import datetime
from enum import Enum
from pathlib import Path
from typing import Any, Optional

try:
    import redis
except ImportError:
    redis = None


def _default_db_path() -> Path:
    return Path(os.getenv("STOA_STATE_DB") or (Path(__file__).with_name(".stoa_state.db")))


def _serialize_payload(payload: dict[str, Any]) -> str:
    return json.dumps(StateStore._normalize_for_json(payload), ensure_ascii=False)


def _deserialize_payload(serialized: str) -> Optional[dict[str, Any]]:
    try:
        return json.loads(serialized)
    except Exception:
        return None


class StateStore:
    def __init__(self, db_path: Optional[str] = None) -> None:
        self.redis_url = os.getenv("STOA_STATE_REDIS_URL")
        self.redis_client = None
        self.db_path = Path(db_path) if db_path else _default_db_path()
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self.lock_timeout = float(os.getenv("STOA_STATE_LOCK_TIMEOUT", "5"))
        if self.redis_url and redis:
            try:
                self.redis_client = redis.Redis.from_url(self.redis_url, decode_responses=True)
                # Test connection
                self.redis_client.ping()
            except Exception:
                self.redis_client = None
        self.lock_path = self.db_path.with_suffix('.lock')
        self._init_db()

    def _redis_key(self, key: str) -> str:
        return f"stoa:state:{key}"

    def _acquire_lock(self) -> bool:
        """Adquire lock com timeout para evitar deadlocks"""
        if self.redis_client:
            lock_key = self._redis_key("lock")
            timeout_secs = int(self.lock_timeout)
            start_time = time.time()
            while time.time() - start_time < self.lock_timeout:
                if self.redis_client.set(lock_key, "1", nx=True, ex=timeout_secs):
                    return True
                time.sleep(0.05)
            return False

        start_time = time.time()
        while time.time() - start_time < self.lock_timeout:
            try:
                self.lock_path.touch(exist_ok=False)
                return True
            except FileExistsError:
                time.sleep(0.1)
                continue
        return False

    def _release_lock(self) -> None:
        """Libera lock"""
        if self.redis_client:
            try:
                self.redis_client.delete(self._redis_key("lock"))
            except Exception:
                pass
            return
        try:
            self.lock_path.unlink(missing_ok=True)
        except Exception:
            pass

    def _with_lock(self, operation: callable) -> Any:
        """Executa operação com lock"""
        if not self._acquire_lock():
            raise RuntimeError(f"Não foi possível adquirir lock em {self.lock_timeout}s")
        try:
            return operation()
        finally:
            self._release_lock()

    def _connect(self):
        if self.redis_client:
            raise RuntimeError("Operação de DB direto não disponível em modo Redis")
        import sqlite3
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        return conn

    def _normalize_for_json(self, value: Any) -> Any:
        if value is None or isinstance(value, (str, int, float, bool)):
            return value
        if isinstance(value, datetime):
            return value.isoformat()
        if isinstance(value, Enum):
            return value.value
        if isinstance(value, Path):
            return str(value)
        if is_dataclass(value):
            return self._normalize_for_json(asdict(value))
        model_dump = getattr(value, "model_dump", None)
        if callable(model_dump):
            return self._normalize_for_json(model_dump())
        if isinstance(value, dict):
            return {str(key): self._normalize_for_json(item) for key, item in value.items()}
        if isinstance(value, (list, tuple, set)):
            return [self._normalize_for_json(item) for item in value]
        if hasattr(value, "__dict__"):
            return self._normalize_for_json(vars(value))
        return str(value)

    def _init_db(self) -> None:
        if self.redis_client:
            return
        def _init():
            with self._connect() as conn:
                conn.execute(
                    """
                    CREATE TABLE IF NOT EXISTS app_state (
                        state_key TEXT PRIMARY KEY,
                        payload_json TEXT NOT NULL,
                        updated_at TEXT NOT NULL
                    )
                    """
                )
                conn.commit()
        self._with_lock(_init)

    def _save_json(self, key: str, payload: dict[str, Any]) -> None:
        if self.redis_client:
            serialized = json.dumps(self._normalize_for_json(payload), ensure_ascii=False)
            self.redis_client.set(self._redis_key(key), serialized)
            return

        def _save():
            serialized = json.dumps(self._normalize_for_json(payload), ensure_ascii=False)
            with self._connect() as conn:
                conn.execute(
                    """
                    INSERT INTO app_state(state_key, payload_json, updated_at)
                    VALUES(?, ?, ?)
                    ON CONFLICT(state_key) DO UPDATE SET
                        payload_json=excluded.payload_json,
                        updated_at=excluded.updated_at
                    """,
                    (key, serialized, datetime.now().isoformat()),
                )
                conn.commit()
        self._with_lock(_save)

    def _load_json(self, key: str) -> Optional[dict[str, Any]]:
        if self.redis_client:
            value = self.redis_client.get(self._redis_key(key))
            if value is None:
                return None
            return _deserialize_payload(value)

        def _load():
            with self._connect() as conn:
                row = conn.execute(
                    "SELECT payload_json FROM app_state WHERE state_key = ?",
                    (key,),
                ).fetchone()
            if not row:
                return None
            try:
                return json.loads(row["payload_json"])
            except Exception:
                return None
        return self._with_lock(_load)

    def _delete(self, key: str) -> None:
        if self.redis_client:
            self.redis_client.delete(self._redis_key(key))
            return

        def _delete():
            with self._connect() as conn:
                conn.execute("DELETE FROM app_state WHERE state_key = ?", (key,))
                conn.commit()
        self._with_lock(_delete)

    def save_pending_preview(self, payload: dict[str, Any]) -> None:
        self._save_json("pending_preview", payload)

    def load_pending_preview(self) -> Optional[dict[str, Any]]:
        return self._load_json("pending_preview")

    def clear_pending_preview(self) -> None:
        self._delete("pending_preview")

    def save_active_goal(self, payload: dict[str, Any]) -> None:
        self._save_json("active_goal", payload)

    def load_active_goal(self) -> Optional[dict[str, Any]]:
        return self._load_json("active_goal")

    def clear_active_goal(self) -> None:
        self._delete("active_goal")

    def save_working_context(self, payload: dict[str, Any]) -> None:
        self._save_json("working_context", payload)

    def load_working_context(self) -> Optional[dict[str, Any]]:
        return self._load_json("working_context")

    def save_operational_state(self, payload: dict[str, Any]) -> None:
        self._save_json("operational_state", payload)

    def load_operational_state(self) -> Optional[dict[str, Any]]:
        return self._load_json("operational_state")
