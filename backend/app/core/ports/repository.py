from __future__ import annotations

from abc import ABC, abstractmethod
from typing import Any

from app.core.domain.models import GameSession


class SessionRepositoryPort(ABC):
    """会话持久化端口——内存 / SQLite / 外部 DB 可替换。"""

    @abstractmethod
    def save(self, session: GameSession) -> None:
        ...

    @abstractmethod
    def get(self, session_id: str) -> GameSession | None:
        ...

    @abstractmethod
    def delete(self, session_id: str) -> None:
        ...

    def list_meta(self, limit: int = 20) -> list[dict[str, Any]]:
        """可选：最近会话列表。默认空。"""
        return []
