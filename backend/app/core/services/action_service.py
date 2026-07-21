from __future__ import annotations

from app.core.domain.enums import ActionType, GamePhase
from app.core.domain.models import ActionRequest, ActionResult, GameSession, WorldEvent
from app.core.graphs.checkpointer import get_sqlite_checkpointer, talk_thread_id

from app.core.graphs.player_action import build_player_action_graph, run_player_talk
from app.core.graphs.world_evolve import WorldEvolveStepper
from app.core.ports.adjudicator import AdjudicatorPort
from app.core.ports.agent_mind import AgentMindPort
from app.core.ports.repository import SessionRepositoryPort
from app.core.services.state_applier import StateApplier
from app.core.services.world_registry import WorldRegistry


class ActionService:
    """
    - MOVE：规则
    - TALK：LangGraph（状态仅 session_id）
    - END_DAY：步进推演（每请求一人或收日），session.evolve_* 落盘
    """

    def __init__(
        self,
        repo: SessionRepositoryPort,
        adjudicator: AdjudicatorPort,
        mind: AgentMindPort,
        registry: WorldRegistry,
        applier: StateApplier | None = None,
        *,
        use_checkpointer: bool = True,
    ) -> None:
        self.repo = repo
        self.adjudicator = adjudicator
        self.mind = mind
        self.registry = registry
        self.applier = applier or StateApplier()
        cp = None
        if use_checkpointer:
            try:
                cp = get_sqlite_checkpointer()
            except Exception:
                cp = None
        self._checkpointer = cp
        self._talk_graph = build_player_action_graph(
            mind,
            adjudicator,
            repo,
            self.applier,
            checkpointer=cp,
            registry=registry,
        )
        self._evolve = WorldEvolveStepper(
            mind,
            adjudicator,
            repo,
            get_pack=registry.get,
            applier=self.applier,
        )

    def handle(self, session_id: str, req: ActionRequest) -> ActionResult:
        session = self.repo.get(session_id)
        if session is None:
            return ActionResult(ok=False, message="会话不存在", error_code="NO_SESSION")

        if session.phase == GamePhase.GAME_OVER:
            return ActionResult(
                ok=False, message="本局已结束", session=session, error_code="GAME_OVER"
            )

        at = req.type.value if isinstance(req.type, ActionType) else str(req.type)

        if session.phase == GamePhase.WORLD_EVOLVE and at in (
            ActionType.END_DAY.value,
            "resume_evolve",
        ):
            result = self._end_day(session, resume=True)
            if result.session:
                self._maybe_settle(result.session)
                self.repo.save(result.session)
            return result

        if session.phase not in (GamePhase.PLAYER_TURN, GamePhase.MONTH_END):
            return ActionResult(
                ok=False,
                message=f"当前相位不可操作: {session.phase}",
                session=session,
                error_code="BAD_PHASE",
            )

        if at == ActionType.MOVE.value:
            result = self._move(session, req)
        elif at == ActionType.TALK.value:
            result = self._talk(session, req)
        elif at == ActionType.END_DAY.value:
            result = self._end_day(session, resume=False)
        elif at == ActionType.ENCOUNTER.value or at == "encounter":
            result = self._encounter(session, req)
        else:
            result = self._custom_via_tiandao(session, req)

        if result.session:
            self._maybe_settle(result.session)
            self.repo.save(result.session)
        return result

    def _encounter(self, session: GameSession, req: ActionRequest) -> ActionResult:
        from app.core.services.encounter import handle_encounter

        try:
            pack = self.registry.get(session.world_id)
        except Exception:
            return ActionResult(
                ok=False,
                message="世界包不可用",
                session=session,
                error_code="NO_PACK",
            )
        return handle_encounter(session, req, pack, self.applier)

    def _maybe_settle(self, session: GameSession) -> None:
        if session.phase in (GamePhase.GAME_OVER, GamePhase.MONTH_END):
            from app.core.services.settlement import settle_if_needed

            settle_if_needed(
                session,
                self.adjudicator,
                self.applier,
                reason=session.game_over_reason,
            )

    def _move(self, session: GameSession, req: ActionRequest) -> ActionResult:
        pid = session.player_id()
        st = session.states.get(pid)
        if not st or not st.alive:
            return ActionResult(ok=False, message="无法移动", session=session, error_code="DEAD")
        dest = req.location_id
        if not dest or dest not in session.map.nodes:
            return ActionResult(
                ok=False, message="未知地点", session=session, error_code="BAD_LOC"
            )
        # 地图锁：委托 WorldPack（可拔插）
        try:
            pack = self.registry.get(session.world_id)
            pack.refresh_access_state(session)
            if not pack.location_open(session, dest):
                return ActionResult(
                    ok=False,
                    message=pack.location_lock_reason(session, dest) or "此处暂不可入",
                    session=session,
                    error_code="LOCKED",
                )
        except Exception:
            pass
        cur = st.location
        if cur and not session.map.can_move(cur, dest):
            return ActionResult(
                ok=False, message="无法直达该地", session=session, error_code="NO_EDGE"
            )
        cost = session.rules.move_ap_cost
        if session.ap < cost:
            return ActionResult(
                ok=False, message="行动点不足", session=session, error_code="NO_AP"
            )

        from_loc = cur
        st.location = dest
        st.updated_day = session.day
        session.ap -= cost
        # 条件线索：首次抵达等固定包
        try:
            pack = self.registry.get(session.world_id)
            from app.core.services.content_packet import apply_packet

            apply_packet(
                session,
                pack.on_move(
                    session,
                    player_id=pid,
                    from_location=from_loc,
                    to_location=dest,
                )
                or {},
                applier=self.applier,
            )
        except Exception:
            pass
        self.repo.save(session)
        msg = f"前往{session.map.nodes[dest].name}"
        if session.ap <= 0:
            return self._end_day(session, lead_message=msg)
        return ActionResult(ok=True, message=msg, session=session)

    def _talk(self, session: GameSession, req: ActionRequest) -> ActionResult:
        pid = session.player_id()
        target = req.target_id
        text = (req.utterance or "").strip()
        if not target or not text:
            return ActionResult(
                ok=False, message="需要对象与内容", session=session, error_code="BAD_REQ"
            )
        if target not in session.profiles or session.profiles[target].is_player:
            return ActionResult(
                ok=False, message="无效对象", session=session, error_code="BAD_TARGET"
            )

        p_st = session.states[pid]
        t_st = session.states.get(target)
        if not p_st.alive or not t_st or not t_st.alive:
            return ActionResult(ok=False, message="无法对话", session=session, error_code="DEAD")
        if p_st.location != t_st.location:
            return ActionResult(
                ok=False, message="不在同一地点", session=session, error_code="NOT_COLOCATED"
            )

        self.repo.save(session)
        # 通告内容可选经 payload 传入（真实意图，非 Mock）
        if isinstance(req.payload, dict):
            proc = req.payload.get("proclamation_content")
            if proc is not None:
                session.graph_meta["_talk_proclamation_content"] = str(proc)
            else:
                session.graph_meta.pop("_talk_proclamation_content", None)
        self.repo.save(session)
        cfg = None
        if self._checkpointer is not None:
            tid = talk_thread_id(session.session_id)
            cfg = {"configurable": {"thread_id": tid}}
            session.graph_meta["last_talk_thread"] = tid
            self.repo.save(session)

        try:
            out = run_player_talk(
                self._talk_graph,
                session_id=session.session_id,
                player_id=pid,
                target_id=target,
                utterance=text,
                config=cfg,
            )
        except Exception as e:  # noqa: BLE001 — LLM/图失败直接返回，不静默 mock
            session = self.repo.get(session.session_id) or session
            if session.phase == GamePhase.ADJUDICATING:
                session.phase = GamePhase.PLAYER_TURN
                self.repo.save(session)
            return ActionResult(
                ok=False,
                message=f"天道未通：{e}",
                session=session,
                error_code="LLM_FAIL",
            )
        if out.get("error") == "NO_SESSION":
            return ActionResult(ok=False, message="会话丢失", error_code="NO_SESSION")

        session = self.repo.get(session.session_id)
        assert session is not None
        narrative = out.get("narrative") or "对话已裁决"
        npc_line = out.get("npc_utterance") or None
        effects = dict(session.graph_meta.pop("last_effects", None) or {})
        raw_new = session.graph_meta.pop("last_new_events", None) or []
        new_events: list[WorldEvent] = []
        for x in raw_new:
            try:
                new_events.append(WorldEvent.model_validate(x) if isinstance(x, dict) else x)
            except Exception:
                continue
        self.repo.save(session)

        if session.phase == GamePhase.GAME_OVER:
            return ActionResult(
                ok=True,
                message=narrative,
                session=session,
                npc_utterance=npc_line,
                effects=effects,
                new_events=new_events,
            )

        if session.ap <= 0:
            r = self._end_day(
                session,
                lead_message=narrative,
                npc_utterance=npc_line,
            )
            if effects and not r.effects:
                r.effects = effects
            if new_events and not r.new_events:
                r.new_events = new_events
            return r

        return ActionResult(
            ok=True,
            message=narrative,
            session=session,
            npc_utterance=npc_line,
            effects=effects,
            new_events=new_events,
        )

    def _end_day(
        self,
        session: GameSession,
        *,
        lead_message: str = "",
        npc_utterance: str | None = None,
        resume: bool = False,
    ) -> ActionResult:
        """
        步进入夜：
        - resume=False：建队 + 处理第一人（队空则直接收日）
        - resume=True：再处理一人，或队列已尽则收日
        """
        if session.phase == GamePhase.GAME_OVER:
            return ActionResult(
                ok=True,
                message=lead_message or "尘缘已尽",
                session=session,
                npc_utterance=npc_utterance,
            )

        self.repo.save(session)

        if resume:
            # 中断恢复：确保相位
            if session.phase != GamePhase.WORLD_EVOLVE:
                session.phase = GamePhase.WORLD_EVOLVE
                self.repo.save(session)
            out = self._evolve.tick(session.session_id)
        else:
            out = self._evolve.start(session.session_id)

        session = self.repo.get(session.session_id)
        assert session is not None
        msg_core = out.get("message") or ""

        if session.phase == GamePhase.MONTH_END:
            msg = (lead_message + " · " if lead_message else "") + (msg_core or "一月期满")
        elif session.phase == GamePhase.GAME_OVER:
            msg = lead_message or session.game_over_reason or msg_core or "尘缘已尽"
        else:
            msg = (lead_message + " · " if lead_message else "") + (
                msg_core or f"进入第{session.day}日"
            )

        return ActionResult(
            ok=True,
            message=msg,
            session=session,
            npc_utterance=npc_utterance,
        )

    def _custom_via_tiandao(self, session: GameSession, req: ActionRequest) -> ActionResult:
        session.phase = GamePhase.ADJUDICATING
        material = {"type": "custom", "action": req.model_dump(mode="json")}
        actors = [session.player_id()]
        if req.target_id:
            actors.append(req.target_id)
        adj = self.adjudicator.adjudicate(
            session, actor_ids=actors, current_material=material, phase="player_action"
        )
        self.applier.apply(session, adj)
        cost = max(0, int(adj.ap_cost or 0))
        session.ap = max(0, session.ap - min(cost, session.ap))
        self.repo.save(session)
        if session.phase != GamePhase.GAME_OVER:
            if session.ap <= 0:
                return self._end_day(session)
            session.phase = GamePhase.PLAYER_TURN
        return ActionResult(
            ok=True,
            message=adj.narrative_summary or "已处理",
            session=session,
        )
