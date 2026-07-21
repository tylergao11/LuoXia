from __future__ import annotations

from typing import Any

from pydantic import BaseModel, Field


class CreateGameBody(BaseModel):
    world_id: str = "luoxia"


class ActionBody(BaseModel):
    type: str
    target_id: str | None = None
    location_id: str | None = None
    utterance: str | None = None
    payload: dict[str, Any] = Field(default_factory=dict)


class SessionView(BaseModel):
    """前端视图 DTO——可逐步加置灰字段。"""

    session_id: str
    world_id: str
    phase: str
    day: int
    ap: int
    max_days: int
    daily_ap: int
    player: dict[str, Any]
    locations: list[dict[str, Any]]
    actors_here: list[dict[str, Any]]
    all_actors: list[dict[str, Any]]
    recent_events: list[dict[str, Any]]
    world_flags_public: dict[str, Any]
    clue_flags: list[dict[str, Any]] = Field(default_factory=list)
    game_over_reason: str | None = None
    settlement_text: str = ""
    """终局文案投影（来自 settlement 事件），非 graph_meta 影子。"""
    logs_self: list[dict[str, Any]] = Field(default_factory=list)
    logs_world: list[dict[str, Any]] = Field(default_factory=list)
    evolve_queue: list[str] = Field(default_factory=list)
    evolve_index: int = 0
    evolve_last_actor_id: str = ""
    evolve_last_actor_name: str = ""
    # 按 actor 分仓的聊天 DTO（= session.dialogue 投影，对白权威）
    chat_by_actor: dict[str, Any] = Field(default_factory=dict)
    # 进行中的交锋/遭遇（无则 null）；前端按 stage_module 加载画模块
    encounter: dict[str, Any] | None = None
