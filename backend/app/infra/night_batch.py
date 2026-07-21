"""
日终一夜协商：密封分栏意图 + play_order。

- 一次 LLM：全队 intents + 排演顺序
- 每 SLOT 只含该角色主观可见信息（禁止全知 world_flags / 他人私密）
- 缺员/非法 → 规则意图兜底
"""

from __future__ import annotations

from typing import Any

from app.core.domain.models import GameSession, NpcIntent
from app.core.services.rule_intent import default_play_order, rule_intend
from app.infra.prompt_blocks import (
    compact_beliefs,
    compact_state,
    dumps_stable,
    freeze_stable_fingerprint,
    get_thread,
    split_digest_for_prompt,
    thread_key,
    _trim_thread,
)

ALLOWED_ACTION_TYPES = frozenset(
    {"talk", "move", "search", "report", "proclaim", "idle", "other"}
)


def public_presence_at(
    session: GameSession, location: str | None, *, exclude_id: str
) -> list[dict[str, Any]]:
    """同地公开可感：仅 id/名/位置/存活，不含 flags/信念。"""
    if not location:
        return []
    out: list[dict[str, Any]] = []
    for aid, st in session.states.items():
        if aid == exclude_id or not st or not st.alive:
            continue
        if st.location != location:
            continue
        prof = session.profiles.get(aid)
        out.append(
            {
                "id": aid,
                "name": prof.display_name if prof else aid,
                "location": location,
                "alive": True,
            }
        )
    out.sort(key=lambda x: x["id"])
    return out


def night_slot_payload(session: GameSession, npc_id: str) -> dict[str, Any]:
    """单人密封槽：仅自己的状态/信念/digest 前缀 + 同地公开在场。"""
    st = session.states.get(npc_id)
    loc = st.location if st else None
    digest_prefix = ""
    if st and (st.flags or {}).get("memory_digest"):
        digest_prefix, _ = split_digest_for_prompt(str(st.flags.get("memory_digest")))
    slot: dict[str, Any] = {
        "npc_id": npc_id,
        "self_state": compact_state(st),
        "self_beliefs": compact_beliefs(session, npc_id, limit=8),
        "self_memory_digest_prefix": digest_prefix or None,
        "same_location_public": public_presence_at(session, loc, exclude_id=npc_id),
        "instruction": "只为本人决策；不得使用本 SLOT 未列出的他人私密或世界阴谋。决策须参考 public_tendency。",
    }
    blurb = ""
    try:
        from app.container import get_container

        pack = get_container().registry.get(session.world_id)
        fn = getattr(pack, "public_tendency_blurb", None)
        if callable(fn):
            blurb = fn(session, npc_id) or ""
    except Exception:
        blurb = ""
    if blurb:
        slot["public_tendency"] = blurb
    return slot


def night_plan_block(session: GameSession, queue: list[str]) -> str:
    """日终动态区：分栏可见 + 协商任务（不含保密 world_flags）。"""
    slots = []
    for nid in queue:
        slots.append({"zone": f"SLOT:{nid}", **night_slot_payload(session, nid)})
    payload = {
        "zone": "NIGHT_PLAN",
        "day": session.day,
        "roster": list(queue),
        "task": (
            "并行扮演 roster 中每位 NPC；每人只根据自己的 SLOT 决策。"
            "同时协商公开行动冲突（同地抢位、互为目标、重复通告），"
            "给出今晚 play_order（谁先落地谁后落地）。"
        ),
        "slots": slots,
    }
    return "### NIGHT_PLAN\n" + dumps_stable(payload)


def build_night_batch_messages(
    session: GameSession, queue: list[str]
) -> tuple[list[dict[str, str]], dict[str, Any]]:
    """
    多轮 thread：intend_batch:night
    首包 STABLE + NIGHT_PLAN；之后只 append 新的 NIGHT_PLAN。
    """
    key = thread_key("intend_batch", "night")
    th = get_thread(session, key)
    frozen = freeze_stable_fingerprint(session, key)
    plan = night_plan_block(session, queue)
    metrics: dict[str, Any] = {
        "stable_len": len(frozen),
        "memory_len": 0,
        "dynamic_len": len(plan),
        "thread_key": key,
        "expected_hit_mode": "night_batch",
        "stable_roster": "all",
        "actor_ids": list(queue),
        "roster_size": len(queue),
    }

    if not th["messages"]:
        first = frozen + "\n\n" + plan
        th["messages"] = [{"role": "user", "content": first}]
        metrics["messages_count"] = 1
        metrics["user_len"] = len(first)
        return list(th["messages"]), metrics

    th["messages"].append({"role": "user", "content": plan})
    _trim_thread(th)
    metrics["messages_count"] = len(th["messages"])
    metrics["user_len"] = len(plan)
    metrics["stable_len"] = len(th["messages"][0]["content"]) if th["messages"] else 0
    return list(th["messages"]), metrics


