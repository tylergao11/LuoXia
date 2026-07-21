"""
落霞线索 = **条件触发 → 固定事件包**（同构 ContentPacket）。

设计：
- 世界只暂停在种子（人设、背景、隐患 flags）；无后续假剧本。
- 故事由 NPC + 天道共写。
- 线索只做「硬钩子」：首次对话某人、首次抵达某地等 → 派发写死的一包 events/ops。
- 每条 once，记在 world_flags.fired_clues。
"""

from __future__ import annotations

from typing import Any, Callable
from uuid import uuid4

from app.core.domain.enums import BeliefSource, EventKind, Severity, TruthRel
from app.core.domain.models import BeliefOp, GameSession, StateOp, WorldEvent
from app.core.services.content_packet import empty_packet, merge_packets

FIRED_KEY = "fired_clues"

PacketBuilder = Callable[[GameSession, dict[str, Any]], dict[str, Any]]


def fired_ids(session: GameSession) -> list[str]:
    raw = (session.world_flags or {}).get(FIRED_KEY)
    if not isinstance(raw, list):
        return []
    return [str(x) for x in raw]


def _mark_fired(session: GameSession, clue_id: str, pending: list[str] | None = None) -> dict[str, Any]:
    base = list(pending if pending is not None else fired_ids(session))
    if clue_id not in base:
        base.append(clue_id)
    return {FIRED_KEY: base}


def _empty() -> dict[str, Any]:
    return empty_packet()


def _ev(
    session: GameSession,
    *,
    clue_id: str,
    title: str,
    body: str,
    actor_ids: list[str],
    location: str | None,
    sev: Severity = Severity.MINOR,
    tags: list[str] | None = None,
    belief_ids: list[str] | None = None,
) -> WorldEvent:
    """场面叙事只在 card_body；见闻命题在 belief_ops，此处仅挂 belief_ids 引用。"""
    pid = session.player_id()
    known = list(dict.fromkeys([pid, *[a for a in actor_ids if a]]))
    meta: dict[str, Any] = {}
    if belief_ids:
        meta["belief_ids"] = list(belief_ids)
    return WorldEvent(
        event_id=f"clue_{clue_id}_{uuid4().hex[:8]}",
        kind=EventKind.WORLD,
        severity=sev,
        title=title,
        summary=body[:120],
        actor_ids=list(actor_ids),
        location=location,
        day=session.day,
        known_to=known,
        card_headline=title,
        card_body=body,
        involves_player=pid in known,
        tags=["clue", "trigger", clue_id, *(tags or [])],
        meta=meta,
    )


def _bel(
    session: GameSession,
    holder: str,
    bid: str,
    prop: str,
    *,
    truth: TruthRel = TruthRel.UNKNOWN_TO_AUTHORITY,
    src: BeliefSource = BeliefSource.INFERENCE,
    conf: float = 0.7,
) -> BeliefOp:
    return BeliefOp(
        holder_id=holder,
        op="upsert",
        belief_id=bid,
        proposition=prop,
        source=src,
        truth_rel=truth,
        confidence=conf,
        day=session.day,
    )


# ----- packet builders（固定内容，非 LLM） -----


def _pkt_first_talk_yun(session: GameSession, ctx: dict[str, Any]) -> dict[str, Any]:
    pid, npc = ctx["player_id"], ctx["npc_id"]
    loc = ctx.get("location")
    name = session.profiles[npc].display_name if npc in session.profiles else npc
    body = (
        f"你第一次与{name}正色交谈。他并未把你当空气，"
        "话里却带着对外来客卿的分寸——既有礼，也有观察。"
    )
    return {
        "state_ops": [
            StateOp(actor_id=pid, op="set", path="flags._met_da_shi_xiong", value=True),
        ],
        "belief_ops": [
            _bel(
                session,
                pid,
                "clue_first_talk_yun",
                f"你与{name}有了正式来往；他似乎在掂量你的来历与用心。",
                truth=TruthRel.MATCHES_AUTHORITY,
                src=BeliefSource.WITNESS,
                conf=0.85,
            ),
        ],
        "events": [
            _ev(
                session,
                clue_id="first_talk_da_shi_xiong",
                title="初见·云烨",
                body=body,
                actor_ids=[pid, npc],
                location=loc,
                sev=Severity.MINOR,
                tags=["first_talk", "social"],
            )
        ],
        "world_flag_ops": {},
        "notes": [],
    }


