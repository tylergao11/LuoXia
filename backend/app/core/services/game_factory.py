from __future__ import annotations

from app.core.domain.enums import GamePhase
from app.core.domain.models import GameSession
from app.core.ports.world_pack import WorldPack
from app.core.services.world_registry import WorldRegistry


class GameFactory:
    """根据 WorldPack 创建新局——引擎入口，无硬编码角色。"""

    def __init__(self, registry: WorldRegistry) -> None:
        self.registry = registry

    def create(self, world_id: str) -> GameSession:
        pack: WorldPack = self.registry.get(world_id)
        rules = pack.rules()
        profiles = pack.build_profiles()
        states = pack.build_initial_states(profiles)
        beliefs = pack.build_initial_beliefs(profiles)
        session = GameSession(
            world_id=pack.world_id,
            phase=GamePhase.PLAYER_TURN,
            day=1,
            ap=rules.daily_ap,
            profiles=profiles,
            states=states,
            beliefs=beliefs,
            events=[],
            map=pack.build_map(),
            rules=rules,
            world_flags=pack.build_world_flags(),
            background_text=pack.background_text(),
        )
        if hasattr(pack, "on_new_game"):
            pack.on_new_game(session)
        return session
