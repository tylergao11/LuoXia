from __future__ import annotations

from app.api.schemas import SessionView
from app.core.domain.models import GameSession
from app.core.services.visibility import VisibilityService


def _registry():
    try:
        from app.container import get_container

        return get_container().registry
    except Exception:
        return None


def _pack(session: GameSession):
    reg = _registry()
    if reg is None:
        return None
    try:
        return reg.get(session.world_id)
    except Exception:
        return None


def to_session_view(session: GameSession) -> SessionView:
    """客户端 DTO：引擎通用可见性 + WorldPack.project_session_extra（Web/3D 共用）。"""
    pid = session.player_id()
    p_st = session.states[pid]
    loc = p_st.location
    reg = _registry()
    pack = None
    if reg is not None:
        try:
            pack = reg.get(session.world_id)
        except Exception:
            pack = None
    vis = VisibilityService(registry=reg)

    actors_here = [
        vis.actor_public_card(session, a) for a in session.actors_at(loc or "")
    ]
    all_actors = [vis.actor_public_card(session, a) for a in session.profiles]

    locations = []
    for nid, node in session.map.nodes.items():
        row = {
            "id": nid,
            "name": node.name,
            "summary": node.summary,
            "art_key": node.art_key,
            "neighbors": session.map.neighbors(nid),
            "is_current": nid == loc,
            "tags": list(node.tags or []),
        }
        if pack is not None:
            row.update(pack.location_view_extra(session, nid))
        else:
            row["unlocked"] = True
            row["locked"] = False
            row["lock_reason"] = ""
        locations.append(row)

    events = [vis.mask_event(session, ev) for ev in session.events[-80:]]
    events = list(reversed(events))

    extra = pack.project_session_extra(session) if pack is not None else {}
    beliefs = extra.get("beliefs")
    if beliefs is None:
        beliefs = [
            {
                "belief_id": b.belief_id,
                "proposition": b.proposition,
                "source": b.source.value if hasattr(b.source, "value") else b.source,
                "truth_rel": b.truth_rel.value
                if hasattr(b.truth_rel, "value")
                else b.truth_rel,
                "confidence": b.confidence,
                "day": b.day,
            }
            for b in session.beliefs.get(pid, [])
        ]
    case_lines = list(extra.get("case_lines") or [])
    clue_flags = list(extra.get("clue_flags") or [])

    player_card = vis.actor_public_card(session, pid)
    flags = dict(player_card.get("flags") or {})
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
        world_flags_public=vis.world_flags_view(session),
        case_lines=case_lines,
        clue_flags=clue_flags,
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
