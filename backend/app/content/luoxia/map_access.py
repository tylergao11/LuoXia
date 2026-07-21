"""
落霞地图硬状态：起始开放集 + map_unlocked + 封山反向锁。
真相源：docs/luoxia.md §8.2

写路径只返回同构 ContentPacket；读路径纯读 session。
"""

from __future__ import annotations

from typing import Any
from uuid import uuid4

from app.core.domain.enums import EventKind, Severity
from app.core.domain.models import GameSession, WorldEvent

# 开局即开放（硬状态初始）
START_OPEN: frozenset[str] = frozenset(
    {"gate", "square", "kitchen", "dorm_outer"}
)

# 可被条件解锁的地点
GATED: frozenset[str] = frozenset(
    {
        "mission",
        "law",
        "hall",
        "elder",
        "library",
        "arena",
        "dorm_inner",
        "backhill",
    }
)

# 封山时对玩家反向锁定（外圈）
SEAL_LOCKS: frozenset[str] = frozenset({"gate", "dorm_outer", "kitchen"})


def unlocked_list(session: GameSession) -> list[str]:
    raw = session.world_flags.get("map_unlocked")
    if not isinstance(raw, list):
        return []
    return [str(x) for x in raw]


def compute_unlock_list(
    session: GameSession,
    *loc_ids: str,
    base: list[str] | None = None,
) -> tuple[list[str], list[str]]:
    """纯函数：返回 (完整新列表, 本次新增 id)。不写 session。"""
    lst = list(base if base is not None else unlocked_list(session))
    added: list[str] = []
    for lid in loc_ids:
        if lid in session.map.nodes and lid not in lst and lid not in START_OPEN:
            lst.append(lid)
            added.append(lid)
    return lst, added


def unlock_packet(
    session: GameSession,
    *loc_ids: str,
    base: list[str] | None = None,
) -> dict[str, Any]:
    """同构包：设置 map_unlocked（若有新增）。"""
    lst, added = compute_unlock_list(session, *loc_ids, base=base)
    if not added:
        return {
            "state_ops": [],
            "belief_ops": [],
            "events": [],
            "world_flag_ops": {},
            "notes": [],
        }
    return {
        "state_ops": [],
        "belief_ops": [],
        "events": [],
        "world_flag_ops": {"map_unlocked": lst},
        "notes": [f"unlock:{x}" for x in added],
    }


def _flags_view(
    session: GameSession, flags_overlay: dict[str, Any] | None = None
) -> dict[str, Any]:
    return {**(session.world_flags or {}), **(flags_overlay or {})}


def seal_conditions_met(
    session: GameSession, *, flags_overlay: dict[str, Any] | None = None
) -> bool:
    """临界条件（不含已立的 sticky flag）。"""
    flags = _flags_view(session, flags_overlay)
    try:
        cd = int(flags.get("xuanyin_countdown", 99))
    except (TypeError, ValueError):
        cd = 99
    if cd <= 5:
        return True
    if flags.get("letter_exposed") and cd <= 10:
        return True
    return False


def seal_active(
    session: GameSession, *, flags_overlay: dict[str, Any] | None = None
) -> bool:
    flags = _flags_view(session, flags_overlay)
    if flags.get("seal_mountain"):
        return True
    return seal_conditions_met(session, flags_overlay=flags_overlay)


def location_open_for_player(session: GameSession, loc_id: str) -> bool:
    if loc_id not in session.map.nodes:
        return False
    if seal_active(session) and loc_id in SEAL_LOCKS:
        return False
    if loc_id in START_OPEN:
        return True
    if loc_id in unlocked_list(session):
        return True
    if loc_id not in GATED:
        return True
    return False


def lock_reason(session: GameSession, loc_id: str) -> str:
    node = session.map.nodes.get(loc_id)
    name = node.name if node else loc_id
    if seal_active(session) and loc_id in SEAL_LOCKS:
        return f"{name}因封山不得擅离核心区。"
    reasons = {
        "mission": "任务堂有职司门禁，需差遣或引荐方可入。",
        "law": "执法堂重地，无故不得擅入。",
        "hall": "宗主殿牌位森严，无故不得擅闯。",
        "elder": "长老院议事之所，客卿不得擅入。",
        "library": "藏经阁无借阅腰牌，明镜不会见你。",
        "arena": "演武场内门弟子所用，暂未对你开放。",
        "dorm_inner": "内门居所，外客不得擅入。",
        "backhill": "后山静修重地，客卿不得擅入。",
    }
    return reasons.get(loc_id, f"{name}尚未对你开放。")


