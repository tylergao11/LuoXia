"""落霞危机 tick——内容包职责；只回同构包，不写 session。"""

from __future__ import annotations

from typing import Any

from app.core.domain.enums import BeliefSource, EventKind, Severity, TruthRel
from app.core.domain.models import BeliefOp, GameSession, WorldEvent


class CrisisTick:
    """
    读落霞 world_flags：
    - countdown==0 且 blood_curse_planted 且未 disarmed → 护山危局
    - countdown==0 且已 disarmed → 化险为夷
    """

    def as_packet(
        self,
        session: GameSession,
        *,
        flags_overlay: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        flags = {**(session.world_flags or {}), **(flags_overlay or {})}
        world_flag_ops: dict[str, Any] = {}
        belief_ops: list[BeliefOp] = []
        events: list[WorldEvent] = []

        try:
            cd = int(flags.get("xuanyin_countdown", -1))
        except (TypeError, ValueError):
            cd = -1

        disarmed = bool(flags.get("blood_curse_disarmed") or flags.get("sect_stabilized"))
        planted = bool(flags.get("blood_curse_planted"))

        if cd == 0 and planted and not disarmed and not flags.get("crisis_fired"):
            world_flag_ops["crisis_fired"] = True
            world_flag_ops["sect_at_brink"] = True
            prop = "天地异象大作，护山阵剧烈震颤，恐有大祸"
            belief_ops.extend(self._broadcast_belief_ops(session, prop, TruthRel.MATCHES_AUTHORITY))
            known = [a for a, st in session.states.items() if st.alive]
            events.append(
                WorldEvent(
                    kind=EventKind.WORLD,
                    severity=Severity.CRITICAL,
                    title="护山异变",
                    summary=prop,
                    actor_ids=[],
                    location=None,
                    day=session.day,
                    known_to=known,
                    card_headline="大劫将至",
                    card_body=prop + "。有人仍以为是「秘境开启」之兆。",
                    involves_player=session.player_id() in known,
                    tags=["crisis", "countdown_zero", "tragedy_gravity"],
                )
            )

        elif cd == 0 and planted and disarmed and not flags.get("crisis_averted_noted"):
            world_flag_ops["crisis_averted_noted"] = True
            world_flag_ops["sect_at_brink"] = False
            prop = "开启之日已至，山门震动片刻，却被先手镇压，化险为夷"
            belief_ops.extend(self._broadcast_belief_ops(session, prop, TruthRel.MATCHES_AUTHORITY))
            known = [a for a, st in session.states.items() if st.alive]
            events.append(
                WorldEvent(
                    kind=EventKind.WORLD,
                    severity=Severity.MAJOR,
                    title="化险为夷",
                    summary=prop,
                    actor_ids=[session.player_id()],
                    day=session.day,
                    known_to=known,
                    card_headline="劫数改写",
                    card_body=prop + "。若无人先手，此日或是宗门末日。",
                    involves_player=True,
                    tags=["crisis_averted", "countdown_zero", "player_agency"],
                )
            )

        if cd in (10, 3) and not flags.get(f"countdown_ping_{cd}"):
            world_flag_ops[f"countdown_ping_{cd}"] = True
            if disarmed:
                prop = f"距传闻「开启之日」约 {cd} 天；你已知阵上有备，心中稍定"
            else:
                prop = f"距传闻中的「开启之日」大约还有 {cd} 天"
            pid = session.player_id()
            belief_ops.append(
                BeliefOp(
                    holder_id=pid,
                    op="upsert",
                    belief_id=f"countdown_ping_{cd}",
                    proposition=prop,
                    source=BeliefSource.RUMOR,
                    truth_rel=TruthRel.UNKNOWN_TO_AUTHORITY,
                    confidence=0.6,
                    day=session.day,
                )
            )
            events.append(
                WorldEvent(
                    kind=EventKind.WORLD,
                    severity=Severity.MINOR if cd == 10 else Severity.MAJOR,
                    title="期限将近",
                    summary=prop,
                    actor_ids=[pid],
                    day=session.day,
                    known_to=[pid],
                    card_headline="时限",
                    card_body=prop,
                    involves_player=True,
                    tags=["countdown_ping"],
                )
            )

        return {
            "state_ops": [],
            "belief_ops": belief_ops,
            "events": events,
            "world_flag_ops": world_flag_ops,
            "notes": [],
        }

    def _broadcast_belief_ops(
        self, session: GameSession, prop: str, truth: TruthRel
    ) -> list[BeliefOp]:
        ops: list[BeliefOp] = []
        for aid, st in session.states.items():
            if not st.alive:
                continue
            ops.append(
                BeliefOp(
                    holder_id=aid,
                    op="upsert",
                    belief_id=f"crisis_d{session.day}_{aid}",
                    proposition=prop,
                    source=BeliefSource.WITNESS,
                    truth_rel=truth,
                    confidence=0.85,
                    day=session.day,
                )
            )
        return ops
