from __future__ import annotations

from typing import Any

from app.core.domain.enums import BeliefSource, GamePhase, TruthRel
from app.core.domain.models import (
    AdjudicationResult,
    Belief,
    BeliefOp,
    GameSession,
    StateOp,
    WorldEvent,
)
from app.core.services.proclamation import ProclamationService


class StateApplier:
    """
    将天道 patch 应用到会话：唯一写权威状态的引擎路径之一。
    内容包不得直接改 session.states，应走裁决结果。
    """

    def __init__(self) -> None:
        self._proclamation = ProclamationService()

    def apply(self, session: GameSession, result: AdjudicationResult) -> list[WorldEvent]:
        # 先展开通告 → 再写状态/信念/事件
        result = self._proclamation.expand(session, result)

        # 世界 flags（diff 日志 append-only，供 LLM 动态区）
        for k, v in (result.world_flag_ops or {}).items():
            old = session.world_flags.get(k)
            session.world_flags[k] = v
            if old != v:
                self._append_diff(
                    session,
                    f"D{session.day} world.{k}: {old!r} -> {v!r}",
                )

        newly_dead: list[str] = []
        for op in result.state_ops:
            before_alive = None
            old_val = self._peek_state_value(session, op.actor_id, op.path)
            if op.path == "alive" and op.op == "set" and op.value is False:
                st0 = session.states.get(op.actor_id)
                before_alive = st0.alive if st0 else None
            self._apply_state_op(session, op)
            new_val = self._peek_state_value(session, op.actor_id, op.path)
            if old_val != new_val:
                self._append_diff(
                    session,
                    f"D{session.day} {op.actor_id}.{op.path}: {old_val!r} -> {new_val!r}",
                )
            if before_alive is True:
                newly_dead.append(op.actor_id)

        for aid in newly_dead:
            self._on_actor_death(session, aid)

        for bop in result.belief_ops:
            prop = (bop.proposition or bop.belief_id or "")[:60]
            self._append_diff(
                session,
                f"D{session.day} belief[{bop.holder_id}] {bop.op}: {prop}",
            )
            self._apply_belief_op(session, bop, default_day=session.day)

        new_events: list[WorldEvent] = []
        for ev in result.events:
            if not ev.day:
                ev.day = session.day
            pid = session.player_id()
            if pid in ev.actor_ids or pid in ev.known_to:
                ev.involves_player = True
            # 保证事件卡有标题与正文，避免前端只有一句话
            if not (ev.card_headline or "").strip():
                ev.card_headline = (ev.title or "旧事").strip() or "旧事"
            if not (ev.card_body or "").strip():
                body = (ev.summary or "").strip()
                if result.narrative_summary and result.narrative_summary not in body:
                    body = (body + "\n\n" + result.narrative_summary).strip()
                ev.card_body = body or ev.card_headline
            if not (ev.summary or "").strip():
                ev.summary = (ev.card_body or ev.card_headline)[:120]
            # 把状态变化写进卡面，列表上就能看见
            try:
                from app.core.services.effect_summary import summarize_adjudication

                focus = None
                for aid in ev.actor_ids or []:
                    if aid != session.player_id():
                        focus = aid
                        break
                effects = summarize_adjudication(session, result, focus_other_id=focus)
                fx = effects.get("full_text") or ""
                if fx and fx not in (ev.card_body or ""):
                    ev.card_body = ((ev.card_body or "").rstrip() + "\n\n——局势——\n" + fx).strip()
                # summary 也带一行己身/对方，免得点开
                bits = []
                if effects.get("self_lines"):
                    bits.append("己身：" + "；".join(effects["self_lines"][:2]))
                if effects.get("other_lines") and effects.get("other_name"):
                    bits.append(
                        f"{effects['other_name']}：" + "；".join(effects["other_lines"][:2])
                    )
                if bits:
                    tip = " / ".join(bits)
                    if tip not in (ev.summary or ""):
                        ev.summary = ((ev.summary or "").rstrip("。") + "。" + tip)[:160]
            except Exception:
                pass
            session.events.append(ev)
            new_events.append(ev)

        flags = result.game_flags or {}
        if flags.get("player_dead"):
            st = session.states.get(session.player_id())
            if st:
                st.alive = False
            session.phase = GamePhase.GAME_OVER
            session.game_over_reason = flags.get("reason") or "玩家死亡"

        if flags.get("player_expelled"):
            st = session.states.get(session.player_id())
            if st:
                st.flags["expelled"] = True
                st.identity["expelled"] = True

        return new_events

    def _on_actor_death(self, session: GameSession, actor_id: str) -> None:
        """通用死亡副作用：清可行动标记、信念可选保留。"""
        st = session.states.get(actor_id)
        if not st:
            return
        st.alive = False
        st.flags["dead"] = True
        st.body = {**(st.body or {}), "wounded": False, "corpse": True}
        # 玩家死亡由 game_flags 处理终局
        if actor_id == session.player_id():
            session.phase = GamePhase.GAME_OVER
            if not session.game_over_reason:
                session.game_over_reason = "玩家死亡"

    def _append_diff(self, session: GameSession, line: str) -> None:
        log = session.graph_meta.setdefault("llm_state_diff_log", [])
        if not isinstance(log, list):
            log = []
            session.graph_meta["llm_state_diff_log"] = log
        log.append(line)
        # 只增截断尾部，永不改写旧行（利于「日志 append」语义）
        if len(log) > 80:
            session.graph_meta["llm_state_diff_log"] = log[-80:]

    def _peek_state_value(self, session: GameSession, actor_id: str, path: str) -> Any:
        st = session.states.get(actor_id)
        if not st:
            return None
        return self._get_path(st.model_dump(), path)

    def _apply_state_op(self, session: GameSession, op: StateOp) -> None:
        state = session.states.get(op.actor_id)
        if state is None:
            return
        data = state.model_dump()
        if op.op == "set":
            self._set_path(data, op.path, op.value)
        elif op.op == "add":
            cur = self._get_path(data, op.path)
            if cur is None:
                cur = 0
            if isinstance(cur, (int, float)) and isinstance(op.value, (int, float)):
                self._set_path(data, op.path, cur + op.value)
        elif op.op == "delete_key":
            self._delete_path(data, op.path)
        elif op.op == "remove":
            # inventory 按 item_id 删
            inv = data.get("inventory") or []
            if isinstance(inv, list) and isinstance(op.value, dict):
                item_id = op.value.get("item_id")
                data["inventory"] = [
                    x for x in inv if not (isinstance(x, dict) and x.get("item_id") == item_id)
                ]
        data["updated_day"] = session.day
        # re-validate
        from app.core.domain.models import AuthorityState

        session.states[op.actor_id] = AuthorityState.model_validate(data)

    def _apply_belief_op(
        self, session: GameSession, bop: BeliefOp, *, default_day: int
    ) -> None:
        holder = bop.holder_id
        if holder not in session.beliefs:
            session.beliefs[holder] = []

        if bop.op == "clear_all":
            session.beliefs[holder] = []
            return

        if bop.op == "retract" and bop.belief_id:
            session.beliefs[holder] = [
                b for b in session.beliefs[holder] if b.belief_id != bop.belief_id
            ]
            return

        if bop.op == "upsert":
            if not bop.belief_id or not bop.proposition:
                return
            src = bop.source
            if isinstance(src, str):
                try:
                    src = BeliefSource(src)
                except ValueError:
                    src = BeliefSource.INFERENCE
            tr = bop.truth_rel
            if isinstance(tr, str):
                try:
                    tr = TruthRel(tr)
                except ValueError:
                    tr = TruthRel.UNKNOWN_TO_AUTHORITY
            belief = Belief(
                belief_id=bop.belief_id,
                holder_id=holder,
                proposition=bop.proposition,
                polarity=bop.polarity,
                source=src,  # type: ignore[arg-type]
                source_detail=bop.source_detail,
                truth_rel=tr,  # type: ignore[arg-type]
                confidence=bop.confidence,
                day=bop.day or default_day,
            )
            others = [b for b in session.beliefs[holder] if b.belief_id != belief.belief_id]
            others.append(belief)
            session.beliefs[holder] = others

    @staticmethod
    def _get_path(data: dict[str, Any], path: str) -> Any:
        cur: Any = data
        for part in path.split("."):
            if not isinstance(cur, dict):
                return None
            cur = cur.get(part)
        return cur

    @staticmethod
    def _set_path(data: dict[str, Any], path: str, value: Any) -> None:
        parts = path.split(".")
        cur: Any = data
        for part in parts[:-1]:
            if part not in cur or not isinstance(cur[part], dict):
                cur[part] = {}
            cur = cur[part]
        cur[parts[-1]] = value

    @staticmethod
    def _delete_path(data: dict[str, Any], path: str) -> None:
        parts = path.split(".")
        cur: Any = data
        for part in parts[:-1]:
            if not isinstance(cur, dict) or part not in cur:
                return
            cur = cur[part]
        if isinstance(cur, dict):
            cur.pop(parts[-1], None)
