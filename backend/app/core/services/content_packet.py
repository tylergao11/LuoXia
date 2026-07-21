"""内容包同构事件包：唯一经 StateApplier 落地。"""

from __future__ import annotations

from typing import Any

from app.core.domain.models import (
    AdjudicationResult,
    BeliefOp,
    GameSession,
    StateOp,
    WorldEvent,
)
from app.core.services.state_applier import StateApplier


def empty_packet() -> dict[str, Any]:
    return {
        "state_ops": [],
        "belief_ops": [],
        "events": [],
        "world_flag_ops": {},
        "notes": [],  # 引擎/调试备注，不进玩家叙事
    }


def merge_packets(*parts: dict[str, Any] | None) -> dict[str, Any]:
    """合并多包；map_unlocked 列表做有序并集。narrative_summary 不进硬产出。"""
    out = empty_packet()
    for p in parts:
        if not p:
            continue
        out["state_ops"].extend(p.get("state_ops") or [])
        out["belief_ops"].extend(p.get("belief_ops") or [])
        out["events"].extend(p.get("events") or [])
        if p.get("notes"):
            out["notes"].extend(p["notes"] if isinstance(p["notes"], list) else [p["notes"]])
        for k, v in (p.get("world_flag_ops") or {}).items():
            if k == "map_unlocked" and isinstance(v, list):
                prev = out["world_flag_ops"].get("map_unlocked")
                if isinstance(prev, list):
                    seen = set(prev)
                    merged = list(prev)
                    for x in v:
                        sx = str(x)
                        if sx not in seen:
                            seen.add(sx)
                            merged.append(sx)
                    out["world_flag_ops"]["map_unlocked"] = merged
                else:
                    out["world_flag_ops"]["map_unlocked"] = list(v)
            else:
                out["world_flag_ops"][k] = v
    return out


def packet_nonempty(packet: dict[str, Any] | None) -> bool:
    if not packet:
        return False
    return bool(
        packet.get("state_ops")
        or packet.get("belief_ops")
        or packet.get("world_flag_ops")
        or packet.get("events")
    )


def packet_to_result(packet: dict[str, Any] | AdjudicationResult | None) -> AdjudicationResult:
    if packet is None:
        return AdjudicationResult()
    if isinstance(packet, AdjudicationResult):
        return packet
    state_ops: list[StateOp] = []
    for op in packet.get("state_ops") or []:
        if isinstance(op, StateOp):
            state_ops.append(op)
        elif isinstance(op, dict):
            state_ops.append(StateOp.model_validate(op))
    belief_ops: list[BeliefOp] = []
    for op in packet.get("belief_ops") or []:
        if isinstance(op, BeliefOp):
            belief_ops.append(op)
        elif isinstance(op, dict):
            belief_ops.append(BeliefOp.model_validate(op))
    events: list[WorldEvent] = []
    for ev in packet.get("events") or []:
        if isinstance(ev, WorldEvent):
            events.append(ev)
        elif isinstance(ev, dict):
            events.append(WorldEvent.model_validate(ev))
    # notes / narrative_summary：管道草稿，不落地为玩家真相
    return AdjudicationResult(
        narrative_summary="",
        state_ops=state_ops,
        belief_ops=belief_ops,
        world_flag_ops=dict(packet.get("world_flag_ops") or {}),
        events=events,
    )


def apply_packet(
    session: GameSession,
    packet: dict[str, Any] | AdjudicationResult | None,
    *,
    applier: StateApplier | None = None,
) -> list[WorldEvent]:
    """内容/引擎统一落地入口。"""
    if not packet:
        return []
    if isinstance(packet, dict) and not packet_nonempty(packet):
        return []
    result = packet_to_result(packet)
    if (
        not result.state_ops
        and not result.belief_ops
        and not result.world_flag_ops
        and not result.events
    ):
        return []
    return (applier or StateApplier()).apply(session, result)
