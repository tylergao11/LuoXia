from __future__ import annotations

from app.core.domain.models import GameSession


class MemoryCompressor:
    """
    信念条数裁剪：旧见闻折进 flags.memory_digest。

    只 append，禁止砍头/改写已有 digest（否则打断 DeepSeek 前缀缓存，
    也丢掉最早见闻）。长度控制留给 prompt：MEMORY 取前缀冻结，溢出进 DYNAMIC。
    """

    def __init__(self, *, keep_recent: int = 12) -> None:
        self.keep_recent = keep_recent

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
            chunk = " | ".join(digest_lines)
            st.flags["memory_digest"] = (prev + " | " if prev else "") + chunk
            st.updated_day = session.day
        session.beliefs[actor_id] = recent
        return len(old)
