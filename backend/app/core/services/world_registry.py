from __future__ import annotations

from app.core.ports.world_pack import WorldPack


class WorldRegistry:
    """已注册世界包：扩展新世界 = register 新 WorldPack。"""

    def __init__(self) -> None:
        self._packs: dict[str, WorldPack] = {}

    def register(self, pack: WorldPack) -> None:
        self._packs[pack.world_id] = pack

    def get(self, world_id: str) -> WorldPack:
        if world_id not in self._packs:
            raise KeyError(f"未知世界包: {world_id}；已注册: {list(self._packs)}")
        return self._packs[world_id]

    def list_worlds(self) -> list[dict[str, str]]:
        return [
            {"world_id": p.world_id, "display_name": p.display_name}
            for p in self._packs.values()
        ]
