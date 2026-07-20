from __future__ import annotations

from copy import deepcopy

from app.core.domain.models import GameSession
from app.core.ports.repository import SessionRepositoryPort


class InMemorySessionRepository(SessionRepositoryPort):
    def __init__(self) -> None:
        self._store: dict[str, GameSession] = {}

    def save(self, session: GameSession) -> None:
        self._store[session.session_id] = session.model_copy(deep=True)

    def get(self, session_id: str) -> GameSession | None:
        s = self._store.get(session_id)
        return s.model_copy(deep=True) if s else None

    def delete(self, session_id: str) -> None:
        self._store.pop(session_id, None)

    def list_meta(self, limit: int = 20) -> list[dict]:
        items = sorted(
            self._store.values(),
            key=lambda s: s.day,
            reverse=True,
        )[:limit]
        return [
            {
                "session_id": s.session_id,
                "world_id": s.world_id,
                "phase": s.phase.value if hasattr(s.phase, "value") else str(s.phase),
                "day": s.day,
            }
            for s in items
        ]
