from __future__ import annotations

from app.core.domain.models import GameSession, NpcIntent, NpcReply
from app.core.ports.agent_mind import AgentMindPort
from app.core.services.rule_intent import default_play_order, rule_intend, rule_intend_many


class ScriptedAgentMind(AgentMindPort):
    """
    基于人设/硬状态的占位心智——不扫台词、不绑具体世界。
    世界专有偏置走 WorldPack.mock_reply_override。
    """

    def reply(
        self,
        session: GameSession,
        *,
        speaker_id: str,
        player_utterance: str,
        listener_id: str = "player",
    ) -> NpcReply:
        _ = listener_id
        try:
            from app.container import get_container

            pack = get_container().registry.get(session.world_id)
            ov = pack.mock_reply_override(
                session, speaker_id=speaker_id, player_utterance=player_utterance or ""
            )
            if ov is not None:
                return ov
        except Exception:
            pass

        prof = session.profiles[speaker_id]
        p = prof.personality
        tags = set(prof.tags or [])
        utter = player_utterance or ""
        st = session.states.get(speaker_id)
        flags = st.flags if st else {}
        trusts = bool(flags.get("trusts_player"))

        if trusts and flags.get("knows_treasure_lost"):
            return NpcReply(
                speaker_id=speaker_id,
                utterance="……好。我只说一句：至宝并不在宗门以为的地方。其余，你尚不能逼我。",
                tone="soft",
                engagement="willing",
                private_thought="终于有人能托一点点了。",
                intent_tags=["trust_reveal"],
            )

        if "冷淡" in p or "冷" in p or "reclusive" in tags:
            line = "……你找我有事？" if not trusts else "……是你。说吧。"
            eng = "tolerant"
        elif "刻板" in p or "死板" in p or "law" in tags:
            line = "有话直说，按规矩来。"
            eng = "willing"
        elif "热心" in p or "gossip" in tags:
            line = f"哟，{utter[:12]}……你先坐，我跟你说。" if utter else "哟，有事？你先坐。"
            eng = "willing"
        elif "洒脱" in p or "圆融" in p or "social" in tags:
            line = (
                f"哈哈，有意思。你说「{utter[:16]}」——不妨细聊。"
                if utter
                else "哈哈，不妨细聊。"
            )
            eng = "willing"
        elif "偏执" in p or "不轻信" in p or "investigator" in tags:
            line = "……你为什么问这个？先报上你的来历。"
            eng = "annoyed"
        else:
            line = f"关于「{utter[:20]}」，我记下了。" if utter else "嗯，我记下了。"
            eng = "willing"

        return NpcReply(
            speaker_id=speaker_id,
            utterance=line,
            tone=eng,
            engagement=eng,
            private_thought=f"（{prof.drives}）",
            intent_tags=["reply"],
        )

    def intend(self, session: GameSession, *, npc_id: str) -> NpcIntent:
        intent = rule_intend(session, npc_id=npc_id)
        try:
            from app.container import get_container

            pack = get_container().registry.get(session.world_id)
            goal = pack.bias_intend_goal(session, npc_id, intent.goal_summary or "")
            if goal != (intent.goal_summary or ""):
                intent = intent.model_copy(update={"goal_summary": goal})
        except Exception:
            pass
        return intent

    def intend_night_batch(
        self, session: GameSession, npc_ids: list[str]
    ) -> tuple[dict[str, NpcIntent], list[str]]:
        queue = [nid for nid in npc_ids if nid in session.profiles]
        intents = rule_intend_many(session, queue)
        return intents, default_play_order(session, queue)
