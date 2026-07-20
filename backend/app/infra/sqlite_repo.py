from __future__ import annotations

import json
import sqlite3
from pathlib import Path

from app.core.domain.models import GameSession
from app.core.ports.repository import SessionRepositoryPort


class SqliteSessionRepository(SessionRepositoryPort):
    """
    会话整包 JSON 存 SQLite——实现可替换，领域模型不变。
    """

    def __init__(self, path: str | Path) -> None:
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._init_db()

    def _connect(self) -> sqlite3.Connection:
        conn = sqlite3.connect(str(self.path), check_same_thread=False)
        conn.row_factory = sqlite3.Row
        return conn

    def _init_db(self) -> None:
        with self._connect() as conn:
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS sessions (
                    session_id TEXT PRIMARY KEY,
                    world_id TEXT NOT NULL,
                    phase TEXT NOT NULL,
                    day INTEGER NOT NULL,
                    updated_at TEXT NOT NULL DEFAULT (datetime('now')),
                    payload TEXT NOT NULL
                )
                """
            )
            conn.execute(
                "CREATE INDEX IF NOT EXISTS idx_sessions_updated ON sessions(updated_at DESC)"
            )
            conn.commit()

    def save(self, session: GameSession) -> None:
        payload = session.model_dump(mode="json")
        raw = json.dumps(payload, ensure_ascii=False, default=str)
        with self._connect() as conn:
            conn.execute(
                """
                INSERT INTO sessions (session_id, world_id, phase, day, updated_at, payload)
                VALUES (?, ?, ?, ?, datetime('now'), ?)
                ON CONFLICT(session_id) DO UPDATE SET
                    world_id=excluded.world_id,
                    phase=excluded.phase,
                    day=excluded.day,
                    updated_at=datetime('now'),
                    payload=excluded.payload
                """,
                (
                    session.session_id,
                    session.world_id,
                    session.phase.value if hasattr(session.phase, "value") else str(session.phase),
                    session.day,
                    raw,
                ),
            )
            conn.commit()

    def get(self, session_id: str) -> GameSession | None:
        with self._connect() as conn:
            row = conn.execute(
                "SELECT payload FROM sessions WHERE session_id = ?",
                (session_id,),
            ).fetchone()
        if not row:
            return None
        data = json.loads(row["payload"])
        return GameSession.model_validate(data)

    def delete(self, session_id: str) -> None:
        with self._connect() as conn:
            conn.execute("DELETE FROM sessions WHERE session_id = ?", (session_id,))
            conn.commit()

    def list_meta(self, limit: int = 20) -> list[dict]:
        with self._connect() as conn:
            rows = conn.execute(
                """
                SELECT session_id, world_id, phase, day, updated_at
                FROM sessions
                ORDER BY updated_at DESC
                LIMIT ?
                """,
                (limit,),
            ).fetchall()
        return [dict(r) for r in rows]
