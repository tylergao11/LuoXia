"""
对话硬钩子：不扫台词。
内容包 on_dialogue 返回同构 ops；合并进 AdjudicationResult，由 StateApplier 落地。
"""

from __future__ import annotations

from typing import Any

from app.core.domain.models import AdjudicationResult, BeliefOp, GameSession, StateOp
from app.core.services.content_packet import apply_packet


def merge_dialogue_hard_hooks(
    session: GameSession,
    adj: AdjudicationResult,
    *,
    player_id: str,
    npc_id: str,
    utterance: str = "",
    registry: Any | None = None,
    material: dict[str, Any] | None = None,
) -> AdjudicationResult:
    _ = material
    events = list(adj.events or [])
    state_ops = list(adj.state_ops or [])
    belief_ops = list(adj.belief_ops or [])
    world_flag_ops = dict(adj.world_flag_ops or {})
    changed = False

    if registry is None:
        return adj
    try:
        pack = registry.get(session.world_id)
        hook = pack.on_dialogue(
            session,
            player_id=player_id,
            npc_id=npc_id,
            utterance=utterance,
        ) or {}
        # notes 仅调试，不进玩家叙事
        for ev in hook.get("events") or []:
            events.append(ev)
            changed = True
        for op in hook.get("state_ops") or []:
            if isinstance(op, StateOp):
                state_ops.append(op)
            elif isinstance(op, dict):
                state_ops.append(StateOp.model_validate(op))
            changed = True
        for op in hook.get("belief_ops") or []:
            if isinstance(op, BeliefOp):
                belief_ops.append(op)
            elif isinstance(op, dict):
                belief_ops.append(BeliefOp.model_validate(op))
            changed = True
        for k, v in (hook.get("world_flag_ops") or {}).items():
            world_flag_ops[k] = v
            changed = True
    except Exception:
        pass

    if not changed:
        return adj
    return adj.model_copy(
        update={
            "events": events,
            "state_ops": state_ops,
            "belief_ops": belief_ops,
            "world_flag_ops": world_flag_ops,
        }
    )


def after_flags_refresh_map(session: GameSession, registry: Any | None = None) -> list[str]:
    """
    裁决写入后：委托 WorldPack.after_flags_refresh（同构包 → apply）。
    返回本次 map_unlocked 中新增 id（若有）。
    """
    if registry is None:
        return []
    try:
        pack = registry.get(session.world_id)
    except Exception:
        return []
    fn = getattr(pack, "after_flags_refresh", None)
    if not callable(fn):
        return []
    before = session.world_flags.get("map_unlocked")
    before_set = set(before) if isinstance(before, list) else set()
    packet = fn(session) or {}
    apply_packet(session, packet)
    after = session.world_flags.get("map_unlocked")
    if not isinstance(after, list):
        return []
    return [str(x) for x in after if str(x) not in before_set]
