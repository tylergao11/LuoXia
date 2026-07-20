from __future__ import annotations

from typing import Any

from app.core.domain.models import Belief, GameSession, WorldEvent


class VisibilityService:
    """
    可见性 / 置灰：引擎规则，不绑具体剧情。

    上帝模式布局：结构可列全；内容按「玩家应知情」点亮，否则 greyed。
    知情来源：自身权威状态 · known_to · 玩家信念命题/关键词 · 同地公开身份
    """

    SENSITIVE_FLAG_KEYS = frozenset(
        {
            "allegiance",
            "knows_treasure_lost",
            "wants_help_but_distrusts",
            "blood_curse_host",
            "is_traitor",
            "secret",
        }
    )

    SENSITIVE_WORLD_FLAGS = frozenset(
        {
            "blood_curse_planted",
            "fake_secret_realm_letter",
            "secret_realm_is_trigger",
            "blood_curse_host_unknown",
            "letter_exposed",
            "blood_curse_disarmed",
            "sect_at_brink",
            "crisis_fired",
        }
    )

    def player_beliefs(self, session: GameSession) -> list[Belief]:
        return list(session.beliefs.get(session.player_id(), []))

    def player_knows_actor_secret(self, session: GameSession, actor_id: str) -> bool:
        """粗匹配：信念命题是否提到该角色 display_name 或 id 的敏感信息。"""
        prof = session.profiles.get(actor_id)
        names = {actor_id}
        if prof:
            names.add(prof.display_name)
            if prof.title:
                names.add(prof.title)
        text = " ".join(b.proposition for b in self.player_beliefs(session))
        # 若信念明确写到内鬼/效忠等且含人名
        sensitive_words = ("内鬼", "玄阴", "效忠", "收买", "至宝遗失", "血阴")
        if not any(w in text for w in sensitive_words):
            return False
        return any(n in text for n in names if n)

    def event_visible_to_player(self, session: GameSession, ev: WorldEvent) -> bool:
        pid = session.player_id()
        if ev.involves_player or pid in ev.known_to:
            return True
        # 信念覆盖：命题含事件标题关键词
        props = " ".join(b.proposition for b in self.player_beliefs(session))
        if ev.title and ev.title in props:
            return True
        return False

    def mask_event(self, session: GameSession, ev: WorldEvent) -> dict[str, Any]:
        visible = self.event_visible_to_player(session, ev)
        return {
            "event_id": ev.event_id,
            "title": ev.title if visible else "未明之事",
            "summary": ev.summary if visible else "（你尚未得知详情）",
            "kind": ev.kind.value if hasattr(ev.kind, "value") else str(ev.kind),
            "severity": ev.severity.value if hasattr(ev.severity, "value") else str(ev.severity),
            "day": ev.day,
            "involves_player": ev.involves_player,
            "track": "self" if ev.involves_player else "world",
            "known": visible,
            "greyed": not visible,
            "card_headline": ev.card_headline if visible else "？？",
            "card_body": ev.card_body if visible else "",
            "location": ev.location,
            "actor_ids": ev.actor_ids if visible else [],
            "tags": ev.tags if visible else [],
        }

    def actor_public_card(self, session: GameSession, actor_id: str) -> dict[str, Any]:
        prof = session.profiles[actor_id]
        st = session.states[actor_id]
        pid = session.player_id()
        is_self = actor_id == pid
        same_loc = st.location == session.states[pid].location

        # 公开：名、衔、是否存活、是否同地；位置在同地或自己时亮，否则灰
        loc_known = is_self or same_loc or self._belief_mentions_location(
            session, actor_id, st.location
        )
        flags_public: dict[str, Any] = {}
        flags_greyed: dict[str, Any] = {}
        for k, v in (st.flags or {}).items():
            if str(k).startswith("_"):
                continue
            if is_self:
                flags_public[k] = v
            elif k in self.SENSITIVE_FLAG_KEYS:
                if self.player_knows_actor_secret(session, actor_id):
                    flags_public[k] = v
                else:
                    flags_greyed[k] = "？？？"
            else:
                # 非敏感 flags：同地可见，否则灰
                if same_loc:
                    flags_public[k] = v
                else:
                    flags_greyed[k] = "？？？"

        return {
            "id": actor_id,
            "name": prof.display_name,
            "title": prof.title,
            "summary": prof.summary,
            "location": st.location if loc_known else None,
            "location_label": self._loc_name(session, st.location) if loc_known else "行踪未明",
            "location_greyed": not loc_known,
            "alive": st.alive,
            "is_player": prof.is_player,
            "art_key": actor_id,
            "drive_priority": prof.drive_priority,
            "can_proclaim": prof.can_proclaim,
            "same_location": same_loc,
            "flags": flags_public,
            "flags_greyed": flags_greyed,
            "cultivation": st.cultivation if is_self or same_loc else None,
            "cultivation_greyed": not (is_self or same_loc),
            "resources": st.resources if is_self else None,
            "inventory": st.inventory if is_self else None,
            "identity": st.identity if is_self or same_loc else {"title": prof.title},
        }

    def world_flags_view(self, session: GameSession) -> dict[str, Any]:
        """世界旗：倒计时等可公开；阴谋向灰或仅信念点亮。"""
        out: dict[str, Any] = {}
        beliefs_text = " ".join(b.proposition for b in self.player_beliefs(session))
        for k, v in session.world_flags.items():
            if k in ("xuanyin_countdown", "no_living_master"):
                out[k] = {"value": v, "greyed": False, "label": k}
                continue
            if k in self.SENSITIVE_WORLD_FLAGS:
                known = self._sensitive_world_known(k, beliefs_text)
                out[k] = {
                    "value": v if known else None,
                    "greyed": not known,
                    "label": k,
                    "display": v if known else "？？？（未证实）",
                }
            else:
                out[k] = {"value": v, "greyed": False, "label": k}
        return out

    def _sensitive_world_known(self, key: str, beliefs_text: str) -> bool:
        mapping = {
            "blood_curse_planted": ("血阴", "血咒", "护山阵"),
            "fake_secret_realm_letter": ("假信", "密信有假", "并非机缘", "骗局"),
            "secret_realm_is_trigger": ("引爆", "触发", "血阴咒", "开启仪式即是引爆"),
            "blood_curse_host_unknown": ("寄宿", "咒种", "阵眼"),
            "letter_exposed": ("假信", "密信", "伪造", "机缘的来信恐是假"),
            "blood_curse_disarmed": ("镇压", "血阴之患已被", "暂镇"),
            "sect_at_brink": ("大祸", "护山阵剧烈", "大劫"),
            "crisis_fired": ("护山异变", "大劫将至", "异象大作"),
        }
        words = mapping.get(key, ())
        return any(w in beliefs_text for w in words)

    def _belief_mentions_location(
        self, session: GameSession, actor_id: str, location: str | None
    ) -> bool:
        if not location:
            return False
        loc_name = self._loc_name(session, location)
        text = " ".join(b.proposition for b in self.player_beliefs(session))
        prof = session.profiles.get(actor_id)
        name = prof.display_name if prof else actor_id
        return name in text and (location in text or loc_name in text)

    @staticmethod
    def _loc_name(session: GameSession, loc_id: str | None) -> str:
        if not loc_id:
            return "未知"
        node = session.map.nodes.get(loc_id)
        return node.name if node else loc_id