def seal_sync_packet(
    session: GameSession, *, flags_overlay: dict[str, Any] | None = None
) -> dict[str, Any]:
    """
    封山 sticky + 首次封山叙事事件卡。纯计算，不写 session。
    flags_overlay：日终减 countdown 后的投影（未落地）。
    """
    flags = _flags_view(session, flags_overlay)
    world_flag_ops: dict[str, Any] = {}
    events: list[WorldEvent] = []
    now = seal_active(session, flags_overlay=flags_overlay)

    if now and not flags.get("seal_mountain"):
        world_flag_ops["seal_mountain"] = True

    first_note = now and not flags.get("seal_mountain_noted")
    if first_note:
        world_flag_ops["seal_mountain"] = True
        world_flag_ops["seal_mountain_noted"] = True
        reason = "劫数将尽，宗门收束门户。"
        try:
            cd = int(flags.get("xuanyin_countdown", 99))
        except (TypeError, ValueError):
            cd = 99
        if flags.get("letter_exposed") and cd <= 10:
            reason = "假信半公开、劫数已紧，宗门下令封山。"
        elif cd <= 5:
            reason = "劫数倒计时危急，外门与山门不得擅离核心。"

        pid = session.player_id()
        loc = None
        pst = session.states.get(pid)
        if pst:
            loc = pst.location
        events.append(
            WorldEvent(
                event_id=f"seal_{uuid4().hex[:8]}",
                kind=EventKind.WORLD,
                severity=Severity.MAJOR,
                title="封山令下",
                summary=reason + "山门、外门客居与伙房一带不得擅离。",
                actor_ids=[pid],
                location=loc,
                day=session.day,
                known_to=[pid],
                card_headline="封山",
                card_body=reason + "你若仍在外圈，暂难出入；核心区弟子开始向内聚拢。",
                involves_player=True,
                tags=["seal_mountain", "hard_state", "crisis_pressure"],
            )
        )

    if not world_flag_ops and not events:
        return {
            "state_ops": [],
            "belief_ops": [],
            "events": [],
            "world_flag_ops": {},
            "notes": [],
        }
    return {
        "state_ops": [],
        "belief_ops": [],
        "events": events,
        "world_flag_ops": world_flag_ops,
        "notes": [],
    }


def maybe_unlock_packet(session: GameSession) -> dict[str, Any]:
    """仅按已有硬状态补解锁（不读台词）。返回同构包。"""
    want: list[str] = []
    if session.world_flags.get("letter_exposed"):
        want.extend(["library", "mission", "law"])
    p_st = session.states.get(session.player_id())
    investigating = bool(p_st and (p_st.flags or {}).get("investigating_curse"))
    luo = session.states.get("shi_mei")
    trusts = bool(luo and (luo.flags or {}).get("trusts_player"))
    try:
        trust_n = int((luo.flags or {}).get("trust_player") or 0) if luo else 0
    except (TypeError, ValueError):
        trust_n = 0
    if investigating or trusts or trust_n >= 2:
        want.append("backhill")
    if trusts or trust_n >= 3:
        want.extend(["dorm_inner", "library"])
    return unlock_packet(session, *want)


def after_flags_packet(session: GameSession) -> dict[str, Any]:
    """裁决后：封山同步 + 条件解锁。"""
    from app.core.services.content_packet import merge_packets

    return merge_packets(seal_sync_packet(session), maybe_unlock_packet(session))


def location_view_extra(session: GameSession, loc_id: str) -> dict[str, Any]:
    open_ = location_open_for_player(session, loc_id)
    return {
        "unlocked": open_,
        "locked": not open_,
        "lock_reason": "" if open_ else lock_reason(session, loc_id),
        "start_open": loc_id in START_OPEN,
        "seal_locked": seal_active(session) and loc_id in SEAL_LOCKS,
    }
