from __future__ import annotations

from app.api.schemas import SessionView
from app.core.domain.models import GameSession
from app.core.services.situation_projection import project_situation_rows
from app.core.services.visibility import VisibilityService


def _registry():
    try:
        from app.container import get_container

        return get_container().registry
    except Exception:
        return None


def _settlement_text_from_events(session: GameSession) -> str:
    for ev in reversed(session.events or []):
        if "settlement" in (ev.tags or []):
            return (ev.card_body or ev.summary or ev.title or "").strip()
    ids = (session.graph_meta or {}).get("settlement_event_ids") or []
    if not ids:
        return ""
    idset = set(ids)
    for ev in reversed(session.events or []):
        if ev.event_id in idset:
            return (ev.card_body or ev.summary or ev.title or "").strip()
    return ""


def to_session_view(session: GameSession) -> SessionView:
    """客户端 DTO：真相字典 → 投影（Web/3D 共用）。"""
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

    phase_s = session.phase.value if hasattr(session.phase, "value") else str(session.phase)
    ended = phase_s in ("GAME_OVER", "MONTH_END") or bool(session.game_over_reason)
    ev_src = session.events if ended else session.events[-80:]
    events = [vis.mask_event(session, ev) for ev in ev_src]
    events = list(reversed(events))

    extra = pack.project_session_extra(session) if pack is not None else {}
    # 见闻：pack 投影；无 pack 时仅透出字典字段（不做内容分类）
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
    clue_flags = list(extra.get("clue_flags") or [])
    from app.core.services.encounter import (
        project_encounter_offer,
        project_encounter_view,
    )

    encounter = extra.get("encounter")
    if encounter is None and pack is not None:
        encounter = project_encounter_view(session, pack)
    encounter_offer = project_encounter_offer(session)

    path_labels: dict = {}
    if pack is not None:
        fn = getattr(pack, "effect_path_labels", None)
        if callable(fn):
            path_labels = dict(fn() or {})
    situation_rows = project_situation_rows(session, path_labels=path_labels)

    player_card = vis.actor_public_card(session, pid)
    flags = dict(player_card.get("flags") or {})
    # memory_digest 不对客户端暴露

    player_view = {
        **player_card,
        "ap": session.ap,
        "cultivation": p_st.cultivation,
        "resources": p_st.resources,
        "inventory": p_st.inventory,
        "flags": flags,
        "identity": p_st.identity,
        "beliefs": beliefs,
        "situation_rows": situation_rows,
    }

    logs_self = [e for e in events if e.get("track") == "self"]
    logs_world = [e for e in events if e.get("track") == "world"]

    from app.core.services import chat_log

    # 隐情/劫数唯一轨 = clue_flags；world_flags_public 不再塞 countdown 文案副本
    wfp = {
        k: v
        for k, v in (vis.world_flags_view(session) or {}).items()
        if k != "xuanyin_countdown"
    }

    return SessionView(
        session_id=session.session_id,
        world_id=session.world_id,
        phase=phase_s,
        day=session.day,
        ap=session.ap,
        max_days=session.rules.max_days,
        daily_ap=session.rules.daily_ap,
        player=player_view,
        locations=locations,
        actors_here=actors_here,
        all_actors=all_actors,
        recent_events=events,
        world_flags_public=wfp,
        clue_flags=clue_flags,
        game_over_reason=session.game_over_reason,
        settlement_text=_settlement_text_from_events(session),
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
        chat_by_actor=chat_log.export_store(session),
        encounter=encounter if isinstance(encounter, dict) else None,
        encounter_offer=encounter_offer if isinstance(encounter_offer, dict) else None,
    )
