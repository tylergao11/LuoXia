from __future__ import annotations

from typing import Any
from uuid import uuid4

from pydantic import BaseModel, Field

from .enums import (
    ActionType,
    BeliefSource,
    EventKind,
    GamePhase,
    Severity,
    TruthRel,
)

ActorId = str
LocationId = str


class ActorProfile(BaseModel):
    """静态人设（内容包提供）；运行时状态在 AuthorityState。"""

    id: ActorId
    display_name: str
    title: str = ""
    summary: str = ""
    personality: str = ""
    drives: str = ""
    is_player: bool = False
    """高驱动则日终优先；功能型可降权。"""
    drive_priority: int = 0
    can_proclaim: bool = False
    tags: list[str] = Field(default_factory=list)
    default_location: LocationId | None = None
    # 扩展孔：境界文案、派系等，引擎不解释
    extra: dict[str, Any] = Field(default_factory=dict)


class AuthorityState(BaseModel):
    """权威状态文档——天道 CRUD 目标；字段可扩展。"""

    actor_id: ActorId
    alive: bool = True
    location: LocationId | None = None
    identity: dict[str, Any] = Field(default_factory=dict)
    cultivation: dict[str, Any] = Field(default_factory=dict)
    resources: dict[str, Any] = Field(default_factory=lambda: {"spirit_stones": 0})
    inventory: list[dict[str, Any]] = Field(default_factory=list)
    body: dict[str, Any] = Field(default_factory=dict)
    law: dict[str, Any] = Field(default_factory=dict)
    flags: dict[str, Any] = Field(default_factory=dict)
    updated_day: int = 1

    def get_path(self, path: str) -> Any:
        cur: Any = self.model_dump()
        for part in path.split("."):
            if not isinstance(cur, dict) or part not in cur:
                return None
            cur = cur[part]
        return cur


class Belief(BaseModel):
    belief_id: str
    holder_id: ActorId
    proposition: str
    polarity: str = "asserted"
    source: BeliefSource = BeliefSource.INFERENCE
    source_detail: str = ""
    truth_rel: TruthRel = TruthRel.UNKNOWN_TO_AUTHORITY
    confidence: float = 0.5
    day: int = 1
    """首次形成该见闻的游戏日（传谣延迟用）。"""
    planted_day: int | None = None
    """传谣跳数；0=亲历/原始。"""
    hop: int = 0
    """冷却：此见闻最早可再被传出的 day。"""
    next_spread_day: int | None = None


class WorldEvent(BaseModel):
    """运行时事件实例（不可枚举内容）；落日志/事件卡。"""

    event_id: str = Field(default_factory=lambda: f"ev_{uuid4().hex[:12]}")
    kind: EventKind = EventKind.OTHER
    severity: Severity = Severity.MINOR
    title: str
    summary: str = ""
    actor_ids: list[ActorId] = Field(default_factory=list)
    location: LocationId | None = None
    day: int = 1
    known_to: list[ActorId] = Field(default_factory=list)
    card_headline: str = ""
    card_body: str = ""
    tags: list[str] = Field(default_factory=list)
    # 玩家「自身」vs 世界日志分流
    involves_player: bool = False
    meta: dict[str, Any] = Field(default_factory=dict)


class LocationNode(BaseModel):
    id: LocationId
    name: str
    summary: str = ""
    # 占位资源 key，前端映射色/图
    art_key: str = "placeholder"
    tags: list[str] = Field(default_factory=list)
    extra: dict[str, Any] = Field(default_factory=dict)


class MapGraph(BaseModel):
    nodes: dict[LocationId, LocationNode] = Field(default_factory=dict)
    """无向边：from -> [to, ...]"""
    edges: dict[LocationId, list[LocationId]] = Field(default_factory=dict)

    def neighbors(self, location_id: LocationId) -> list[LocationId]:
        return list(self.edges.get(location_id, []))

    def can_move(self, frm: LocationId, to: LocationId) -> bool:
        if frm == to:
            return True
        return to in self.neighbors(frm) or frm in self.neighbors(to)


class WorldRules(BaseModel):
    """内容包可覆盖的规则默认值。"""

    max_days: int = 21
    daily_ap: int = 6
    move_ap_cost: int = 1
    player_actor_id: ActorId = "player"
    high_drive_min_priority: int = 50


