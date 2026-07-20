from __future__ import annotations

from app.api.schemas import SessionView
from app.core.domain.models import GameSession
from app.core.services.visibility import VisibilityService


_vis = VisibilityService()


def to_session_view(session: GameSession) -> SessionView:
    pid = session.player_id()
    p_st = session.states[pid]
    loc = p_st.location

    actors_here = [
        _vis.actor_public_card(session, a) for a in session.actors_at(loc or "")
    ]
    all_actors = [_vis.actor_public_card(session, a) for a in session.profiles]

    locations = []
    for nid, node in session.map.nodes.items():
        locations.append(
            {
                "id": nid,
                "name": node.name,
                "summary": node.summary,
                "art_key": node.art_key,
                "neighbors": session.map.neighbors(nid),
                "is_current": nid == loc,
            }
        )

    events = [
        _vis.mask_event(session, ev) for ev in session.events[-80:]
    ]
    events = list(reversed(events))

    # 信念列表（玩家自己的——全可见）
    beliefs = [
        {
            "belief_id": b.belief_id,
            "proposition": b.proposition,
            "source": b.source.value if hasattr(b.source, "value") else b.source,
            "truth_rel": b.truth_rel.value if hasattr(b.truth_rel, "value") else b.truth_rel,
            "confidence": b.confidence,
            "day": b.day,
        }
        for b in session.beliefs.get(pid, [])
    ]

    player_card = _vis.actor_public_card(session, pid)
    flags = dict(player_card.get("flags") or {})
    # 压缩记忆对玩家自己始终可见
    if p_st.flags.get("memory_digest"):
        flags["memory_digest"] = p_st.flags["memory_digest"]

    player_view = {
        **player_card,
        "ap": session.ap,
        "cultivation": p_st.cultivation,
        "resources": p_st.resources,
        "inventory": p_st.inventory,
        "flags": flags,
        "identity": p_st.identity,
        "beliefs": beliefs,
    }

    logs_self = [e for e in events if e.get("track") == "self"]
    logs_world = [e for e in events if e.get("track") == "world"]

    return SessionView(
        session_id=session.session_id,
        world_id=session.world_id,
        phase=session.phase.value if hasattr(session.phase, "value") else str(session.phase),
        day=session.day,
        ap=session.ap,
        max_days=session.rules.max_days,
        daily_ap=session.rules.daily_ap,
        player=player_view,
        locations=locations,
        actors_here=actors_here,
        all_actors=all_actors,
        recent_events=events,
        world_flags_public=_vis.world_flags_view(session),
        game_over_reason=session.game_over_reason,
        ending_tags=session.ending_tags,
        logs_self=logs_self,
        logs_world=logs_world,
        evolve_queue=list(session.evolve_queue or []),
        evolve_index=int(session.evolve_index or 0),
        evolve_last_actor_id=str(session.graph_meta.get("evolve_last_actor") or ""),
        evolve_last_actor_name=(
            session.profiles[str(session.graph_meta.get("evolve_last_actor"))].display_name
            if session.graph_meta.get("evolve_last_actor")
            and str(session.graph_meta.get("evolve_last_actor")) in session.profiles
            else ""
        ),
    )
