from __future__ import annotations

from typing import Any

from app.core.domain.models import Belief, GameSession, WorldEvent


class VisibilityService:
    """
    可见性 / 置灰：引擎只做算法。
    敏感旗 / belief 前缀表由 WorldPack.visibility_config() 提供。
    registry 由调用方注入，禁止 get_container。
    """

    def __init__(self, registry: Any | None = None) -> None:
        self.registry = registry

    def _cfg(self, session: GameSession) -> dict[str, Any]:
        if self.registry is None:
            return {}
        try:
            pack = self.registry.get(session.world_id)
            fn = getattr(pack, "visibility_config", None)
            if callable(fn):
                return dict(fn() or {})
        except Exception:
            pass
        return {}

    def player_beliefs(self, session: GameSession) -> list[Belief]:
        return list(session.beliefs.get(session.player_id(), []))

    def player_knows_actor_secret(self, session: GameSession, actor_id: str) -> bool:
        st = session.states.get(session.player_id())
        if st and (st.flags or {}).get(f"knows_secret_{actor_id}"):
            return True
        prefixes = (f"secret_{actor_id}", f"expose_{actor_id}", f"exposed_{actor_id}")
        for b in self.player_beliefs(session):
            bid = b.belief_id or ""
            if any(bid.startswith(p) for p in prefixes):
                return True
        return False

    def event_visible_to_player(self, session: GameSession, ev: WorldEvent) -> bool:
        pid = session.player_id()
        if ev.involves_player or pid in ev.known_to:
            return True
        eid = ev.event_id or ""
        if eid:
            for b in self.player_beliefs(session):
                if (b.belief_id or "").startswith(f"know_event_{eid}"):
                    return True
        return False

    def mask_event(self, session: GameSession, ev: WorldEvent) -> dict[str, Any]:
        visible = self.event_visible_to_player(session, ev)
        raw_body = ev.card_body if visible else ""
        raw_summary = ev.summary if visible else "（你尚未得知详情）"
        # 旧存档可能把整轮局势块误嵌进 card_body；投影时剥掉，事件权威只留叙事
        if visible and raw_body:
            raw_body = str(raw_body).split("——局势——")[0].strip()
        if visible and raw_summary:
            s = str(raw_summary).split("——局势——")[0].strip()
            raw_summary = s or "（无摘要）"
        return {
            "event_id": ev.event_id,
            "title": ev.title if visible else "未明之事",
            "summary": raw_summary,
            "kind": ev.kind.value if hasattr(ev.kind, "value") else str(ev.kind),
            "severity": ev.severity.value if hasattr(ev.severity, "value") else str(ev.severity),
            "day": ev.day,
            "involves_player": ev.involves_player,
            "track": "self" if ev.involves_player else "world",
            "known": visible,
            "greyed": not visible,
            "card_headline": ev.card_headline if visible else "？？",
            "card_body": raw_body,
            "location": ev.location,
            "actor_ids": ev.actor_ids if visible else [],
            "tags": ev.tags if visible else [],
        }

    def actor_public_card(self, session: GameSession, actor_id: str) -> dict[str, Any]:
        cfg = self._cfg(session)
        sensitive_flags = frozenset(cfg.get("sensitive_flag_keys") or ())
        prof = session.profiles[actor_id]
        st = session.states[actor_id]
        pid = session.player_id()
        is_self = actor_id == pid
        same_loc = st.location == session.states[pid].location

        loc_known = is_self or same_loc or self._belief_mentions_location(
            session, actor_id, st.location
        )
        flags_public: dict[str, Any] = {}
        flags_greyed: dict[str, Any] = {}
        for k, v in (st.flags or {}).items():
            # 下划线开头 = 引擎内部标记，不对客户端暴露
            if str(k).startswith("_"):
                continue
            # 兜底：历史存档里可能仍有 talk_count_ 等英文内部键
            sk = str(k)
            if sk.startswith("talk_count_") or sk.startswith("met_") or sk.startswith(
                "visited_"
            ):
                continue
            if is_self:
                flags_public[k] = v
            elif k in sensitive_flags:
                if self.player_knows_actor_secret(session, actor_id):
                    flags_public[k] = v
                else:
                    flags_greyed[k] = "？？？"
            else:
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
        cfg = self._cfg(session)
        public = frozenset(cfg.get("public_world_flags") or ())
        sensitive = frozenset(cfg.get("sensitive_world_flags") or ())
        # 内部键不进客户端
        hide = frozenset(
            {"fired_clues", "map_unlocked", "seal_mountain_noted", "active_encounter"}
        )
        out: dict[str, Any] = {}
        for k, v in session.world_flags.items():
            if k in hide or str(k).startswith("_"):
                continue
            if k in public:
                out[k] = {"value": v, "greyed": False, "label": k}
                continue
            if k in sensitive:
                known = self.sensitive_world_known(k, session)
                out[k] = {
                    "value": v if known else None,
                    "greyed": not known,
                    "label": k,
                    "display": v if known else "？？？（未证实）",
                }
            else:
                out[k] = {"value": v, "greyed": False, "label": k}
        return out

    def sensitive_world_known(self, key: str, session: GameSession) -> bool:
        st = session.states.get(session.player_id())
        if st and (st.flags or {}).get(f"knows_{key}"):
            return True
        cfg = self._cfg(session)
        prefixes_map = cfg.get("world_flag_belief_prefixes") or {}
        prefixes = tuple(prefixes_map.get(key) or (key,))
        for b in self.player_beliefs(session):
            bid = b.belief_id or ""
            if any(bid.startswith(p) for p in prefixes):
                return True
        return False

    def _belief_mentions_location(
        self, session: GameSession, actor_id: str, location: str | None
    ) -> bool:
        if not location:
            return False
        for b in self.player_beliefs(session):
            bid = b.belief_id or ""
            if bid.startswith(f"seen_{actor_id}_at_{location}"):
                return True
            if bid.startswith(f"loc_{actor_id}_{location}"):
                return True
        return False

    @staticmethod
    def _loc_name(session: GameSession, loc_id: str | None) -> str:
        if not loc_id:
            return "未知"
        node = session.map.nodes.get(loc_id)
        return node.name if node else loc_id