def _pkt_first_talk_lin(session: GameSession, ctx: dict[str, Any]) -> dict[str, Any]:
    pid, npc = ctx["player_id"], ctx["npc_id"]
    loc = ctx.get("location")
    name = session.profiles[npc].display_name if npc in session.profiles else npc
    body = (
        f"{name}笑意温润，话锋却滑。你说的每句，他都能圆过去——"
        "像把你当贵客，也像在听你到底知道多少。"
    )
    return {
        "state_ops": [
            StateOp(actor_id=pid, op="set", path="flags._met_er_shi_xiong", value=True),
        ],
        "belief_ops": [
            _bel(
                session,
                pid,
                "clue_first_talk_lin",
                f"{name}很好相处，却让人说不清他真正站在哪一边。",
                conf=0.65,
            ),
        ],
        "events": [
            _ev(
                session,
                clue_id="first_talk_er_shi_xiong",
                title="初见·林溯",
                body=body,
                actor_ids=[pid, npc],
                location=loc,
                tags=["first_talk", "social"],
            )
        ],
        "world_flag_ops": {},
        "notes": [],
    }


def _pkt_first_talk_shi_mei(session: GameSession, ctx: dict[str, Any]) -> dict[str, Any]:
    pid, npc = ctx["player_id"], ctx["npc_id"]
    loc = ctx.get("location")
    body = (
        "洛晴话极少。她看你的眼神里没有敌意，却也没有接纳——"
        "像隔着一层薄冰。你感觉她在藏着什么，但她什么也没说。"
    )
    return {
        "state_ops": [
            StateOp(actor_id=pid, op="set", path="flags._met_shi_mei", value=True),
            StateOp(actor_id=npc, op="set", path="flags._noticed_player", value=True),
        ],
        "belief_ops": [
            _bel(
                session,
                pid,
                "clue_first_talk_shi_mei",
                "洛晴不愿多言；她身上似有不可对人言的重负。",
                conf=0.7,
            ),
        ],
        "events": [
            _ev(
                session,
                clue_id="first_talk_shi_mei",
                title="初见·洛晴",
                body=body,
                actor_ids=[pid, npc],
                location=loc,
                sev=Severity.MINOR,
                tags=["first_talk", "social"],
            )
        ],
        "world_flag_ops": {},
        "notes": [],
    }


def _pkt_first_talk_fa(session: GameSession, ctx: dict[str, Any]) -> dict[str, Any]:
    pid, npc = ctx["player_id"], ctx["npc_id"]
    loc = ctx.get("location")
    name = session.profiles[npc].display_name if npc in session.profiles else npc
    body = (
        f"{name}言辞简硬。客卿在他眼中先是「是否安分」，"
        "而不是「是否可亲」。你被点到了规矩的边缘。"
    )
    return {
        "state_ops": [
            StateOp(actor_id=pid, op="set", path="flags._met_zhang_lao_fa", value=True),
        ],
        "belief_ops": [
            _bel(
                session,
                pid,
                "clue_first_talk_fa",
                f"{name}重规矩；在他面前妄言易惹事。",
                truth=TruthRel.MATCHES_AUTHORITY,
                src=BeliefSource.WITNESS,
                conf=0.8,
            ),
        ],
        "events": [
            _ev(
                session,
                clue_id="first_talk_zhang_lao_fa",
                title="初见·执法",
                body=body,
                actor_ids=[pid, npc],
                location=loc,
                tags=["first_talk", "law"],
            )
        ],
        "world_flag_ops": {},
        "notes": [],
    }


def _pkt_first_talk_tang(session: GameSession, ctx: dict[str, Any]) -> dict[str, Any]:
    pid, npc = ctx["player_id"], ctx["npc_id"]
    loc = ctx.get("location")
    body = (
        "任务堂主谈起「机缘」时两眼放光，对秘境之说十分上心。"
        "他把许多希望押在一封来信上——至于真假，他似乎不愿深想。"
    )
    return {
        "state_ops": [
            StateOp(actor_id=pid, op="set", path="flags._met_ren_wu_tang_zhu", value=True),
            StateOp(actor_id=pid, op="set", path="flags.heard_letter", value=True),
        ],
        "belief_ops": [
            _bel(
                session,
                pid,
                "clue_first_talk_mission",
                "任务堂极重「秘境机缘」与来信；宗内不少人跟着热起来。",
                conf=0.75,
            ),
        ],
        "events": [
            _ev(
                session,
                clue_id="first_talk_ren_wu_tang_zhu",
                title="初见·任务堂",
                body=body,
                actor_ids=[pid, npc],
                location=loc,
                tags=["first_talk", "letter_hook"],
            )
        ],
        "world_flag_ops": {},
        "notes": [],
    }


