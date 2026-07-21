"""
林溯动摇：日终信念同步；对话动摇由天道事件包（clues.lin_su_*）发放。
只回同构包，不写 session。
"""

from __future__ import annotations

from typing import Any
from uuid import uuid4

from app.core.domain.enums import EventKind, Severity
from app.core.domain.models import GameSession, StateOp, WorldEvent

LIN_SU_ID = "er_shi_xiong"

# 炸宗认知：只认 belief_id 前缀（天道/线索包写入），不扫命题词表
DETONATE_BELIEF_PREFIX = "lin_su_detonate"


def already_shaken(session: GameSession) -> bool:
    st = session.states.get(LIN_SU_ID)
    if not st:
        return False
    return bool((st.flags or {}).get("knows_curse_will_detonate"))


def lin_su_has_detonate_belief(session: GameSession) -> bool:
    for b in session.beliefs.get(LIN_SU_ID, []):
        if (b.belief_id or "").startswith(DETONATE_BELIEF_PREFIX):
            return True
    return False


def sync_shake_packet(session: GameSession) -> dict[str, Any]:
    """日终：信念已含炸宗认知则补硬状态（同构包）。"""
    empty = {
        "state_ops": [],
        "belief_ops": [],
        "events": [],
        "world_flag_ops": {},
        "notes": [],
    }
    if already_shaken(session) or not lin_su_has_detonate_belief(session):
        return empty
    st = session.states.get(LIN_SU_ID)
    if not st or not st.alive:
        return empty
    pid = session.player_id()
    stance = st.flags.get("shake_stance") or "self_protect"
    return {
        "state_ops": [
            StateOp(
                actor_id=LIN_SU_ID,
                op="set",
                path="flags.believes_curse_only_weakens_array",
                value=False,
            ),
            StateOp(
                actor_id=LIN_SU_ID,
                op="set",
                path="flags.knows_curse_will_detonate",
                value=True,
            ),
            StateOp(
                actor_id=LIN_SU_ID,
                op="set",
                path="flags.shake_stance",
                value=stance,
            ),
        ],
        "belief_ops": [],
        "events": [
            WorldEvent(
                event_id=f"lin_su_shake_sync_{uuid4().hex[:8]}",
                kind=EventKind.SOCIAL,
                severity=Severity.TRIVIAL,
                title="林溯神色有异",
                summary="林溯近日谈及护山时，眼神总有一瞬躲闪。",
                actor_ids=[pid, LIN_SU_ID],
                location=st.location,
                day=session.day,
                known_to=[pid],
                card_headline="林溯神色有异",
                card_body="他似已听见某种可怕的可能，却未对人明说。",
                involves_player=True,
                tags=["lin_su_shake", "belief_sync", "hard_state"],
            )
        ],
        "world_flag_ops": {},
        "notes": [],
    }


# 兼容旧测试名
def sync_shake_from_beliefs(session: GameSession) -> list[WorldEvent]:
    """测试兼容：apply 后返回 events。生产路径请用 sync_shake_packet。"""
    from app.core.services.content_packet import apply_packet

    packet = sync_shake_packet(session)
    return apply_packet(session, packet)
