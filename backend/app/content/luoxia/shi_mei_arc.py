"""
洛晴深度线——产出同构事件包（state_ops / belief_ops / world_flag_ops / events）。
禁止直改 session；由 dialogue_hooks / pack 经 StateApplier 落地。
"""

from __future__ import annotations

from typing import Any
from uuid import uuid4

from app.core.domain.enums import BeliefSource, EventKind, Severity, TruthRel
from app.core.domain.models import BeliefOp, GameSession, StateOp, WorldEvent

SHI_MEI_ID = "shi_mei"

STAGES = [
    {
        "id": "guarded",
        "min_trust": 0,
        "flag": "arc_shi_mei_guarded",
        "player_hint": "小师妹对你仍有防备。",
    },
    {
        "id": "warming",
        "min_trust": 2,
        "flag": "arc_shi_mei_warming",
        "player_hint": "她偶尔会多看你一眼，却仍沉默。",
        "belief": "洛晴似乎并非不愿开口，而是背着极重的嘱托。",
    },
    {
        "id": "hint_treasure",
        "min_trust": 3,
        "flag": "arc_shi_mei_hint",
        "requires_trusts": True,
        "player_hint": "她承认至宝之事与外间传言不同。",
        "belief": "洛晴暗示：宗门至宝「落霞剑髓」其实早已不在「该在的地方」。",
        "world_note": "treasure_hint_shared",
    },
    {
        "id": "partial_truth",
        "min_trust": 5,
        "flag": "arc_shi_mei_partial",
        "requires_trusts": True,
        "player_hint": "她吐露师父临终所托的一角。",
        "belief": "落云子临终曾托洛晴：落霞剑髓遗失之秘在她手中；师父之死或与玄阴下毒有关；不可轻信宗内任何人。",
        "npc_belief": "客卿或许可靠——但遗命与剑髓仍在。",
        "world_note": "luoyun_last_words_partial",
    },
    {
        "id": "ally",
        "min_trust": 7,
        "flag": "arc_shi_mei_ally",
        "requires_trusts": True,
        "player_hint": "洛晴愿与你联手查证血阴与假信。",
        "belief": "洛晴与你达成默契：共查护山隐患与密信真伪。",
        "set_flags": {"ally_player": True},
        "world_note": "shi_mei_allied",
    },
]


def _empty() -> dict[str, Any]:
    return {
        "state_ops": [],
        "belief_ops": [],
        "world_flag_ops": {},
        "events": [],
        "notes": [],
    }


def trust_level(session: GameSession) -> int:
    st = session.states.get(SHI_MEI_ID)
    if not st:
        return 0
    try:
        return int(st.flags.get("trust_player") or 0)
    except (TypeError, ValueError):
        return 0


def advance_on_dialogue(session: GameSession, *, utterance: str = "") -> dict[str, Any]:
    """对话后尝试推进一档；只返回同构包，不写 session。"""
    _ = utterance
    return _try_advance(session, force_soft=True)


def maybe_public_encounter_packet(session: GameSession) -> dict[str, Any]:
    """偶遇：后山对玩家仍锁时，拉回公共区（同构包）。"""
    from app.content.luoxia import map_access

    out = _empty()
    st = session.states.get(SHI_MEI_ID)
    if not st or not st.alive:
        return out
    loc = st.location or ""
    public = ("square", "kitchen", "dorm_outer", "gate")
    if loc in public:
        return out
    if loc == "backhill" and not map_access.location_open_for_player(session, "backhill"):
        out["state_ops"].extend(
            [
                StateOp(actor_id=SHI_MEI_ID, op="set", path="location", value="square"),
                StateOp(
                    actor_id=SHI_MEI_ID,
                    op="set",
                    path="flags.shi_mei_public_encounter",
                    value=True,
                ),
            ]
        )
        out["events"].append(
            WorldEvent(
                event_id=f"shi_mei_enc_{uuid4().hex[:8]}",
                kind=EventKind.WORLD,
                severity=Severity.TRIVIAL,
                title="偶遇·洛晴",
                summary="有人在广场角落看见洛晴驻足片刻，旋又沉默走开。",
                actor_ids=[SHI_MEI_ID],
                location="square",
                day=session.day,
                known_to=[session.player_id()],
                card_headline="偶遇洛晴",
                card_body="她似在人群边缘一闪而过——并非只是后山的传闻。",
                involves_player=True,
                tags=["shi_mei_encounter", "public"],
            )
        )
    return out