def _pkt_arrive_square(session: GameSession, ctx: dict[str, Any]) -> dict[str, Any]:
    pid = ctx["player_id"]
    loc = ctx.get("location") or "square"
    body = (
        "落霞广场人声与靴声混成一片。有人谈护山异动，有人谈秘境将开——"
        "像一场尚未开锣的戏，锣鼓却已经在远处响了。"
    )
    return {
        "state_ops": [
            StateOp(actor_id=pid, op="set", path="flags._visited_square", value=True),
        ],
        "belief_ops": [
            _bel(
                session,
                pid,
                "clue_arrive_square",
                "广场上「秘境」与「护山异象」的议论此起彼伏。",
                conf=0.7,
            ),
        ],
        "events": [
            _ev(
                session,
                clue_id="first_arrive_square",
                title="初至广场",
                body=body,
                actor_ids=[pid],
                location=loc,
                tags=["arrive", "public"],
            )
        ],
        "world_flag_ops": {},
        "notes": [],
    }


def _pkt_arrive_library(session: GameSession, ctx: dict[str, Any]) -> dict[str, Any]:
    pid = ctx["player_id"]
    loc = ctx.get("location") or "library"
    body = (
        "藏经阁尘味与纸香并重。明镜未必会见你，"
        "但架上旧录像在提醒：有些事写在纸上，比写在嘴里更危险。"
    )
    return {
        "state_ops": [
            StateOp(actor_id=pid, op="set", path="flags._visited_library", value=True),
        ],
        "belief_ops": [
            _bel(
                session,
                pid,
                "clue_arrive_library",
                "藏经阁可能藏着与宗门旧事相关的记载。",
                conf=0.6,
            ),
        ],
        "events": [
            _ev(
                session,
                clue_id="first_arrive_library",
                title="初入藏经阁",
                body=body,
                actor_ids=[pid],
                location=loc,
                sev=Severity.MINOR,
                tags=["arrive", "archive"],
            )
        ],
        "world_flag_ops": {},
        "notes": [],
    }


def _pkt_arrive_backhill(session: GameSession, ctx: dict[str, Any]) -> dict[str, Any]:
    pid = ctx["player_id"]
    loc = ctx.get("location") or "backhill"
    body = (
        "后山风更冷。树影里像有人走过，又像没有。"
        "你隐隐觉得：这里不适合大声说话。"
    )
    return {
        "state_ops": [
            StateOp(actor_id=pid, op="set", path="flags._visited_backhill", value=True),
        ],
        "belief_ops": [
            _bel(
                session,
                pid,
                "clue_arrive_backhill",
                "后山安静得反常，似不宜久留，也不宜声张。",
                conf=0.65,
            ),
        ],
        "events": [
            _ev(
                session,
                clue_id="first_arrive_backhill",
                title="初入后山",
                body=body,
                actor_ids=[pid],
                location=loc,
                sev=Severity.MINOR,
                tags=["arrive", "secluded"],
            )
        ],
        "world_flag_ops": {},
        "notes": [],
    }


def _pkt_arrive_law(session: GameSession, ctx: dict[str, Any]) -> dict[str, Any]:
    pid = ctx["player_id"]
    loc = ctx.get("location") or "law"
    body = (
        "执法堂门槛沉。案牍与刑具不必全看见，气压已经够了。"
        "客卿踏入此地，本身就是一则记录。"
    )
    return {
        "state_ops": [
            StateOp(actor_id=pid, op="set", path="flags._visited_law", value=True),
        ],
        "belief_ops": [
            _bel(
                session,
                pid,
                "clue_arrive_law",
                "执法堂重地；在这里的言行都会被人掂量。",
                truth=TruthRel.MATCHES_AUTHORITY,
                src=BeliefSource.WITNESS,
                conf=0.85,
            ),
        ],
        "events": [
            _ev(
                session,
                clue_id="first_arrive_law",
                title="初入执法堂",
                body=body,
                actor_ids=[pid],
                location=loc,
                tags=["arrive", "law"],
            )
        ],
        "world_flag_ops": {},
        "notes": [],
    }


