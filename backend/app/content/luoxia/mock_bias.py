"""落霞 Mock 心智偏置——内容包，不进 infra。"""

from __future__ import annotations

from app.core.domain.models import GameSession, NpcReply

LIN_SU_ID = "er_shi_xiong"


def mock_reply_override(
    session: GameSession,
    *,
    speaker_id: str,
    player_utterance: str = "",
) -> NpcReply | None:
    _ = player_utterance
    st = session.states.get(speaker_id)
    flags = st.flags if st else {}
    if speaker_id != LIN_SU_ID or not flags.get("knows_curse_will_detonate"):
        return None
    stance = str(flags.get("shake_stance") or "self_protect")
    if stance == "frantic":
        return NpcReply(
            speaker_id=speaker_id,
            utterance="你、你胡说什么？护山之事岂能妄言——换个话题！",
            tone="nervous",
            engagement="annoyed",
            private_thought="若真会炸宗……我岂不成了替死鬼？",
            intent_tags=["shake_frantic", "deflect"],
        )
    if stance == "consider_flip":
        return NpcReply(
            speaker_id=speaker_id,
            utterance="……你若真有办法保住性命与宗门，不妨私下再谈。此处不宜多言。",
            tone="careful",
            engagement="tolerant",
            private_thought="或许该另寻退路——但不能露馅。",
            intent_tags=["shake_flip", "probe"],
        )
    return NpcReply(
        speaker_id=speaker_id,
        utterance="哈哈……护山异动？坊间闲话罢了。你我还是谈些实在的。",
        tone="forced_ease",
        engagement="tolerant",
        private_thought="不能慌。先稳住，再想自保。",
        intent_tags=["shake_protect", "deflect"],
    )


def bias_intend_goal(session: GameSession, npc_id: str, goal: str) -> str:
    st = session.states.get(npc_id)
    if npc_id != LIN_SU_ID or not st or not (st.flags or {}).get("knows_curse_will_detonate"):
        return goal
    stance = str((st.flags or {}).get("shake_stance") or "self_protect")
    bias = {
        "self_protect": "暗中自保，对外仍圆融，少提仪式",
        "consider_flip": "权衡退路，试探可倚之人，不露内情",
        "frantic": "慌乱撇清，回避护山与密信话题",
    }.get(stance, "暗中自保")
    g = (goal or "").strip()
    return f"{bias}" + (f"；{g}" if g else "")
