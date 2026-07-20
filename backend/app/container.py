"""组合根：组装端口实现。换 LLM / DB / 世界包只改这里。"""

from __future__ import annotations

from functools import lru_cache

from app.config import settings
from app.content.luoxia import LuoxiaWorldPack
from app.content.qingxi import QingxiWorldPack
from app.core.services.action_service import ActionService
from app.core.services.game_factory import GameFactory
from app.core.services.world_registry import WorldRegistry
from app.infra.llm_adjudicator import LLMAdjudicator
from app.infra.llm_client import LLMClient
from app.infra.llm_mind import LLMAgentMind
from app.infra.memory_repo import InMemorySessionRepository
from app.infra.mock_adjudicator import MockAdjudicator
from app.infra.mock_mind import MockAgentMind
from app.infra.sqlite_repo import SqliteSessionRepository


class Container:
    def __init__(self) -> None:
        self.registry = WorldRegistry()
        self.registry.register(LuoxiaWorldPack())
        self.registry.register(QingxiWorldPack())

        if settings.session_store.lower() == "memory":
            self.repo = InMemorySessionRepository()
            self.store_mode = "memory"
        else:
            self.repo = SqliteSessionRepository(settings.sqlite_path)
            self.store_mode = "sqlite"

        self.llm = LLMClient()

        if settings.use_llm and self.llm.available:
            # 纯 LLM，失败直接抛，无 Mock 嵌套回退
            self.adjudicator = LLMAdjudicator(self.llm)
            self.mind = LLMAgentMind(self.llm)
            self.llm_mode = f"llm ({settings.llm_model})"
        else:
            self.adjudicator = MockAdjudicator(registry=self.registry)
            self.mind = MockAgentMind()
            self.llm_mode = "mock"

        self.factory = GameFactory(self.registry)
        self.actions = ActionService(
            repo=self.repo,
            adjudicator=self.adjudicator,
            mind=self.mind,
            registry=self.registry,
            use_checkpointer=settings.use_graph_checkpointer,
        )


@lru_cache
def get_container() -> Container:
    return Container()
