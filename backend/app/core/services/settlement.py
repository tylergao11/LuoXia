"""终局：请天道根据本局上下文收束；禁止程序员 if-else 结局标签。"""

from __future__ import annotations

from typing import Any

from app.core.domain.enums import GamePhase
from app.core.domain.models import GameSession
from app.core.ports.adjudicator import AdjudicatorPort
from app.core.services.state_applier import StateApplier


def _chronicle(session: GameSession, limit: int = 120) -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []
    for ev in session.events[-limit:]:
        out.append(
            {
                "day": ev.day,
                "title": ev.title,
                "summary": (ev.summary or "")[:200],
                "kind": ev.kind.value if hasattr(ev.kind, "value") else str(ev.kind),
                "tags": list(ev.tags or [])[:8],
                "involves_player": bool(ev.involves_player),
            }
        )
    return out


def _player_snapshot(session: GameSession) -> dict[str, Any]:
    pid = session.player_id()
    st = session.states.get(pid)
    prof = session.profiles.get(pid)
    beliefs = [
        {
            "belief_id": b.belief_id,
            "proposition": (b.proposition or "")[:160],
            "day": b.day,
        }
        for b in (session.beliefs.get(pid) or [])[-40:]
    ]
    return {
        "id": pid,
        "name": prof.display_name if prof else pid,
        "alive": st.alive if st else False,
        "location": st.location if st else None,
        "identity": dict(st.identity or {}) if st else {},
        "cultivation": dict(st.cultivation or {}) if st else {},
        "resources": dict(st.resources or {}) if st else {},
        "flags": {
            k: v
            for k, v in (st.flags or {}).items()
            if not str(k).startswith("_") and k != "memory_digest"
        }
        if st
        else {},
        "beliefs": beliefs,
    }


def settle_if_needed(
    session: GameSession,
    adjudicator: AdjudicatorPort,
    applier: StateApplier | None = None,
    *,
    reason: str | None = None,
) -> GameSession:
    """
    phase 已是 GAME_OVER / MONTH_END 时调用一次天道 settlement。
    幂等：graph_meta.settlement_done。
    """
    if session.phase not in (GamePhase.GAME_OVER, GamePhase.MONTH_END):
        return session
    meta = session.graph_meta
    if meta.get("settlement_done"):
        return session

    why = (reason or session.game_over_reason or "尘缘已尽").strip()
    if not session.game_over_reason:
        session.game_over_reason = why

    material: dict[str, Any] = {
        "type": "settlement",
        "reason": why,
        "day": session.day,
        "max_days": session.rules.max_days,
        "phase": session.phase.value
        if hasattr(session.phase, "value")
        else str(session.phase),
        "player": _player_snapshot(session),
        "world_flags": dict(session.world_flags or {}),
        "event_chronicle": _chronicle(session),
        "alive_actors": [
            {
                "id": aid,
                "name": session.profiles[aid].display_name
                if aid in session.profiles
                else aid,
                "alive": st.alive,
                "location": st.location,
                "flags": {
                    k: v
                    for k, v in (st.flags or {}).items()
                    if not str(k).startswith("_")
                },
            }
            for aid, st in session.states.items()
        ],
    }

    actor_ids = [session.player_id()]
    for aid, st in session.states.items():
        if st.alive and aid not in actor_ids:
            actor_ids.append(aid)
        if len(actor_ids) >= 12:
            break

    adj = adjudicator.adjudicate(
        session,
        actor_ids=actor_ids,
        current_material=material,
        phase="settlement",
    )
    # 终局文案进 events（真相字典）；不用 graph_meta.settlement_summary
    if not adj.events and (adj.narrative_summary or "").strip():
        from app.core.domain.enums import EventKind, Severity
        from app.core.domain.models import WorldEvent

        adj = adj.model_copy(
            update={
                "events": [
                    WorldEvent(
                        kind=EventKind.WORLD,
                        severity=Severity.MAJOR,
                        title="尘缘收束",
                        summary=(adj.narrative_summary or "")[:120],
                        card_headline="尘缘收束",
                        card_body=adj.narrative_summary or "",
                        day=session.day,
                        actor_ids=[session.player_id()],
                        known_to=[session.player_id()],
                        involves_player=True,
                        tags=["settlement"],
                    )
                ]
            }
        )
    for ev in adj.events or []:
        tags = list(ev.tags or [])
        if "settlement" not in tags:
            tags.append("settlement")
            ev.tags = tags

    (applier or StateApplier()).apply(session, adj)

    meta["settlement_done"] = True
    meta.pop("settlement_summary", None)
    if adj.events:
        meta["settlement_event_ids"] = [e.event_id for e in adj.events if e.event_id]

    return session