def maybe_public_encounter(session: GameSession) -> list[WorldEvent]:
    """兼容旧测试：经 apply_packet 落地后返回 events。"""
    from app.core.services.content_packet import apply_packet

    return apply_packet(session, maybe_public_encounter_packet(session))


def day_end_packet(session: GameSession) -> dict[str, Any]:
    """日终：偶遇 + 静默低阶段推进（同构包，不写 session）。"""
    out = maybe_public_encounter_packet(session)
    soft = _try_advance(session, force_soft=False)
    # 合并时注意：偶遇已改 location 的 ops 尚未落地，_try_advance 仍读旧 location —— 可接受
    out["state_ops"].extend(soft["state_ops"])
    out["belief_ops"].extend(soft["belief_ops"])
    out["world_flag_ops"].update(soft["world_flag_ops"])
    out["events"].extend(soft["events"])
    out["notes"].extend(soft["notes"])
    return out


def advance_on_day_end(session: GameSession) -> list[WorldEvent]:
    """兼容：经 apply_packet 落地日终包。"""
    from app.core.services.content_packet import apply_packet

    return apply_packet(session, day_end_packet(session))


def _try_advance(session: GameSession, *, force_soft: bool) -> dict[str, Any]:
    out = _empty()
    st = session.states.get(SHI_MEI_ID)
    if not st or not st.alive:
        return out
    t = trust_level(session)
    trusts = bool(st.flags.get("trusts_player"))
    # 已有 flag 只读当前 session（同回合多档时用 pending 集合）
    pending_flags: set[str] = set()

    for stage in STAGES:
        flag = stage["flag"]
        if st.flags.get(flag) or flag in pending_flags:
            continue
        if t < int(stage["min_trust"]):
            break
        if stage.get("requires_trusts") and not trusts:
            break
        if stage["id"] in ("partial_truth", "ally") and not force_soft:
            continue
        if stage["id"] == "ally" and not (
            force_soft
            or st.flags.get("ally_player")
            or st.flags.get("arc_shi_mei_ally")
        ):
            continue

        pending_flags.add(flag)
        out["state_ops"].append(
            StateOp(actor_id=SHI_MEI_ID, op="set", path=f"flags.{flag}", value=True)
        )
        for k, v in (stage.get("set_flags") or {}).items():
            out["state_ops"].append(
                StateOp(actor_id=SHI_MEI_ID, op="set", path=f"flags.{k}", value=v)
            )
        if stage.get("world_note"):
            out["world_flag_ops"][stage["world_note"]] = True

        pid = session.player_id()
        if stage.get("belief"):
            out["belief_ops"].append(
                BeliefOp(
                    holder_id=pid,
                    op="upsert",
                    belief_id=f"shi_mei_{stage['id']}_{uuid4().hex[:6]}",
                    proposition=stage["belief"],
                    source=BeliefSource.TOLD_BY,
                    source_detail=SHI_MEI_ID,
                    truth_rel=TruthRel.MATCHES_AUTHORITY,
                    confidence=0.8,
                    day=session.day,
                )
            )
        if stage.get("npc_belief"):
            out["belief_ops"].append(
                BeliefOp(
                    holder_id=SHI_MEI_ID,
                    op="upsert",
                    belief_id=f"shi_mei_self_{stage['id']}",
                    proposition=stage["npc_belief"],
                    source=BeliefSource.SELF,
                    truth_rel=TruthRel.MATCHES_AUTHORITY,
                    confidence=0.9,
                    day=session.day,
                )
            )
        hint = stage.get("player_hint") or stage["id"]
        out["notes"].append(hint)
        out["events"].append(
            WorldEvent(
                kind=EventKind.SOCIAL,
                severity=Severity.MINOR
                if stage["id"] in ("guarded", "warming")
                else Severity.MAJOR,
                title=f"洛晴·{stage['id']}",
                summary=hint,
                actor_ids=[pid, SHI_MEI_ID],
                location=st.location,
                day=session.day,
                known_to=[pid, SHI_MEI_ID],
                card_headline="师妹心防",
                card_body=hint + (("\n" + stage["belief"]) if stage.get("belief") else ""),
                involves_player=True,
                tags=["shi_mei_arc", stage["id"]],
            )
        )
        if force_soft:
            break

    return out