def _pkt_leave_dorm_first(session: GameSession, ctx: dict[str, Any]) -> dict[str, Any]:
    pid = ctx["player_id"]
    to_loc = ctx.get("location")
    body = (
        "你第一次离开外门客居往宗门深处走。门槛外的世界不会自动对你友好——"
        "路要自己走，闲话也会自己长。"
    )
    return {
        "state_ops": [
            StateOp(actor_id=pid, op="set", path="flags._left_dorm_once", value=True),
        ],
        "belief_ops": [
            _bel(
                session,
                pid,
                "clue_leave_dorm",
                "客居之外，宗门另有一套运转；你已踏出第一步。",
                truth=TruthRel.MATCHES_AUTHORITY,
                src=BeliefSource.SELF,
                conf=0.9,
            ),
        ],
        "events": [
            _ev(
                session,
                clue_id="first_leave_dorm_outer",
                title="跨出客居",
                body=body,
                actor_ids=[pid],
                location=to_loc,
                tags=["move", "onboarding"],
            )
        ],
        "world_flag_ops": {},
        "notes": [],
    }


def _pkt_third_talk_shi_mei(session: GameSession, ctx: dict[str, Any]) -> dict[str, Any]:
    """与洛晴累计第 3 次对话（次数由 flags 累加，非台词关键词）。"""
    pid, npc = ctx["player_id"], ctx["npc_id"]
    loc = ctx.get("location")
    body = (
        "这已是你第三次与她说话。冰没有化，但裂开了一丝："
        "她不再立刻走开，只是把话压得更短。"
    )
    return {
        "state_ops": [
            StateOp(actor_id=npc, op="set", path="flags._talk_depth_player", value=3),
        ],
        "belief_ops": [
            _bel(
                session,
                pid,
                "clue_shi_mei_talk3",
                "洛晴对你仍防备，但已不像初见时那般拒人于千里。",
                conf=0.7,
            ),
        ],
        "events": [
            _ev(
                session,
                clue_id="talk_shi_mei_third",
                title="再近一步",
                body=body,
                actor_ids=[pid, npc],
                location=loc,
                sev=Severity.MINOR,
                tags=["talk_count", "social"],
            )
        ],
        "world_flag_ops": {},
        "notes": [],
    }


# ----- 注册表 -----

# when: kind=talk|move
# npc_id / location_id / from_location / talk_count_npc / talk_count_min
CLUE_DEFS: list[dict[str, Any]] = [
    {
        "id": "first_talk_da_shi_xiong",
        "kind": "talk",
        "npc_id": "da_shi_xiong",
        "build": _pkt_first_talk_yun,
    },
    {
        "id": "first_talk_er_shi_xiong",
        "kind": "talk",
        "npc_id": "er_shi_xiong",
        "build": _pkt_first_talk_lin,
    },
    {
        "id": "first_talk_shi_mei",
        "kind": "talk",
        "npc_id": "shi_mei",
        "build": _pkt_first_talk_shi_mei,
    },
    {
        "id": "first_talk_zhang_lao_fa",
        "kind": "talk",
        "npc_id": "zhang_lao_fa",
        "build": _pkt_first_talk_fa,
    },
    {
        "id": "first_talk_ren_wu_tang_zhu",
        "kind": "talk",
        "npc_id": "ren_wu_tang_zhu",
        "build": _pkt_first_talk_tang,
    },
    {
        "id": "talk_shi_mei_third",
        "kind": "talk",
        "npc_id": "shi_mei",
        "talk_count_min": 3,
        "build": _pkt_third_talk_shi_mei,
    },
    {
        "id": "first_arrive_square",
        "kind": "move",
        "location_id": "square",
        "build": _pkt_arrive_square,
    },
    {
        "id": "first_arrive_library",
        "kind": "move",
        "location_id": "library",
        "build": _pkt_arrive_library,
    },
    {
        "id": "first_arrive_backhill",
        "kind": "move",
        "location_id": "backhill",
        "build": _pkt_arrive_backhill,
    },
    {
        "id": "first_arrive_law",
        "kind": "move",
        "location_id": "law",
        "build": _pkt_arrive_law,
    },
    {
        "id": "first_leave_dorm_outer",
        "kind": "move",
        "from_location": "dorm_outer",
        "build": _pkt_leave_dorm_first,
    },
]


def _talk_count(session: GameSession, npc_id: str) -> int:
    """内部计数，存 flags._talk_count_<npc>，不进玩家 UI。"""
    st = session.states.get(session.player_id())
    if not st:
        return 0
    key = f"_talk_count_{npc_id}"
    try:
        return int((st.flags or {}).get(key) or 0)
    except (TypeError, ValueError):
        return 0


