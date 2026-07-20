from __future__ import annotations

from typing import Any
from uuid import uuid4

from app.core.domain.enums import BeliefSource, EventKind, Severity, TruthRel
from app.core.domain.models import (
    BeliefOp,
    GameSession,
    StateOp,
    WorldEvent,
)


class InvestigationResolver:
    """
    通用探索推进：根据对话关键词 + 地点 + 对象 tags/权职 改 world_flags。
    键名约定（世界包选用即可）：
      letter_exposed / blood_curse_disarmed / blood_curse_host_found
      evidence_level (int)
    """

    def apply_dialogue(
        self,
        session: GameSession,
        *,
        player_id: str,
        npc_id: str,
        utterance: str,
        location: str | None,
    ) -> dict[str, Any]:
        """返回 state_ops / belief_ops / events / narrative_extra / world_flag_patches。"""
        utter = utterance or ""
        state_ops: list[StateOp] = []
        belief_ops: list[BeliefOp] = []
        events: list[WorldEvent] = []
        flag_patches: dict[str, Any] = {}
        notes: list[str] = []

        prof = session.profiles.get(npc_id)
        tags = set(prof.tags or []) if prof else set()
        npc_name = prof.display_name if prof else npc_id
        p_st = session.states.get(player_id)

        # 证据层
        evidence = 0
        if p_st:
            try:
                evidence = int(p_st.flags.get("evidence_level") or 0)
            except (TypeError, ValueError):
                evidence = 0

        # —— 假信线 ——
        if session.world_flags.get("fake_secret_realm_letter") and not session.world_flags.get(
            "letter_exposed"
        ):
            if any(k in utter for k in ("假信", "密信有假", "骗局", "不是机缘", "伪造")):
                if (
                    "law" in tags
                    or "investigator" in tags
                    or location in ("law", "library", "mission", "elder")
                ):
                    flag_patches["letter_exposed"] = True
                    evidence += 2
                    notes.append("假信之疑被坐实一二。")
                    belief_ops.append(
                        self._belief(
                            player_id,
                            f"letter_exposed_d{session.day}",
                            "你愈发确信：秘境机缘的来信恐是假的",
                            TruthRel.MATCHES_AUTHORITY,
                        )
                    )
                    events.append(
                        self._event(
                            session,
                            title="密信疑云",
                            summary="关于秘境来信的真伪，有了更硬的线索。",
                            actors=[player_id, npc_id],
                            loc=location,
                            tags=["investigation", "letter"],
                        )
                    )
                else:
                    evidence += 1
                    notes.append(f"{npc_name}未必能断案，但话已传出。")
                    belief_ops.append(
                        self._belief(
                            npc_id,
                            f"letter_rumor_{npc_id}",
                            "有人说秘境密信可能有假",
                            TruthRel.CONFLICTS_AUTHORITY,
                            source=BeliefSource.RUMOR,
                        )
                    )

        # —— 血阴线 ——
        if session.world_flags.get("blood_curse_planted") and not session.world_flags.get(
            "blood_curse_disarmed"
        ):
            curse_talk = any(k in utter for k in ("血阴", "血咒", "解咒", "阵眼", "寄宿", "护山阵"))
            if curse_talk:
                state_ops.append(
                    StateOp(
                        actor_id=player_id,
                        op="set",
                        path="flags.investigating_curse",
                        value=True,
                    )
                )
                # 藏经/后山/执法 推进更深
                deep = location in ("library", "backhill", "law", "elder") or "reclusive" in tags
                if deep and any(k in utter for k in ("解咒", "破阵", "阵眼", "消解", "镇封")):
                    if evidence >= 2 or deep:
                        flag_patches["blood_curse_disarmed"] = True
                        flag_patches["sect_stabilized"] = True
                        evidence += 3
                        notes.append("你与对方合力，寻得镇压血阴的法门，阵势稍稳。")
                        events.append(
                            self._event(
                                session,
                                title="血阴暂镇",
                                summary="护山隐患被压下一线，大劫或可改写。",
                                actors=[player_id, npc_id],
                                loc=location,
                                severity=Severity.MAJOR,
                                tags=["investigation", "curse_disarm"],
                            )
                        )
                        belief_ops.append(
                            self._belief(
                                player_id,
                                "curse_disarmed",
                                "血阴之患已被暂时镇压",
                                TruthRel.MATCHES_AUTHORITY,
                                conf=0.85,
                            )
                        )
                elif deep:
                    evidence += 1
                    notes.append("典籍或禁地留下了关于邪咒的批注。")
                    if location == "library" or "reclusive" in tags:
                        belief_ops.append(
                            self._belief(
                                player_id,
                                f"curse_note_d{session.day}",
                                "旧录提及：护山阵眼若被邪咒寄宿，开启仪式即是引爆之刻",
                                TruthRel.MATCHES_AUTHORITY,
                                conf=0.7,
                            )
                        )
                        # 点亮 secret_realm_is_trigger 相关认知（信念侧）
                        flag_patches.setdefault("_belief_only", True)

        # —— 内鬼线：向执法/调查者指认 ——
        if any(k in utter for k in ("内鬼", "细作", "卧底", "林溯", "二师兄")):
            # 不写死必须是林溯；若权威有 allegiance 隐藏者且玩家点名其 display_name
            exposed = False
            for aid, st in session.states.items():
                if st.flags.get("allegiance") and st.flags.get("allegiance") not in (
                    "sect",
                    None,
                    "",
                ):
                    name = session.profiles[aid].display_name if aid in session.profiles else aid
                    title = session.profiles[aid].title if aid in session.profiles else ""
                    if name in utter or title in utter or aid in utter:
                        if "law" in tags or "investigator" in tags or location == "law":
                            state_ops.append(
                                StateOp(
                                    actor_id=aid,
                                    op="set",
                                    path="flags.exposed",
                                    value=True,
                                )
                            )
                            evidence += 2
                            exposed = True
                            notes.append(f"{name}的嫌疑被呈到了能办案的人面前。")
                            events.append(
                                self._event(
                                    session,
                                    title="嫌疑坐实一线",
                                    summary=f"关于{name}的不轨之嫌，有了正式记录。",
                                    actors=[player_id, npc_id, aid],
                                    loc=location,
                                    severity=Severity.MAJOR,
                                    tags=["investigation", "expose"],
                                )
                            )
            if not exposed and ("内鬼" in utter or "细作" in utter):
                evidence += 1

        # —— 信任：对守密/难信之人说软话，累计 trust ——
        soft = any(
            k in utter
            for k in ("相信你", "帮你", "不告诉别人", "托付", "我能保守秘密", "你可以信我", "不必一个人")
        )
        npc_flags = session.states.get(npc_id).flags if session.states.get(npc_id) else {}
        hard_to_trust = (
            "reclusive" in tags
            or bool(npc_flags.get("wants_help_but_distrusts"))
            or "不轻信" in (prof.personality if prof else "")
            or "冷淡" in (prof.personality if prof else "")
        )
        if soft and hard_to_trust and p_st is not None:
            # 信任写在 NPC 对玩家的 flags 上
            try:
                trust = int(npc_flags.get("trust_player") or 0)
            except (TypeError, ValueError):
                trust = 0
            trust += 1
            state_ops.append(
                StateOp(actor_id=npc_id, op="set", path="flags.trust_player", value=trust)
            )
            if trust >= 3 and not npc_flags.get("trusts_player"):
                state_ops.append(
                    StateOp(actor_id=npc_id, op="set", path="flags.trusts_player", value=True)
                )
                notes.append(f"{npc_name}似乎终于愿意多信你一分。")
                # 若其掌握遗秘类 flag，托付线索（不写死内容，只开权限标记）
                if npc_flags.get("knows_treasure_lost"):
                    belief_ops.append(
                        self._belief(
                            player_id,
                            f"secret_hint_{npc_id}",
                            f"{npc_name}暗示：宗门至宝之事，与外间传言不同……她知一二。",
                            TruthRel.MATCHES_AUTHORITY,
                            conf=0.7,
                        )
                    )
                    events.append(
                        self._event(
                            session,
                            title="一丝托付",
                            summary=f"{npc_name}对你流露出难得的信任。",
                            actors=[player_id, npc_id],
                            loc=location,
                            severity=Severity.MINOR,
                            tags=["trust", "investigation"],
                        )
                    )
            elif trust < 3:
                notes.append(f"{npc_name}听了你的话，眼神仍有防备，但未拒之门外。")

        if evidence and p_st is not None:
            # 与旧值取 max，避免覆盖更高证据
            try:
                old_e = int(p_st.flags.get("evidence_level") or 0)
            except (TypeError, ValueError):
                old_e = 0
            state_ops.append(
                StateOp(
                    actor_id=player_id,
                    op="set",
                    path="flags.evidence_level",
                    value=max(old_e, evidence),
                )
            )

        return {
            "state_ops": state_ops,
            "belief_ops": belief_ops,
            "events": events,
            "flag_patches": {k: v for k, v in flag_patches.items() if not str(k).startswith("_")},
            "notes": notes,
        }

    def _belief(
        self,
        holder: str,
        bid: str,
        prop: str,
        truth: TruthRel,
        source: BeliefSource = BeliefSource.INFERENCE,
        conf: float = 0.75,
    ) -> BeliefOp:
        return BeliefOp(
            holder_id=holder,
            op="upsert",
            belief_id=bid,
            proposition=prop,
            source=source,
            truth_rel=truth,
            confidence=conf,
        )

    def _event(
        self,
        session: GameSession,
        *,
        title: str,
        summary: str,
        actors: list[str],
        loc: str | None,
        severity: Severity = Severity.MINOR,
        tags: list[str] | None = None,
    ) -> WorldEvent:
        pid = session.player_id()
        return WorldEvent(
            kind=EventKind.WORLD,
            severity=severity,
            title=title,
            summary=summary,
            actor_ids=actors,
            location=loc,
            day=session.day,
            known_to=list({pid, *[a for a in actors if a]}),
            card_headline=title,
            card_body=summary,
            involves_player=pid in actors,
            tags=tags or ["investigation"],
            event_id=f"inv_{uuid4().hex[:10]}",
        )
