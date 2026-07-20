from __future__ import annotations

from app.core.domain.models import GameSession, NpcIntent, NpcReply
from app.core.ports.agent_mind import AgentMindPort


class MockAgentMind(AgentMindPort):
    """
    基于人设/标签的占位心智——尽量世界无关。
    具体 id 分支仅作弱默认；优先 tags 与 drives 文本。
    """

    def reply(
        self,
        session: GameSession,
        *,
        speaker_id: str,
        player_utterance: str,
        listener_id: str = "player",
    ) -> NpcReply:
        prof = session.profiles[speaker_id]
        p = prof.personality
        tags = set(prof.tags or [])
        utter = player_utterance

        if any(k in utter for k in ("蠢", "废物", "滚", "白痴")):
            return NpcReply(
                speaker_id=speaker_id,
                utterance="……到此为止。",
                tone="leaving",
                engagement="leaving",
                private_thought="恶语伤人。",
                intent_tags=["leave"],
            )

        st = session.states.get(speaker_id)
        flags = st.flags if st else {}
        trusts = bool(flags.get("trusts_player"))
        try:
            trust_n = int(flags.get("trust_player") or 0)
        except (TypeError, ValueError):
            trust_n = 0

        # 通告请求
        if prof.can_proclaim and any(k in utter for k in ("通告", "昭告", "公示", "发榜")):
            return NpcReply(
                speaker_id=speaker_id,
                utterance="言之有理……此事可由本座发通告。你且说清楚要昭告什么。",
                tone="serious",
                engagement="willing",
                private_thought="权柄在手，不可轻用。",
                intent_tags=["proclamation"],
            )

        # 已信任：可吐露部分，仍不全盘托出
        if trusts and any(k in utter for k in ("秘密", "至宝", "真相", "师父", "帮你", "怎么办")):
            if flags.get("knows_treasure_lost"):
                return NpcReply(
                    speaker_id=speaker_id,
                    utterance="……好。我只说一句：至宝并不在宗门以为的地方。其余，你尚不能逼我。",
                    tone="soft",
                    engagement="willing",
                    private_thought="终于有人能托一点点了。",
                    intent_tags=["trust_reveal"],
                )
            return NpcReply(
                speaker_id=speaker_id,
                utterance="我信你几分。有些事，我们一起查。",
                tone="soft",
                engagement="willing",
                private_thought="防备松了一点。",
                intent_tags=["trust"],
            )

        if trust_n > 0 and trust_n < 3 and any(
            k in utter for k in ("信我", "秘密", "帮你", "不告诉")
        ):
            return NpcReply(
                speaker_id=speaker_id,
                utterance="……我听见了。但我还不能全信你。",
                tone="hesitant",
                engagement="tolerant",
                private_thought=f"信任 {trust_n}/3",
                intent_tags=["trust_building"],
            )

        if "冷淡" in p or "冷" in p or "reclusive" in tags:
            line = "……你找我有事？" if not trusts else "……是你。说吧。"
            eng = "tolerant"
        elif "刻板" in p or "死板" in p or "law" in tags:
            line = "有话直说，按规矩来。"
            eng = "willing"
        elif "热心" in p or "gossip" in tags:
            line = f"哟，{utter[:12]}……你先坐，我跟你说。"
            eng = "willing"
        elif "洒脱" in p or "圆融" in p or "social" in tags:
            line = f"哈哈，有意思。你说「{utter[:16]}」——不妨细聊。"
            eng = "willing"
        elif "偏执" in p or "不轻信" in p or "investigator" in tags:
            line = "……你为什么问这个？先报上你的来历。"
            eng = "annoyed"
        else:
            line = f"关于「{utter[:20]}」，我记下了。"
            eng = "willing"

        # 若对方信念里已有线索，可略作呼应（通用）
        beliefs = session.beliefs.get(speaker_id, [])
        if any("内鬼" in b.proposition or "血阴" in b.proposition for b in beliefs):
            if "内鬼" in utter or "血阴" in utter:
                line = "噤声。这等话……也不是不能谈，换个地方。"
                eng = "tolerant"

        return NpcReply(
            speaker_id=speaker_id,
            utterance=line,
            tone=eng,
            engagement=eng,
            private_thought=f"（{prof.drives}）",
            intent_tags=["reply"],
        )

    def intend(self, session: GameSession, *, npc_id: str) -> NpcIntent:
        prof = session.profiles[npc_id]
        st = session.states.get(npc_id)
        if not st or not st.alive:
            return NpcIntent(npc_id=npc_id, goal_summary="无力行动", action={"type": "idle"})

        tags = set(prof.tags or [])
        if prof.drive_priority < 50 and "functional" in tags and session.day % 2 == 0:
            return NpcIntent(
                npc_id=npc_id, goal_summary="当值/休憩", action={"type": "idle"}
            )

        # 标签驱动意图（世界无关）
        if "investigator" in tags or "查" in prof.drives:
            dest = "law" if "law" in session.map.nodes else st.location
            return NpcIntent(
                npc_id=npc_id,
                goal_summary="暗中查访异常迹象",
                action={"type": "search", "location": dest, "detail": "取证"},
                priority="high",
            )
        if "social" in tags or "人缘" in prof.drives or "探听" in prof.drives:
            dest = "square" if "square" in session.map.nodes else st.location
            return NpcIntent(
                npc_id=npc_id,
                goal_summary="在公共处维系人缘、探听议论",
                action={"type": "talk", "location": dest},
                priority="high",
            )
        if "reclusive" in tags or "独自" in prof.drives or "守密" in prof.drives:
            dest = "library" if "library" in session.map.nodes else (
                "backhill" if "backhill" in session.map.nodes else st.location
            )
            return NpcIntent(
                npc_id=npc_id,
                goal_summary="独自徘徊静处",
                action={"type": "move", "location": dest},
                priority="high",
            )
        if "order" in tags or "规矩" in prof.drives or "正统" in prof.drives:
            dest = "hall" if "hall" in session.map.nodes else st.location
            return NpcIntent(
                npc_id=npc_id,
                goal_summary="巡视礼仪与秩序",
                action={"type": "move", "location": dest},
            )
        if prof.can_proclaim and session.day % 5 == 0:
            return NpcIntent(
                npc_id=npc_id,
                goal_summary="视情发布安定人心的通告",
                action={
                    "type": "proclaim",
                    "detail": "各司其职，勿信无根流言。",
                },
                priority="high",
            )
        if "law" in tags:
            return NpcIntent(
                npc_id=npc_id,
                goal_summary="处理本职案牍",
                action={"type": "idle", "location": st.location},
            )

        # 弱默认：回默认点或 idle
        if prof.default_location and prof.default_location != st.location:
            return NpcIntent(
                npc_id=npc_id,
                goal_summary=f"返回{prof.default_location}",
                action={"type": "move", "location": prof.default_location},
            )
        return NpcIntent(
            npc_id=npc_id,
            goal_summary=f"{prof.display_name}按本职行事",
            action={"type": "idle"},
        )
