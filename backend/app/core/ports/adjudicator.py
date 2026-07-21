from __future__ import annotations

from abc import ABC, abstractmethod
from typing import Any

from app.core.domain.models import AdjudicationResult, GameSession


class AdjudicatorPort(ABC):
    """
    天道端口：对权威状态有最终解释权。

    实现：LLM 天道（产品路径必须可用）。
    """

    @abstractmethod
    def adjudicate(
        self,
        session: GameSession,
        *,
        actor_ids: list[str],
        current_material: dict[str, Any],
        phase: str = "player_action",
    ) -> AdjudicationResult:
        """
        输入约定：
        - 背景与相关角色状态由实现方从 session 读取
        - current_material 仅当前对话/行动，不含全历史原文
        """
        ...
