"""规则意图：日终批次缺员/失败时的兜底（世界无关 tags/drives + 地图 node tags）。"""

from __future__ import annotations

from app.core.domain.models import GameSession, NpcIntent


def _loc_with_tag(session: GameSession, *want_tags: str, fallback: str | None) -> str | None:
    tags_want = set(want_tags)
    for nid, node in session.map.nodes.items():
        node_tags = set(node.tags or [])
        if tags_want & node_tags:
            return nid
    return fallback


def rule_intend_many(
    session: GameSession, npc_ids: list[str]
) -> dict[str, NpcIntent]:
    return {nid: rule_intend(session, npc_id=nid) for nid in npc_ids}


def default_play_order(session: GameSession, queue: list[str]) -> list[str]:
    """按 drive_priority 降序；同分按 id。"""

    def _key(nid: str) -> tuple:
        prof = session.profiles.get(nid)
        pri = int(prof.drive_priority) if prof else 0
        return (-pri, nid)

    return sorted([nid for nid in queue if nid in session.profiles], key=_key)


def rule_intend(session: GameSession, *, npc_id: str) -> NpcIntent:
    prof = session.profiles.get(npc_id)
    st = session.states.get(npc_id)
    if not prof or not st or not st.alive:
        return NpcIntent(npc_id=npc_id, goal_summary="无力行动", action={"type": "idle"})

    tags = set(prof.tags or [])
    if prof.drive_priority < 50 and "functional" in tags and session.day % 2 == 0:
        return NpcIntent(
            npc_id=npc_id, goal_summary="当值/休憩", action={"type": "idle"}
        )

    if "investigator" in tags or "查" in prof.drives:
        dest = _loc_with_tag(session, "archive", "order", fallback=st.location)
        return NpcIntent(
            npc_id=npc_id,
            goal_summary="暗中查访异常迹象",
            action={"type": "search", "location": dest, "detail": "取证"},
            priority="high",
        )
    if "social" in tags or "人缘" in prof.drives or "探听" in prof.drives:
        dest = _loc_with_tag(session, "public", "social", fallback=st.location)
        return NpcIntent(
            npc_id=npc_id,
            goal_summary="在公共处维系人缘、探听议论",
            action={"type": "talk", "location": dest},
            priority="high",
        )
    if "reclusive" in tags or "独自" in prof.drives or "守密" in prof.drives:
        dest = _loc_with_tag(session, "secluded", fallback=st.location)
        return NpcIntent(
            npc_id=npc_id,
            goal_summary="独自徘徊静处",
            action={"type": "move", "location": dest},
            priority="high",
        )
    if "order" in tags or "规矩" in prof.drives or "正统" in prof.drives:
        dest = _loc_with_tag(session, "order", fallback=st.location)
        return NpcIntent(
            npc_id=npc_id,
            goal_summary="巡视礼仪与秩序",
            action={"type": "move", "location": dest},
        )
    if prof.can_proclaim and session.day % 5 == 0:
        return NpcIntent(
            npc_id=npc_id,
            goal_summary="视情发布安定人心的通告",
            action={
                "type": "proclaim",
                "detail": "各司其职，勿信无根流言。",
            },
            priority="high",
        )
    if "law" in tags:
        return NpcIntent(
            npc_id=npc_id,
            goal_summary="处理本职案牍",
            action={"type": "idle", "location": st.location},
        )

    if prof.default_location and prof.default_location != st.location:
        return NpcIntent(
            npc_id=npc_id,
            goal_summary=f"返回{prof.default_location}",
            action={"type": "move", "location": prof.default_location},
        )
    return NpcIntent(
        npc_id=npc_id,
        goal_summary=f"{prof.display_name}按本职行事",
        action={"type": "idle"},
    )
