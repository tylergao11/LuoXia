from __future__ import annotations

from typing import Any, TypedDict

from langgraph.graph import END, StateGraph

from app.core.domain.enums import GamePhase
from app.core.ports.adjudicator import AdjudicatorPort
from app.core.ports.agent_mind import AgentMindPort
from app.core.ports.repository import SessionRepositoryPort
from app.core.services.state_applier import StateApplier


class PlayerActionState(TypedDict, total=False):
    """只存可 msgpack 的简单类型；会话经 repo 读写。"""

    session_id: str
    player_id: str
    target_id: str
    utterance: str
    npc_utterance: str
    narrative: str
    ap_cost: int
    error: str


def build_player_action_graph(
    mind: AgentMindPort,
    adjudicator: AdjudicatorPort,
    repo: SessionRepositoryPort,
    applier: StateApplier | None = None,
    checkpointer=None,
):
    """
    LLM：build_context → dialogue_turn（1×LLM）→ persist
    Mock：无 dialogue_turn → npc_reply + tiandao → persist
    """
    applier = applier or StateApplier()

    def build_context(state: PlayerActionState) -> dict[str, Any]:
        sid = state["session_id"]
        session = repo.get(sid)
        if session is None:
            return {"error": "NO_SESSION"}
        session.phase = GamePhase.ADJUDICATING
        repo.save(session)
        return {"error": "", "player_id": session.player_id()}

    def dialogue_turn_node(state: PlayerActionState) -> dict[str, Any]:
        """有 dialogue_turn 则单次完成；Mock 无此方法则走双步。"""
        if state.get("error"):
            return {}
        session = repo.get(state["session_id"])
        assert session is not None

        combined = getattr(mind, "dialogue_turn", None)
        if not callable(combined):
            session.graph_meta["_talk_fast"] = False
            repo.save(session)
            return {}

        reply, adj = combined(
            session,
            speaker_id=state["target_id"],
            player_utterance=state["utterance"],
            listener_id=state["player_id"],
        )
        loc = session.states[state["player_id"]].location
        session.graph_meta["_talk_material"] = {
            "type": "dialogue",
            "location": loc,
            "participants": [state["player_id"], state["target_id"]],
            "player_utterance": state["utterance"],
            "npc_utterance": reply.utterance,
            "npc_engagement": reply.engagement,
            "npc_wants_action": reply.wants_action,
            "fast_path": True,
        }
        session.graph_meta["_talk_adj"] = adj.model_dump(mode="json")
        session.graph_meta["_talk_fast"] = True
        repo.save(session)
        return {
            "npc_utterance": reply.utterance or "",
            "narrative": adj.narrative_summary or "",
            "ap_cost": int(adj.ap_cost or 0),
        }

    def need_slow_path(state: PlayerActionState) -> str:
        if state.get("error"):
            return "persist"
        session = repo.get(state["session_id"])
        if session is None:
            return "persist"
        if session.graph_meta.get("_talk_fast"):
            return "persist"
        return "npc_reply"

    def npc_reply_node(state: PlayerActionState) -> dict[str, Any]:
        if state.get("error"):
            return {}
        session = repo.get(state["session_id"])
        assert session is not None
        reply = mind.reply(
            session,
            speaker_id=state["target_id"],
            player_utterance=state["utterance"],
            listener_id=state["player_id"],
        )
        loc = session.states[state["player_id"]].location
        session.graph_meta["_talk_material"] = {
            "type": "dialogue",
            "location": loc,
            "participants": [state["player_id"], state["target_id"]],
            "player_utterance": state["utterance"],
            "npc_utterance": reply.utterance,
            "npc_engagement": reply.engagement,
            "npc_wants_action": reply.wants_action,
        }
        repo.save(session)
        return {"npc_utterance": reply.utterance or ""}

    def tiandao_node(state: PlayerActionState) -> dict[str, Any]:
        if state.get("error"):
            return {}
        session = repo.get(state["session_id"])
        assert session is not None
        material = session.graph_meta.get("_talk_material") or {
            "type": "dialogue",
            "player_utterance": state["utterance"],
            "npc_utterance": state.get("npc_utterance") or "",
            "participants": [state["player_id"], state["target_id"]],
        }
        adj = adjudicator.adjudicate(
            session,
            actor_ids=[state["player_id"], state["target_id"]],
            current_material=material,
            phase="player_action",
        )
        session.graph_meta["_talk_adj"] = adj.model_dump(mode="json")
        repo.save(session)
        return {
            "narrative": adj.narrative_summary or "",
            "ap_cost": int(adj.ap_cost or 0),
        }

    def persist_node(state: PlayerActionState) -> dict[str, Any]:
        if state.get("error"):
            return {}
        from app.core.domain.models import AdjudicationResult
        from app.core.services.effect_summary import summarize_adjudication

        session = repo.get(state["session_id"])
        assert session is not None
        raw = session.graph_meta.get("_talk_adj") or {}
        adj = AdjudicationResult.model_validate(raw)
        created = applier.apply(session, adj)
        cost = max(0, int(state.get("ap_cost") or adj.ap_cost or 0))
        session.ap = max(0, session.ap - min(cost, session.ap))
        if session.phase != GamePhase.GAME_OVER:
            session.phase = GamePhase.PLAYER_TURN
        # 己身/对方状态变化，供 API 与气泡直接展示
        effects = summarize_adjudication(
            session, adj, focus_other_id=state.get("target_id")
        )
        session.graph_meta["last_effects"] = effects
        # 本轮新生事件（前端封条卡必须用这个，禁止猜 recent[0]）
        session.graph_meta["last_new_events"] = [
            e.model_dump(mode="json") for e in (created or [])
        ]
        session.graph_meta.pop("_talk_material", None)
        session.graph_meta.pop("_talk_adj", None)
        session.graph_meta.pop("_talk_fast", None)
        repo.save(session)
        return {
            "narrative": state.get("narrative") or adj.narrative_summary or "",
            "ap_cost": cost,
        }

    g = StateGraph(PlayerActionState)
    g.add_node("build_context", build_context)
    g.add_node("dialogue_turn", dialogue_turn_node)
    g.add_node("npc_reply", npc_reply_node)
    g.add_node("tiandao", tiandao_node)
    g.add_node("persist", persist_node)
    g.set_entry_point("build_context")
    g.add_edge("build_context", "dialogue_turn")
    g.add_conditional_edges(
        "dialogue_turn",
        need_slow_path,
        {"persist": "persist", "npc_reply": "npc_reply"},
    )
    g.add_edge("npc_reply", "tiandao")
    g.add_edge("tiandao", "persist")
    g.add_edge("persist", END)
    if checkpointer is not None:
        return g.compile(checkpointer=checkpointer)
    return g.compile()


def run_player_talk(
    graph,
    *,
    session_id: str,
    player_id: str,
    target_id: str,
    utterance: str,
    config: dict | None = None,
) -> PlayerActionState:
    init: PlayerActionState = {
        "session_id": session_id,
        "player_id": player_id,
        "target_id": target_id,
        "utterance": utterance,
        "npc_utterance": "",
        "narrative": "",
        "ap_cost": 0,
        "error": "",
    }
    if config:
        return graph.invoke(init, config)  # type: ignore[return-value]
    return graph.invoke(init)  # type: ignore[return-value]
