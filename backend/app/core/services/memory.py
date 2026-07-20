from __future__ import annotations

from app.core.domain.models import Belief, GameSession


class MemoryCompressor:
    """
    Hermes 式压缩占位：按角色裁剪信念条数，旧见闻折成 flags.memory_digest。
    不绑具体剧情；只做结构压缩。
    """

    def __init__(self, *, keep_recent: int = 12, digest_max_chars: int = 280) -> None:
        self.keep_recent = keep_recent
        self.digest_max_chars = digest_max_chars

    def compress_session(self, session: GameSession) -> int:
        """返回被折叠的信念条数。"""
        folded = 0
        for aid in list(session.beliefs.keys()):
            folded += self.compress_actor(session, aid)
        return folded

    def compress_actor(self, session: GameSession, actor_id: str) -> int:
        beliefs = list(session.beliefs.get(actor_id) or [])
        if len(beliefs) <= self.keep_recent:
            return 0
        # 按 day 排序，旧的进 digest
        beliefs.sort(key=lambda b: (b.day, b.belief_id))
        old, recent = beliefs[: -self.keep_recent], beliefs[-self.keep_recent :]
        digest_lines = [f"D{b.day}:{b.proposition}" for b in old]
        st = session.states.get(actor_id)
        if st is not None:
            prev = str(st.flags.get("memory_digest") or "")
            merged = (prev + " | " if prev else "") + " | ".join(digest_lines)
            if len(merged) > self.digest_max_chars:
                merged = "…" + merged[-self.digest_max_chars :]
            st.flags["memory_digest"] = merged
            st.updated_day = session.day
        session.beliefs[actor_id] = recent
        return len(old)
