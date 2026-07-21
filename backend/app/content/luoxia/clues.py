"""
线索事件包：与天道 AdjudicationResult 同构。

「解锁线索」= 模拟天道发来的一包：events + state_ops + belief_ops + world_flag_ops。
引擎不扫台词；LLM 天道直接产出同构字段；Mock/测试用本模块注入。
禁止直写 session。
"""

from __future__ import annotations

from typing import Any
from uuid import uuid4

from app.core.domain.enums import BeliefSource, EventKind, Severity, TruthRel
from app.core.domain.models import BeliefOp, GameSession, StateOp, WorldEvent

CLUE_IDS = frozenset(
    {
        "map_open_law",
        "map_open_mission",
        "map_open_library",
        "map_open_hall",
        "map_open_backhill",
        "letter_exposed",
        "investigate_curse",
        "disarm_curse",
        "expose_lin_su",
        "trust_shi_mei",
        "ally_shi_mei",
        "lin_su_detonate",
        "lin_su_flip",
        "lin_su_frantic",
    }
)


def simulate_tiandao_clue(
    session: GameSession,
    clue_id: str,
    *,
    player_id: str,
    npc_id: str,
    location: str | None,
    map_unlocked_base: list[str] | None = None,
) -> dict[str, Any]:
    """模拟天道因该线索发出的一包 ops/event。"""
    from app.content.luoxia import map_access

    state_ops: list[StateOp] = []
    belief_ops: list[BeliefOp] = []
    events: list[WorldEvent] = []
    world_flag_ops: dict[str, Any] = {}
    narrative = ""
    base = map_unlocked_base

    def ev(title: str, summary: str, *, sev: Severity = Severity.MINOR, tags: list[str] | None = None) -> WorldEvent:
        return WorldEvent(
            event_id=f"clue_{clue_id}_{uuid4().hex[:8]}",
            kind=EventKind.WORLD,
            severity=sev,
            title=title,
            summary=summary,
            actor_ids=[player_id, npc_id],
            location=location,
            day=session.day,
            known_to=[player_id],
            card_headline=title,
            card_body=summary,
            involves_player=True,
            tags=["clue", clue_id, *(tags or [])],
        )

    def bel(
        holder: str,
        bid: str,
        prop: str,
        truth: TruthRel,
        src: BeliefSource = BeliefSource.INFERENCE,
        conf: float = 0.75,
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

    def take_unlocks(*loc_ids: str) -> list[str]:
        nonlocal base
        pkt = map_access.unlock_packet(session, *loc_ids, base=base)
        if pkt.get("world_flag_ops", {}).get("map_unlocked") is not None:
            base = list(pkt["world_flag_ops"]["map_unlocked"])
            world_flag_ops["map_unlocked"] = base
            return list(pkt.get("notes") or [])
        return []

    cid = str(clue_id or "").strip()
    if cid not in CLUE_IDS:
        return {
            "state_ops": [],
            "belief_ops": [],
            "events": [],
            "world_flag_ops": {},
            "narrative_summary": "",
        }

    if cid == "map_open_law":
        if take_unlocks("law"):
            events.append(ev("门径新开", "你获准前往执法堂。", sev=Severity.TRIVIAL, tags=["map_unlock"]))
            narrative = "门径新开：执法堂"
    elif cid == "map_open_mission":
        if take_unlocks("mission"):
            events.append(ev("门径新开", "你获准前往任务堂。", sev=Severity.TRIVIAL, tags=["map_unlock"]))
            narrative = "门径新开：任务堂"
    elif cid == "map_open_library":
        if take_unlocks("library"):
            events.append(ev("门径新开", "你获准前往藏经阁。", sev=Severity.TRIVIAL, tags=["map_unlock"]))
            narrative = "门径新开：藏经阁"
    elif cid == "map_open_hall":
        if take_unlocks("hall"):
            events.append(ev("门径新开", "你获准前往宗主殿。", sev=Severity.TRIVIAL, tags=["map_unlock"]))
            narrative = "门径新开：宗主殿"
    elif cid == "map_open_backhill":
        if take_unlocks("backhill"):
            events.append(ev("门径新开", "你获准前往后山。", sev=Severity.TRIVIAL, tags=["map_unlock"]))
            narrative = "门径新开：后山"

    elif cid == "letter_exposed" and not session.world_flags.get("letter_exposed"):
        world_flag_ops["letter_exposed"] = True
        take_unlocks("library", "mission", "law")
        state_ops.append(StateOp(actor_id=player_id, op="set", path="flags.faction_lean_yun", value=True))
        p_st = session.states.get(player_id)
        old_e = 0
        if p_st:
            try:
                old_e = int((p_st.flags or {}).get("evidence_level") or 0)
            except (TypeError, ValueError):
                old_e = 0
        state_ops.append(
            StateOp(actor_id=player_id, op="set", path="flags.evidence_level", value=max(2, old_e))
        )
        belief_ops.append(
            bel(
                player_id,
                f"letter_exposed_d{session.day}",
                "你愈发确信：秘境机缘的来信恐是假的",
                TruthRel.MATCHES_AUTHORITY,
            )
        )
        events.append(ev("密信疑云", "关于秘境来信的真伪，有了更硬的线索。", tags=["letter"]))
        narrative = "假信之疑被坐实一二。"

    elif cid == "investigate_curse":
        state_ops.append(
            StateOp(actor_id=player_id, op="set", path="flags.investigating_curse", value=True)
        )
        take_unlocks("backhill", "library")
        events.append(ev("查阵之意", "你决意追查护山异常与邪咒踪迹。", tags=["curse"]))
        narrative = "你开始深查护山隐患。"

    elif cid == "disarm_curse" and not session.world_flags.get("blood_curse_disarmed"):
        world_flag_ops["blood_curse_disarmed"] = True
        world_flag_ops["sect_stabilized"] = True
        belief_ops.append(
            bel(
                player_id,
                "curse_disarmed",
                "血阴之患已被暂时镇压",
                TruthRel.MATCHES_AUTHORITY,
                conf=0.85,
            )
        )
        events.append(
            ev("血阴暂镇", "护山隐患被压下一线，大劫或可改写。", sev=Severity.MAJOR, tags=["curse_disarm"])
        )
        narrative = "血阴之患暂镇，阵势稍稳。"

    elif cid == "expose_lin_su":
        lin = session.states.get("er_shi_xiong")
        if lin and not lin.flags.get("exposed"):
            state_ops.append(
                StateOp(actor_id="er_shi_xiong", op="set", path="flags.exposed", value=True)
            )
            state_ops.append(
                StateOp(actor_id=player_id, op="set", path="flags.faction_lean_yun", value=True)
            )
            events.append(
                ev("嫌疑坐实一线", "关于林溯的不轨之嫌，有了正式记录。", sev=Severity.MAJOR, tags=["expose"])
            )
            narrative = "林溯的嫌疑被立案。"

    elif cid == "trust_shi_mei":
        st = session.states.get("shi_mei")
        if st and st.alive:
            try:
                trust = int((st.flags or {}).get("trust_player") or 0) + 1
            except (TypeError, ValueError):
                trust = 1
            state_ops.append(
                StateOp(actor_id="shi_mei", op="set", path="flags.trust_player", value=trust)
            )
            if trust >= 3:
                state_ops.append(
                    StateOp(actor_id="shi_mei", op="set", path="flags.trusts_player", value=True)
                )
                take_unlocks("backhill", "dorm_inner", "library")
            events.append(ev("一丝托付", "洛晴对你流露出难得的信任。", tags=["trust"]))
            narrative = "洛晴对你的防备松了一线。"

    elif cid == "ally_shi_mei":
        st = session.states.get("shi_mei")
        if st and st.alive:
            state_ops.append(
                StateOp(actor_id="shi_mei", op="set", path="flags.ally_player", value=True)
            )
            state_ops.append(
                StateOp(actor_id="shi_mei", op="set", path="flags.arc_shi_mei_ally", value=True)
            )
            state_ops.append(
                StateOp(actor_id="shi_mei", op="set", path="flags.trusts_player", value=True)
            )
            events.append(ev("洛晴同盟", "你们达成默契：共查护山隐患。", sev=Severity.MAJOR, tags=["ally"]))
            narrative = "洛晴愿与你联手。"

    elif cid in ("lin_su_detonate", "lin_su_flip", "lin_su_frantic"):
        stance = {
            "lin_su_detonate": "self_protect",
            "lin_su_flip": "consider_flip",
            "lin_su_frantic": "frantic",
        }[cid]
        lin = session.states.get("er_shi_xiong")
        if lin and lin.alive:
            state_ops.extend(
                [
                    StateOp(
                        actor_id="er_shi_xiong",
                        op="set",
                        path="flags.believes_curse_only_weakens_array",
                        value=False,
                    ),
                    StateOp(
                        actor_id="er_shi_xiong",
                        op="set",
                        path="flags.knows_curse_will_detonate",
                        value=True,
                    ),
                    StateOp(
                        actor_id="er_shi_xiong",
                        op="set",
                        path="flags.shake_stance",
                        value=stance,
                    ),
                ]
            )
            if stance == "consider_flip":
                state_ops.append(
                    StateOp(actor_id=player_id, op="set", path="flags.faction_lean_lin", value=True)
                )
            belief_ops.append(
                bel(
                    "er_shi_xiong",
                    f"lin_su_detonate_{uuid4().hex[:8]}",
                    "若所言非虚，开启仪式约等于引爆护山——玄阴恐要毁宗，而非仅削弱阵势。",
                    TruthRel.MATCHES_AUTHORITY,
                    src=BeliefSource.TOLD_BY,
                    conf=0.82,
                )
            )
            events.append(
                ev(
                    "林溯神色有异",
                    "谈及护山隐患时，林溯笑容僵了一瞬，随即又圆了回来。",
                    tags=["lin_su_shake"],
                )
            )
            narrative = "林溯神色有异。"

    return {
        "state_ops": state_ops,
        "belief_ops": belief_ops,
        "events": events,
        "world_flag_ops": world_flag_ops,
        "narrative_summary": narrative,
    }


def merge_simulated_clues(
    session: GameSession,
    clue_ids: list[str],
    *,
    player_id: str,
    npc_id: str,
    location: str | None,
) -> dict[str, Any]:
    """合并多条模拟天道线索包（供 Mock 注入）。"""
    state_ops: list[StateOp] = []
    belief_ops: list[BeliefOp] = []
    events: list[WorldEvent] = []
    world_flag_ops: dict[str, Any] = {}
    notes: list[str] = []
    seen: set[str] = set()
    pending_map: list[str] | None = None
    for raw in clue_ids or []:
        cid = str(raw or "").strip()
        if not cid or cid in seen:
            continue
        seen.add(cid)
        chunk = simulate_tiandao_clue(
            session,
            cid,
            player_id=player_id,
            npc_id=npc_id,
            location=location,
            map_unlocked_base=pending_map,
        )
        state_ops.extend(chunk.get("state_ops") or [])
        belief_ops.extend(chunk.get("belief_ops") or [])
        events.extend(chunk.get("events") or [])
        for k, v in (chunk.get("world_flag_ops") or {}).items():
            if k == "map_unlocked" and isinstance(v, list):
                pending_map = list(v)
                world_flag_ops["map_unlocked"] = pending_map
            else:
                world_flag_ops[k] = v
        if chunk.get("narrative_summary"):
            notes.append(str(chunk["narrative_summary"]))
    return {
        "state_ops": state_ops,
        "belief_ops": belief_ops,
        "events": events,
        "world_flag_ops": world_flag_ops,
        "notes": notes,
    }
