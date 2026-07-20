from __future__ import annotations

from abc import ABC, abstractmethod

from app.core.domain.models import GameSession, NpcIntent, NpcReply


class AgentMindPort(ABC):
    """
    角色心智端口：只基于主观信念 + 人设决策，不写权威状态。
    """

    @abstractmethod
    def reply(
        self,
        session: GameSession,
        *,
        speaker_id: str,
        player_utterance: str,
        listener_id: str = "player",
    ) -> NpcReply:
        ...

    @abstractmethod
    def intend(self, session: GameSession, *, npc_id: str) -> NpcIntent:
        ...