def _match(
    defn: dict[str, Any],
    *,
    kind: str,
    ctx: dict[str, Any],
    session: GameSession,
    talk_count_after: int | None = None,
) -> bool:
    if defn.get("kind") != kind:
        return False
    if kind == "talk":
        if defn.get("npc_id") and defn["npc_id"] != ctx.get("npc_id"):
            return False
        need = defn.get("talk_count_min")
        if need is not None:
            n = talk_count_after if talk_count_after is not None else _talk_count(
                session, str(ctx.get("npc_id") or "")
            )
            if n < int(need):
                return False
        return True
    if kind == "move":
        if defn.get("location_id") and defn["location_id"] != ctx.get("location"):
            return False
        if defn.get("from_location") and defn["from_location"] != ctx.get("from_location"):
            return False
        return True
    return False


def _link_event_beliefs(packet: dict[str, Any]) -> dict[str, Any]:
    """同包内：events.meta.belief_ids ← belief_ops.belief_id（引用，不复述命题）。"""
    bids: list[str] = []
    for op in packet.get("belief_ops") or []:
        bid = getattr(op, "belief_id", None)
        if bid is None and isinstance(op, dict):
            bid = op.get("belief_id")
        if bid:
            bids.append(str(bid))
    if not bids:
        return packet
    for ev in packet.get("events") or []:
        if hasattr(ev, "meta"):
            meta = dict(ev.meta or {})
            meta["belief_ids"] = list(dict.fromkeys([*(meta.get("belief_ids") or []), *bids]))
            ev.meta = meta
        elif isinstance(ev, dict):
            meta = dict(ev.get("meta") or {})
            meta["belief_ids"] = list(dict.fromkeys([*(meta.get("belief_ids") or []), *bids]))
            ev["meta"] = meta
    return packet


def collect_trigger_packets(
    session: GameSession,
    *,
    kind: str,
    player_id: str,
    npc_id: str | None = None,
    location: str | None = None,
    from_location: str | None = None,
) -> dict[str, Any]:
    """
    评估可触发线索，返回合并后的同构包（含 fired_clues 更新）。
    不直写 session；对话计数以 state_ops 形式带出。
    """
    ctx = {
        "player_id": player_id,
        "npc_id": npc_id,
        "location": location,
        "from_location": from_location,
    }
    already = set(fired_ids(session))
    pending_fired = list(fired_ids(session))
    parts: list[dict[str, Any]] = []

    count_ops: list[StateOp] = []
    talk_after: int | None = None
    if kind == "talk" and npc_id:
        talk_after = _talk_count(session, npc_id) + 1
        count_ops.append(
            StateOp(
                actor_id=player_id,
                op="set",
                path=f"flags._talk_count_{npc_id}",
                value=talk_after,
            )
        )

    for defn in CLUE_DEFS:
        cid = str(defn["id"])
        if cid in already:
            continue
        if not _match(
            defn,
            kind=kind,
            ctx=ctx,
            session=session,
            talk_count_after=talk_after,
        ):
            continue
        build: PacketBuilder = defn["build"]
        pkt = _link_event_beliefs(build(session, ctx) or _empty())
        pending_fired = list(_mark_fired(session, cid, pending_fired)[FIRED_KEY])
        pkt.setdefault("world_flag_ops", {})
        pkt["world_flag_ops"][FIRED_KEY] = list(pending_fired)
        parts.append(pkt)
        already.add(cid)

    out = merge_packets(*parts) if parts else _empty()
    if count_ops:
        out["state_ops"] = list(count_ops) + list(out.get("state_ops") or [])
    return out


def packet_for_clue_id(
    session: GameSession,
    clue_id: str,
    *,
    player_id: str,
    npc_id: str = "",
    location: str | None = None,
) -> dict[str, Any]:
    """按 id 取固定包；已触发则空。"""
    cid = str(clue_id or "").strip()
    if not cid or cid in set(fired_ids(session)):
        return _empty()
    for defn in CLUE_DEFS:
        if defn["id"] != cid:
            continue
        ctx = {
            "player_id": player_id,
            "npc_id": npc_id or defn.get("npc_id") or "",
            "location": location,
            "from_location": None,
        }
        pkt = _link_event_beliefs(defn["build"](session, ctx) or _empty())
        fired = _mark_fired(session, cid)
        pkt.setdefault("world_flag_ops", {})
        pkt["world_flag_ops"].update(fired)
        return pkt
    return _empty()


def inject_clue_packets(
    session: GameSession,
    clue_ids: list[str],
    *,
    player_id: str,
    npc_id: str,
    location: str | None,
) -> dict[str, Any]:
    """按线索 id 列表注入固定包。"""
    parts = [
        packet_for_clue_id(
            session, cid, player_id=player_id, npc_id=npc_id, location=location
        )
        for cid in (clue_ids or [])
    ]
    return merge_packets(*parts) if parts else _empty()
