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
        """并行 intend，写入 graph_meta['evolve_intents']。"""
        session = self.repo.get(session_id)
        if session is None or not queue:
            return
        intend_many = getattr(self.mind, "intend_many", None)
        if callable(intend_many):
            intents = intend_many(session, queue)
        else:
            intents = {nid: self.mind.intend(session, npc_id=nid) for nid in queue}
        session = self.repo.get(session_id)
        if session is None:
            return
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
        """合法移动不走 LLM 裁决。"""
        st = session.states.get(npc_id)
        if not st or not st.alive:
            return False
        if location not in session.map.nodes:
            return False
        cur = st.location
        if cur and not session.map.can_move(cur, location) and cur != location:
            # 无边时仍允许同图瞬移式夜行（避免卡死），若严格可 return False
            pass
        st.location = location
        st.updated_day = session.day
        name = session.profiles[npc_id].display_name if npc_id in session.profiles else npc_id
        loc_name = session.map.nodes[location].name
        session.events.append(
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
        )
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
        from app.core.services.crisis import CrisisTick
        from app.core.services.ending import EndingService
        from app.core.services.memory import MemoryCompressor
        from app.core.services.rumor import RumorPass

        session = self.repo.get(session_id)
        if session is None:
            return {"error": "NO_SESSION", "message": "会话不存在", "done": True}

        pack = self.get_pack(session.world_id)

        if session.phase == GamePhase.GAME_OVER:
            EndingService().finalize(session, pack, reason=session.game_over_reason)
            session.evolve_queue = []
            session.evolve_index = 0
            session.graph_meta["evolve_last_actor"] = ""
            session.graph_meta.pop("evolve_intents", None)
            self.repo.save(session)
            return {
                "message": session.game_over_reason or "尘缘已尽",
                "done": True,
                "last_actor_id": "",
            }

        session.phase = GamePhase.DAY_ROLLOVER
        if hasattr(pack, "on_day_end"):
            pack.on_day_end(session)

        RumorPass().run(session)

        session.day += 1
        if "xuanyin_countdown" in session.world_flags:
            try:
                session.world_flags["xuanyin_countdown"] = max(
                    0, int(session.world_flags["xuanyin_countdown"]) - 1
                )
            except (TypeError, ValueError):
                pass

        CrisisTick().run(session)
        MemoryCompressor().compress_session(session)

        session.evolve_queue = []
        session.evolve_index = 0
        session.graph_meta["evolve_last_actor"] = ""
        session.graph_meta.pop("evolve_intents", None)

        if session.day > session.rules.max_days:
            session.phase = GamePhase.MONTH_END
            EndingService().finalize(session, pack, reason="一月期满")
            self.repo.save(session)
            return {"message": "一月期满", "done": True, "last_actor_id": ""}

        prev = session.day - 1
        session.ap = session.rules.daily_ap
        session.phase = GamePhase.PLAYER_TURN
        self.repo.save(session)
        return {
            "message": f"第{prev}日终 · 进入第{session.day}日",
            "done": True,
            "last_actor_id": "",
        }
