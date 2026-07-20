from __future__ import annotations

from app.core.domain.enums import GamePhase
from app.core.domain.models import GameSession
from app.core.ports.world_pack import WorldPack


class EndingService:
    """
    结局标签：引擎通用标签 + WorldPack 可扩展标签。
    不在此写死「林溯反水」等，由 pack 读权威状态/flags 解释。
    """

    def finalize(
        self,
        session: GameSession,
        pack: WorldPack | None = None,
        *,
        reason: str | None = None,
    ) -> GameSession:
        tags: list[str] = list(session.ending_tags or [])
        tags.extend(self._engine_tags(session))
        if pack is not None and hasattr(pack, "evaluate_ending_tags"):
            extra = pack.evaluate_ending_tags(session)  # type: ignore[attr-defined]
            if extra:
                tags.extend(extra)
        # 去重保序
        seen: set[str] = set()
        ordered: list[str] = []
        for t in tags:
            if t and t not in seen:
                seen.add(t)
                ordered.append(t)
        session.ending_tags = ordered
        if reason and not session.game_over_reason:
            session.game_over_reason = reason
        if session.phase not in (GamePhase.GAME_OVER, GamePhase.MONTH_END):
            session.phase = GamePhase.MONTH_END
        return session

    def _engine_tags(self, session: GameSession) -> list[str]:
        tags: list[str] = []
        pid = session.player_id()
        st = session.states.get(pid)
        if st and not st.alive:
            tags.append("客卿身死")
        if st and (st.flags.get("expelled") or st.identity.get("expelled")):
            tags.append("被逐出宗")
        if session.day > session.rules.max_days or session.phase == GamePhase.MONTH_END:
            tags.append("时限已至")
        if session.ap == 0 and session.day >= session.rules.max_days:
            tags.append("月尽")
        # 存活天数
        tags.append(f"存续至第{min(session.day, session.rules.max_days)}日")
        return tags
