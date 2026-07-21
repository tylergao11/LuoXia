from __future__ import annotations

from collections.abc import Callable
from typing import Any

from app.config import settings
from app.core.domain.enums import EventKind, GamePhase, Severity
from app.core.domain.models import NpcIntent, WorldEvent
from app.core.ports.adjudicator import AdjudicatorPort
from app.core.ports.agent_mind import AgentMindPort
from app.core.ports.repository import SessionRepositoryPort
from app.core.ports.world_pack import WorldPack
from app.core.services.state_applier import StateApplier


def _settlement_message(session) -> str:
    """终局文案投影：读 settlement 事件，不读 graph_meta 影子。"""
    for ev in reversed(session.events or []):
        tags = ev.tags or []
        if "settlement" in tags:
            return (ev.card_body or ev.summary or ev.title or "").strip()
    ids = (session.graph_meta or {}).get("settlement_event_ids") or []
    if ids:
        idset = set(ids)
        for ev in reversed(session.events or []):
            if ev.event_id in idset:
                return (ev.card_body or ev.summary or ev.title or "").strip()
    return ""


class WorldEvolveStepper:
    """
    日终步进：select → process_one* → rollover。
    每步独立落盘；不在一次调用里跑完全图（方案 D）。
    """

    def __init__(
        self,
        mind: AgentMindPort,
        adjudicator: AdjudicatorPort,
        repo: SessionRepositoryPort,
        get_pack: Callable[[str], WorldPack],
        applier: StateApplier | None = None,
        max_npcs: int | None = None,
    ) -> None:
        self.mind = mind
        self.adjudicator = adjudicator
        self.repo = repo
        self.get_pack = get_pack
        self.applier = applier or StateApplier()
        self.max_npcs = int(max_npcs if max_npcs is not None else settings.evolve_max_npcs)

    def start(self, session_id: str) -> dict[str, Any]:
        """建队 → 并行预取意图 → 处理第一人（队空则直接收日）。"""
        out = self.select_npcs(session_id)
        if out.get("error"):
            return out
        session = self.repo.get(session_id)
        if session is None:
            return {"error": "NO_SESSION", "message": "会话不存在", "done": True}
        queue = list(session.evolve_queue or [])
        if not queue:
            return self.rollover(session_id)
        self._prefetch_intents(session_id, queue)
        return self.process_one(session_id)

    def _prefetch_intents(self, session_id: str, queue: list[str]) -> None:
        """
        预取意图并写入 graph_meta['evolve_intents']。
        优先一夜协商批次（含 play_order → 重排 evolve_queue）；否则回退 intend_many / 逐人。
        """
        session = self.repo.get(session_id)
        if session is None or not queue:
            return

        batch = getattr(self.mind, "intend_night_batch", None)
        if callable(batch):
            intents, play_order = batch(session, queue)
            # 同一 session 对象保留 llm_threads；勿重新 get 丢掉批次上下文
            if play_order and set(play_order) == set(queue):
                session.evolve_queue = list(play_order)
            session.graph_meta["evolve_intents"] = {
                nid: (intent.model_dump(mode="json") if hasattr(intent, "model_dump") else intent)
                for nid, intent in intents.items()
            }
            session.graph_meta["evolve_play_order"] = list(session.evolve_queue or [])
            self.repo.save(session)
            return

        intend_many = getattr(self.mind, "intend_many", None)
        if callable(intend_many):
            intents = intend_many(session, queue)
        else:
            intents = {nid: self.mind.intend(session, npc_id=nid) for nid in queue}
        session.graph_meta["evolve_intents"] = {
            nid: (intent.model_dump(mode="json") if hasattr(intent, "model_dump") else intent)
            for nid, intent in intents.items()
        }
        self.repo.save(session)

    def tick(self, session_id: str) -> dict[str, Any]:
        """续跑一步：未完则 process_one；已完则 rollover。"""
        session = self.repo.get(session_id)
        if session is None:
            return {"error": "NO_SESSION", "message": "会话不存在", "done": True}
        if session.phase == GamePhase.GAME_OVER:
            return self.rollover(session_id)
        queue = list(session.evolve_queue or [])
        index = int(session.evolve_index or 0)
        if not queue or index >= len(queue):
            return self.rollover(session_id)
        return self.process_one(session_id)

    def select_npcs(self, session_id: str) -> dict[str, Any]:
        session = self.repo.get(session_id)
        if session is None:
            return {"error": "NO_SESSION", "message": "会话不存在", "done": True}

        session.phase = GamePhase.WORLD_EVOLVE
        pack = self.get_pack(session.world_id)
        hinted = pack.evolve_priority_ids(session.day, session.world_flags)
        bonus = pack.evolve_actor_scores(session) or {}

        if hinted is not None:
            candidates = [
                i
                for i in hinted
                if i in session.profiles
                and not session.profiles[i].is_player
                and session.states.get(i)
                and session.states[i].alive
            ]
            candidates.sort(
                key=lambda aid: -(
                    session.profiles[aid].drive_priority + float(bonus.get(aid, 0))
                )
            )
            queue = candidates[: self.max_npcs]
        else:
            scored: list[tuple[float, str]] = []
            for aid, prof in session.profiles.items():
                if prof.is_player:
                    continue
                st = session.states.get(aid)
                if not st or not st.alive:
                    continue
                total = float(prof.drive_priority) + float(bonus.get(aid, 0))
                if (
                    prof.drive_priority < 50
                    and bonus.get(aid, 0) <= 0
                    and session.day % 2 == 0
                ):
                    continue
                scored.append((total, aid))
            scored.sort(key=lambda x: -x[0])
            queue = [aid for _, aid in scored[: self.max_npcs]]

        session.evolve_queue = list(queue)
        session.evolve_index = 0
        session.graph_meta["evolve_last_actor"] = ""
        session.graph_meta["evolve_intents"] = {}
        self.repo.save(session)
        return {
            "queue": queue,
            "index": 0,
            "error": "",
            "message": f"夜色初合 · 将演 {len(queue)} 人",
            "done": False,
            "last_actor_id": "",
        }

    def _resolve_intent(self, session, npc_id: str) -> NpcIntent:
        cached = (session.graph_meta.get("evolve_intents") or {}).get(npc_id)
        if isinstance(cached, dict):
            try:
                return NpcIntent.model_validate(cached)
            except Exception:
                pass
        return self.mind.intend(session, npc_id=npc_id)

    def _apply_simple_move(self, session, npc_id: str, location: str, goal: str) -> bool:
        """合法移动：同构包 → apply_packet，不直写 events。"""
        from app.core.domain.models import StateOp
        from app.core.services.content_packet import apply_packet

        st = session.states.get(npc_id)
        if not st or not st.alive:
            return False
        if location not in session.map.nodes:
            return False
        cur = st.location
        if cur and not session.map.can_move(cur, location) and cur != location:
            pass
        name = session.profiles[npc_id].display_name if npc_id in session.profiles else npc_id
        loc_name = session.map.nodes[location].name
        packet = {
            "state_ops": [
                StateOp(actor_id=npc_id, op="set", path="location", value=location),
            ],
            "belief_ops": [],
            "world_flag_ops": {},
            "events": [
                WorldEvent(
                    kind=EventKind.OTHER,
                    severity=Severity.TRIVIAL,
                    title=f"{name}移步",
                    summary=goal or f"{name}前往{loc_name}",
                    actor_ids=[npc_id],
                    location=location,
                    day=session.day,
                    known_to=[npc_id],
                    card_headline=f"{name}的夜行",
                    card_body=f"{name}夜至{loc_name}。",
                    tags=["world_evolve", "move", "fast_path"],
                )
            ],
        }
        apply_packet(session, packet, applier=self.applier)
        return True

    def process_one(self, session_id: str) -> dict[str, Any]:
        session = self.repo.get(session_id)
        if session is None:
            return {"error": "NO_SESSION", "message": "会话不存在", "done": True}

        queue = list(session.evolve_queue or [])
        index = int(session.evolve_index or 0)

        if session.phase == GamePhase.GAME_OVER:
            session.evolve_index = index
            self.repo.save(session)
            return {
                "index": index,
                "queue": queue,
                "done": True,
                "message": session.game_over_reason or "尘缘已尽",
                "last_actor_id": "",
            }

        if index >= len(queue):
            return {
                "index": index,
                "queue": queue,
                "done": False,
                "message": "夜事将尽，待收日",
                "last_actor_id": "",
            }

        npc_id = queue[index]
        intent = self._resolve_intent(session, npc_id)
        action = intent.action or {}
        atype = str(action.get("type") or "idle")

        if atype == "idle":
            pass
        elif atype == "move" and action.get("location"):
            ok = self._apply_simple_move(
                session,
                npc_id,
                str(action.get("location")),
                intent.goal_summary or "",
            )
            if not ok:
                # 非法移动回退裁决
                material = {
                    "type": "npc_action",
                    "npc_id": npc_id,
                    "intent": intent.model_dump(mode="json"),
                }
                adj = self.adjudicator.adjudicate(
                    session,
                    actor_ids=[npc_id],
                    current_material=material,
                    phase="world_evolve",
                )
                adj.ap_cost = 0
                self.applier.apply(session, adj)
        else:
            actor_ids = [npc_id]
            tid = action.get("target_id")
            if tid:
                actor_ids.append(str(tid))
            material = {
                "type": "npc_action",
                "npc_id": npc_id,
                "intent": intent.model_dump(mode="json"),
            }
            adj = self.adjudicator.adjudicate(
                session,
                actor_ids=actor_ids,
                current_material=material,
                phase="world_evolve",
            )
            adj.ap_cost = 0
            self.applier.apply(session, adj)

        index += 1
        session.evolve_index = index
        session.evolve_queue = queue
        session.phase = GamePhase.WORLD_EVOLVE
        session.graph_meta["evolve_last_actor"] = npc_id
        self.repo.save(session)

        name = (
            session.profiles[npc_id].display_name
            if npc_id in session.profiles
            else npc_id
        )
        goal = (intent.goal_summary or "").strip()
        if goal:
            msg = f"夜色流转 · {index}/{len(queue)} · {name} · {goal}"
        else:
            msg = f"夜色流转 · {index}/{len(queue)} · {name}"

        return {
            "index": index,
            "queue": queue,
            "done": False,
            "message": msg,
            "last_actor_id": npc_id,
            "error": "",
        }

    def rollover(self, session_id: str) -> dict[str, Any]:
        from app.core.services.memory import MemoryCompressor
        from app.core.services.rumor import RumorPass

        session = self.repo.get(session_id)
        if session is None:
            return {"error": "NO_SESSION", "message": "会话不存在", "done": True}

        pack = self.get_pack(session.world_id)

        if session.phase == GamePhase.GAME_OVER:
            if not session.game_over_reason:
                session.game_over_reason = "尘缘已尽"
            from app.core.services.settlement import settle_if_needed

            settle_if_needed(
                session,
                self.adjudicator,
                self.applier,
                reason=session.game_over_reason,
            )
            session.evolve_queue = []
            session.evolve_index = 0
            session.graph_meta["evolve_last_actor"] = ""
            session.graph_meta.pop("evolve_intents", None)
            self.repo.save(session)
            msg = _settlement_message(session) or session.game_over_reason
            return {
                "message": msg or "尘缘已尽",
                "done": True,
                "last_actor_id": "",
            }

        session.phase = GamePhase.DAY_ROLLOVER
        from app.core.services.content_packet import apply_packet

        apply_packet(session, pack.on_day_end(session) or {})

        RumorPass().run(session)

        session.day += 1
        # 倒计时 / 危机 / 封山：世界包 on_day_rollover 只回包，引擎 apply
        apply_packet(session, pack.on_day_rollover(session) or {})

        MemoryCompressor().compress_session(session)

        session.evolve_queue = []
        session.evolve_index = 0
        session.graph_meta["evolve_last_actor"] = ""
        session.graph_meta.pop("evolve_intents", None)

        if session.day > session.rules.max_days:
            session.phase = GamePhase.MONTH_END
            session.game_over_reason = session.game_over_reason or "一月期满"
            from app.core.services.settlement import settle_if_needed

            settle_if_needed(
                session,
                self.adjudicator,
                self.applier,
                reason=session.game_over_reason,
            )
            self.repo.save(session)
            msg = _settlement_message(session) or "一月期满"
            return {"message": str(msg), "done": True, "last_actor_id": ""}

        prev = session.day - 1
        session.ap = session.rules.daily_ap
        session.phase = GamePhase.PLAYER_TURN
        self.repo.save(session)
        return {
            "message": f"第{prev}日终 · 进入第{session.day}日",
            "done": True,
            "last_actor_id": "",
        }