class GameSession(BaseModel):
    """一局运行时聚合根。"""

    session_id: str = Field(default_factory=lambda: uuid4().hex)
    world_id: str
    phase: GamePhase = GamePhase.PLAYER_TURN
    day: int = 1
    ap: int = 6
    profiles: dict[ActorId, ActorProfile] = Field(default_factory=dict)
    states: dict[ActorId, AuthorityState] = Field(default_factory=dict)
    beliefs: dict[ActorId, list[Belief]] = Field(default_factory=dict)
    events: list[WorldEvent] = Field(default_factory=list)
    map: MapGraph = Field(default_factory=MapGraph)
    rules: WorldRules = Field(default_factory=WorldRules)
    world_flags: dict[str, Any] = Field(default_factory=dict)
    background_text: str = ""
    game_over_reason: str | None = None
    # 日终演变断点（进程崩溃后可续跑）
    evolve_queue: list[str] = Field(default_factory=list)
    evolve_index: int = 0
    # 真相字典·对白：按 actor 分仓；仅「说了什么」+ 事件封条引用 + 机械局势脚注
    # 见闻/天下/履历叙事不在此写——那些在 beliefs / world_flags / events
    dialogue: dict[str, Any] = Field(default_factory=dict)
    # LangGraph / LLM 缓存草稿（非玩家真相）
    graph_meta: dict[str, Any] = Field(default_factory=dict)

    def player_id(self) -> ActorId:
        return self.rules.player_actor_id

    def actors_at(self, location_id: LocationId) -> list[ActorId]:
        return [
            aid
            for aid, st in self.states.items()
            if st.alive and st.location == location_id
        ]


class ActionRequest(BaseModel):
    type: ActionType | str
    actor_id: ActorId | None = None
    target_id: ActorId | None = None
    location_id: LocationId | None = None
    utterance: str | None = None
    payload: dict[str, Any] = Field(default_factory=dict)


class ActionResult(BaseModel):
    ok: bool = True
    message: str = ""
    session: GameSession | None = None
    new_events: list[WorldEvent] = Field(default_factory=list)
    npc_utterance: str | None = None
    error_code: str | None = None
    # 局势摘要：己身/对方状态变化（前端直接展示，不必点开）
    effects: dict[str, Any] = Field(default_factory=dict)


class StateOp(BaseModel):
    actor_id: ActorId
    op: str  # set | add | remove | delete_key
    path: str
    value: Any = None


class BeliefOp(BaseModel):
    holder_id: ActorId
    op: str  # upsert | retract | clear_all
    belief_id: str | None = None
    proposition: str | None = None
    polarity: str = "asserted"
    source: BeliefSource | str = BeliefSource.INFERENCE
    source_detail: str = ""
    truth_rel: TruthRel | str = TruthRel.UNKNOWN_TO_AUTHORITY
    confidence: float = 0.5
    day: int | None = None
    reason: str | None = None


class AdjudicationResult(BaseModel):
    """天道输出的引擎层 DTO（与 LLM JSON 同构，可校验）。"""

    schema_version: int = 1
    narrative_summary: str = ""
    ap_cost: int = 0
    state_ops: list[StateOp] = Field(default_factory=list)
    belief_ops: list[BeliefOp] = Field(default_factory=list)
    events: list[WorldEvent] = Field(default_factory=list)
    proclamation: dict[str, Any] | None = None
    game_flags: dict[str, Any] = Field(default_factory=dict)
    """世界级 flags 补丁（非角色状态）。"""
    world_flag_ops: dict[str, Any] = Field(default_factory=dict)
    ui_hints: dict[str, Any] = Field(default_factory=dict)


class NpcReply(BaseModel):
    speaker_id: ActorId
    utterance: str
    tone: str = ""
    intent_tags: list[str] = Field(default_factory=list)
    private_thought: str = ""
    wants_action: dict[str, Any] | None = None
    engagement: str = "willing"


class NpcIntent(BaseModel):
    npc_id: ActorId
    goal_summary: str = ""
    action: dict[str, Any] = Field(default_factory=lambda: {"type": "idle"})
    priority: str = "normal"
    based_on_beliefs: list[str] = Field(default_factory=list)
