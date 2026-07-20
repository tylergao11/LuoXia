from __future__ import annotations

from typing import Any

from app.core.domain.enums import BeliefSource, EventKind, Severity, TruthRel
from app.core.domain.models import AdjudicationResult, BeliefOp, GameSession, WorldEvent


class ProclamationService:
    """
    权职通告：将 proclamation 展开为全员（或 scope）信念 + 事件。
    是否有权：profiles.can_proclaim 或 identity.can_proclaim。
    """

    def expand(
        self, session: GameSession, result: AdjudicationResult
    ) -> AdjudicationResult:
        proc = result.proclamation
        if not proc or not isinstance(proc, dict):
            return result
        by = str(proc.get("by") or "")
        content = str(proc.get("content") or "").strip()
        if not by or not content:
            return result
        if not self._can_proclaim(session, by):
            return result

        scope = str(proc.get("scope") or "sect")
        holders = self._holders(session, scope)
        name = (
            session.profiles[by].display_name if by in session.profiles else by
        )
        belief_id = str(proc.get("belief_id") or f"proclamation_d{session.day}_{by}")

        ops = list(result.belief_ops)
        truth = self._truth(proc)
        for hid in holders:
            ops.append(
                BeliefOp(
                    holder_id=hid,
                    op="upsert",
                    belief_id=belief_id,
                    proposition=content,
                    source=BeliefSource.PROCLAMATION,
                    source_detail=f"{name}通告",
                    truth_rel=truth,
                    confidence=float(proc.get("confidence") or 0.85),
                    day=session.day,
                )
            )

        events = list(result.events)
        events.append(
            WorldEvent(
                kind=EventKind.LAW,
                severity=Severity.MAJOR,
                title=f"通告：{content[:20]}",
                summary=f"{name}向宗门通告：{content}",
                actor_ids=[by],
                location=session.states[by].location if by in session.states else None,
                day=session.day,
                known_to=holders,
                card_headline="宗门通告",
                card_body=content,
                involves_player=session.player_id() in holders,
                tags=["proclamation"],
            )
        )

        result.belief_ops = ops
        result.events = events
        return result

    def _can_proclaim(self, session: GameSession, actor_id: str) -> bool:
        prof = session.profiles.get(actor_id)
        if prof and prof.can_proclaim:
            return True
        st = session.states.get(actor_id)
        if st and st.identity.get("can_proclaim"):
            return True
        return False

    def _holders(self, session: GameSession, scope: str) -> list[str]:
        if scope == "local":
            # 仅同地——需要 by 的位置，此处简化全宗
            pass
        return [
            aid
            for aid, st in session.states.items()
            if st.alive
        ]

    def _truth(self, proc: dict[str, Any]) -> TruthRel:
        raw = proc.get("truth_rel") or "unknown_to_authority"
        try:
            return TruthRel(raw)
        except ValueError:
            return TruthRel.UNKNOWN_TO_AUTHORITY