def sanitize_one_intent(session: GameSession, npc_id: str, raw: dict[str, Any] | None) -> NpcIntent:
    """纠偏单条意图；无法使用则规则兜底。"""
    if not isinstance(raw, dict):
        return rule_intend(session, npc_id=npc_id)

    action = raw.get("action") if isinstance(raw.get("action"), dict) else {"type": "idle"}
    action = dict(action)
    atype = str(action.get("type") or "idle").lower()
    if atype not in ALLOWED_ACTION_TYPES:
        atype = "idle"
        action = {"type": "idle"}
    else:
        action["type"] = atype

    loc = action.get("location")
    if loc is not None and str(loc) not in session.map.nodes:
        action.pop("location", None)
        if atype == "move":
            return rule_intend(session, npc_id=npc_id)

    tid = action.get("target_id")
    if tid is not None and str(tid) not in session.profiles:
        action.pop("target_id", None)

    prof = session.profiles.get(npc_id)
    if atype == "proclaim" and (not prof or not prof.can_proclaim):
        return rule_intend(session, npc_id=npc_id)

    st = session.states.get(npc_id)
    if not st or not st.alive:
        return NpcIntent(npc_id=npc_id, goal_summary="无力行动", action={"type": "idle"})

    priority = str(raw.get("priority") or "normal")
    if priority not in ("low", "normal", "high"):
        priority = "normal"

    based = raw.get("based_on_beliefs")
    if not isinstance(based, list):
        based = []

    return NpcIntent(
        npc_id=npc_id,
        goal_summary=str(raw.get("goal_summary") or "")[:200],
        action=action,
        priority=priority,
        based_on_beliefs=[str(x) for x in based[:8]],
    )


def resolve_play_order(session: GameSession, queue: list[str], raw_order: Any) -> list[str]:
    """play_order 必须是 queue 的排列；否则按驱动回退。"""
    qset = set(queue)
    if isinstance(raw_order, list):
        cleaned: list[str] = []
        seen: set[str] = set()
        for x in raw_order:
            aid = str(x)
            if aid in qset and aid not in seen:
                cleaned.append(aid)
                seen.add(aid)
        if len(cleaned) == len(queue):
            return cleaned
        # 补上遗漏，保持模型前缀顺序 + 原 queue 相对序
        for aid in queue:
            if aid not in seen:
                cleaned.append(aid)
        return cleaned
    return default_play_order(session, queue)


def parse_night_batch(
    session: GameSession, queue: list[str], raw: dict[str, Any] | None
) -> tuple[dict[str, NpcIntent], list[str]]:
    """
    解析批次结果 → 全覆盖 intents + play_order。
    任何缺口用规则意图补齐。
    """
    raw = raw if isinstance(raw, dict) else {}
    by_id: dict[str, dict[str, Any]] = {}
    intents_raw = raw.get("intents")
    if isinstance(intents_raw, list):
        for item in intents_raw:
            if not isinstance(item, dict):
                continue
            nid = str(item.get("npc_id") or "")
            if nid in queue and nid not in by_id:
                by_id[nid] = item
    elif isinstance(intents_raw, dict):
        for nid, item in intents_raw.items():
            sid = str(nid)
            if sid in queue and isinstance(item, dict) and sid not in by_id:
                item = dict(item)
                item.setdefault("npc_id", sid)
                by_id[sid] = item

    out: dict[str, NpcIntent] = {}
    for nid in queue:
        out[nid] = sanitize_one_intent(session, nid, by_id.get(nid))

    order = resolve_play_order(session, queue, raw.get("play_order"))
    return out, order


def slot_text_leaks_other_private(
    session: GameSession, slot_npc: str, other_npc: str, slot_blob: str
) -> bool:
    """测试辅助：若 other 的私密命题出现在 slot 文本中则视为泄漏。"""
    if other_npc == slot_npc:
        return False
    for b in session.beliefs.get(other_npc) or []:
        prop = (b.proposition or "").strip()
        if len(prop) >= 6 and prop in slot_blob:
            return True
    return False


__all__ = [
    "build_night_batch_messages",
    "night_plan_block",
    "night_slot_payload",
    "parse_night_batch",
    "public_presence_at",
    "sanitize_one_intent",
    "resolve_play_order",
    "slot_text_leaks_other_private",
]
