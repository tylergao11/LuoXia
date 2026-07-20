"""
洛晴深度线——纯内容包数据 + 推进逻辑。
引擎只在 WorldPack.on_day_end / dialogue 钩子调用，不写死在 Graph。
"""

from __future__ import annotations

from typing import Any
from uuid import uuid4

from app.core.domain.enums import BeliefSource, EventKind, Severity, TruthRel
from app.core.domain.models import Belief, GameSession, WorldEvent

SHI_MEI_ID = "shi_mei"

# 阶段：按 trust_player 与 flags 推进（可被玩家加速）
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
        "belief": "洛晴暗示：宗门至宝其实早已不在「该在的地方」。",
        "world_note": "treasure_hint_shared",
    },
    {
        "id": "partial_truth",
        "min_trust": 5,
        "flag": "arc_shi_mei_partial",
        "requires_trusts": True,
        "player_hint": "她吐露师父临终所托的一角。",
        "belief": "落云子临终曾托洛晴：至宝遗失多年，不可轻信宗内任何人。",
        "npc_belief": "客卿或许可靠——但遗命仍在。",
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


def trust_level(session: GameSession) -> int:
    st = session.states.get(SHI_MEI_ID)
    if not st:
        return 0
    try:
        return int(st.flags.get("trust_player") or 0)
    except (TypeError, ValueError):
        return 0


def advance_on_dialogue(
    session: GameSession, *, utterance: str
) -> dict[str, Any]:
    """对话后尝试推进阶段；返回 notes / events 由调用方合并。"""
    return _try_advance(session, force_soft=True, utterance=utterance)


def advance_on_day_end(session: GameSession) -> list[WorldEvent]:
    """日终若信任已够，可静默推进低阶段；事件需写入 session。"""
    out = _try_advance(session, force_soft=False, utterance="")
    events = list(out.get("events") or [])
    for e in events:
        session.events.append(e)
    return events


def _try_advance(
    session: GameSession, *, force_soft: bool, utterance: str
) -> dict[str, Any]:
    st = session.states.get(SHI_MEI_ID)
    if not st or not st.alive:
        return {"events": [], "notes": []}
    t = trust_level(session)
    trusts = bool(st.flags.get("trusts_player"))
    events: list[WorldEvent] = []
    notes: list[str] = []

    for stage in STAGES:
        flag = stage["flag"]
        if st.flags.get(flag):
            continue
        if t < int(stage["min_trust"]):
            break
        if stage.get("requires_trusts") and not trusts:
            break
        # 高阶段需要对话触发（避免挂机白给）
        if stage["id"] in ("partial_truth", "ally") and not force_soft:
            continue
        if stage["id"] == "ally" and not any(
            k in utterance for k in ("一起", "联手", "帮你查", "我们")
        ):
            if force_soft:
                continue

        st.flags[flag] = True
        for k, v in (stage.get("set_flags") or {}).items():
            st.flags[k] = v
        if stage.get("world_note"):
            session.world_flags[stage["world_note"]] = True

        pid = session.player_id()
        if stage.get("belief"):
            session.beliefs.setdefault(pid, []).append(
                Belief(
                    belief_id=f"shi_mei_{stage['id']}_{uuid4().hex[:6]}",
                    holder_id=pid,
                    proposition=stage["belief"],
                    source=BeliefSource.TOLD_BY,
                    source_detail=SHI_MEI_ID,
                    truth_rel=TruthRel.MATCHES_AUTHORITY,
                    confidence=0.8,
                    day=session.day,
                    planted_day=session.day,
                    hop=0,
                )
            )
        if stage.get("npc_belief"):
            session.beliefs.setdefault(SHI_MEI_ID, []).append(
                Belief(
                    belief_id=f"shi_mei_self_{stage['id']}",
                    holder_id=SHI_MEI_ID,
                    proposition=stage["npc_belief"],
                    source=BeliefSource.SELF,
                    truth_rel=TruthRel.MATCHES_AUTHORITY,
                    confidence=0.9,
                    day=session.day,
                    planted_day=session.day,
                )
            )
        hint = stage.get("player_hint") or stage["id"]
        notes.append(hint)
        events.append(
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
        # 一次对话最多推进一档
        if force_soft:
            break

    # 事件交给裁决结果 apply，避免重复写入
    return {"events": events, "notes": notes}
