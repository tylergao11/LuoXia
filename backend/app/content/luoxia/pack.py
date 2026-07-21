from __future__ import annotations

from typing import Any

from app.content.luoxia import data as D  # noqa: I001
from app.core.domain.enums import BeliefSource, EventKind, Severity, TruthRel
from app.core.domain.models import (
    ActorProfile,
    AuthorityState,
    Belief,
    LocationNode,
    MapGraph,
    WorldEvent,
    WorldRules,
)
from app.core.ports.world_pack import WorldPack


class LuoxiaWorldPack(WorldPack):
    """落霞宗世界包——仅内容与种子，不含引擎逻辑。"""

    @property
    def world_id(self) -> str:
        return "luoxia"

    @property
    def display_name(self) -> str:
        return "落霞宗"

    def background_text(self) -> str:
        return D.BACKGROUND

    def rules(self) -> WorldRules:
        return WorldRules(
            max_days=21,
            daily_ap=6,
            move_ap_cost=1,
            player_actor_id="player",
            high_drive_min_priority=50,
        )

    def build_map(self) -> MapGraph:
        nodes = {
            n["id"]: LocationNode(
                id=n["id"],
                name=n["name"],
                summary=n["summary"],
                art_key=n.get("art_key", n["id"]),
                tags=n.get("tags", []),
            )
            for n in D.LOCATIONS
        }
        edges: dict[str, list[str]] = {k: list(v) for k, v in D.EDGES.items()}
        # 补双向
        for a, tos in list(edges.items()):
            for b in tos:
                edges.setdefault(b, [])
                if a not in edges[b]:
                    edges[b].append(a)
        return MapGraph(nodes=nodes, edges=edges)

    def build_profiles(self) -> dict[str, ActorProfile]:
        out: dict[str, ActorProfile] = {}
        for raw in D.ACTORS:
            p = ActorProfile.model_validate(raw)
            out[p.id] = p
        return out

    def build_initial_states(
        self, profiles: dict[str, ActorProfile]
    ) -> dict[str, AuthorityState]:
        states: dict[str, AuthorityState] = {}
        for pid, prof in profiles.items():
            seed = D.STATE_SEEDS.get(pid, {})
            cult = seed.get("cultivation")
            if not cult and prof.extra.get("realm"):
                cult = {"realm": str(prof.extra["realm"]).replace("后期", "").replace("中期", "").replace("初期", "").strip() or "炼气", "layer": 1}
            states[pid] = AuthorityState(
                actor_id=pid,
                alive=seed.get("alive", True),
                location=seed.get("location", prof.default_location),
                identity=seed.get("identity", {"title": prof.title}),
                cultivation=cult or {},
                resources=seed.get("resources", {"spirit_stones": 0}),
                inventory=seed.get("inventory", []),
                body=seed.get("body", {}),
                law=seed.get("law", {}),
                flags=seed.get("flags", {}),
                updated_day=1,
            )
        return states

    def build_initial_beliefs(
        self, profiles: dict[str, ActorProfile]
    ) -> dict[str, list[Belief]]:
        beliefs: dict[str, list[Belief]] = {pid: [] for pid in profiles}
        for raw in D.BELIEF_SEEDS:
            b = Belief.model_validate(raw)
            beliefs.setdefault(b.holder_id, []).append(b)
        return beliefs

    def build_world_flags(self) -> dict[str, Any]:
        return dict(D.WORLD_FLAGS)

    def evolve_priority_ids(self, day: int, flags: dict[str, Any]) -> list[str] | None:
        # 越接近死线，强制纳入核心高驱动（再按 score 排序）
        core = [
            "da_shi_xiong",
            "er_shi_xiong",
            "san_shi_jie",
            "shi_mei",
            "zhang_lao_fa",
            "ren_wu_tang_zhu",
            "cang_jing_guan",
        ]
        try:
            cd = int(flags.get("xuanyin_countdown", 99))
        except (TypeError, ValueError):
            cd = 99
        if day >= 20 or cd <= 10:
            return core
        return None

    def evolve_actor_scores(self, session: Any) -> dict[str, float]:
        """按倒计时表加权重；暴露/死亡等状态可再微调。"""
        flags = session.world_flags or {}
        try:
            cd = int(flags.get("xuanyin_countdown", 21))
        except (TypeError, ValueError):
            cd = 21

        table = D.EVOLVE_WEIGHT_BY_COUNTDOWN
        # 取 countdown <= key 的最小 key 档
        applicable = sorted(k for k in table if cd <= k)
        bonus: dict[str, float] = {}
        if applicable:
            tier = min(applicable)
            bonus = {k: float(v) for k, v in table[tier].items()}
        else:
            bonus = {k: float(v) for k, v in table.get(21, {}).items()}

        # 状态微调（仍是数据驱动，非剧本节点）
        lin = session.states.get("er_shi_xiong")
        if lin and lin.alive and lin.flags.get("allegiance") == "xuanyin":
            bonus["er_shi_xiong"] = bonus.get("er_shi_xiong", 0) + 5
            if lin.flags.get("exposed"):
                bonus["zhang_lao_fa"] = bonus.get("zhang_lao_fa", 0) + 20
                bonus["da_shi_xiong"] = bonus.get("da_shi_xiong", 0) + 15

        yun = session.states.get("da_shi_xiong")
        if yun and yun.alive and yun.flags.get("has_evidence"):
            bonus["da_shi_xiong"] = bonus.get("da_shi_xiong", 0) + 10

        return bonus

    def on_new_game(self, session: Any) -> dict:
        """开局引导：只回同构包，引擎 apply。"""
        from app.core.domain.models import BeliefOp

        pid = session.player_id()
        guide = (
            "【客卿须知】你借住落霞宗。每日行动点有限；"
            "点地图前往（部分去处未开放）、点人物对话、点日志看事件。"
            "世界会自转：你若无为，暗流仍会涌动。"
            "可先找白问舟问安，去广场听人言；秘境说法真假、护山异象，皆需你自己查证。"
            "与洛晴相处需耐心；后山等重地须有机缘或许可。"
        )
        loc = session.states[pid].location if pid in session.states else None
        return {
            "state_ops": [],
            "belief_ops": [
                BeliefOp(
                    holder_id=pid,
                    op="upsert",
                    belief_id="guide_day1",
                    proposition=guide,
                    source=BeliefSource.SELF,
                    truth_rel=TruthRel.MATCHES_AUTHORITY,
                    confidence=1.0,
                    day=1,
                )
            ],
            "events": [
                WorldEvent(
                    kind=EventKind.WORLD,
                    severity=Severity.TRIVIAL,
                    title="踏入落霞",
                    summary=guide,
                    actor_ids=[pid],
                    location=loc,
                    day=1,
                    known_to=[pid],
                    card_headline="客卿须知",
                    card_body=guide,
                    involves_player=True,
                    tags=["guide", "onboarding"],
                )
            ],
            "world_flag_ops": {},
            "notes": [],
        }

    def on_day_end(self, session: Any) -> dict:
        from app.content.luoxia import lin_su_shake, shi_mei_arc
        from app.core.services.content_packet import merge_packets

        return merge_packets(
            lin_su_shake.sync_shake_packet(session),
            shi_mei_arc.day_end_packet(session),
        )

    def on_day_rollover(self, session: Any) -> dict:
        """day += 1 之后：倒计时、危机、封山——只回同构包。"""
        from app.content.luoxia import map_access
        from app.content.luoxia.crisis import CrisisTick
        from app.core.services.content_packet import merge_packets

        overlay: dict[str, Any] = {}
        parts: list[dict] = []
        if "xuanyin_countdown" in (session.world_flags or {}):
            try:
                cd = max(0, int(session.world_flags["xuanyin_countdown"]) - 1)
            except (TypeError, ValueError):
                cd = 0
            overlay["xuanyin_countdown"] = cd
            parts.append(
                {
                    "state_ops": [],
                    "belief_ops": [],
                    "events": [],
                    "world_flag_ops": {"xuanyin_countdown": cd},
                    "notes": [],
                }
            )
        parts.append(CrisisTick().as_packet(session, flags_overlay=overlay or None))
        parts.append(map_access.seal_sync_packet(session, flags_overlay=overlay or None))
        return merge_packets(*parts)

    def on_dialogue(
        self,
        session: Any,
        *,
        player_id: str,
        npc_id: str,
        utterance: str,
    ) -> dict:
        if npc_id != "shi_mei":
            return {}
        from app.content.luoxia import shi_mei_arc

        return shi_mei_arc.advance_on_dialogue(session, utterance=utterance)

    def visibility_config(self) -> dict:
        from app.content.luoxia import visibility_cfg

        return visibility_cfg.as_dict()

    def merge_clue_packets(
        self,
        session: Any,
        clue_ids: list[str],
        *,
        player_id: str,
        npc_id: str,
        location: str | None = None,
    ) -> dict:
        from app.content.luoxia.clues import merge_simulated_clues

        return merge_simulated_clues(
            session,
            clue_ids,
            player_id=player_id,
            npc_id=npc_id,
            location=location,
        )

    def refresh_access_state(self, session: Any) -> None:
        """只读：封山/锁点用 seal_active 条件判定，不写 session。"""
        return None

    def location_open(self, session: Any, location_id: str) -> bool:
        from app.content.luoxia import map_access

        return map_access.location_open_for_player(session, location_id)

    def location_lock_reason(self, session: Any, location_id: str) -> str:
        from app.content.luoxia import map_access

        return map_access.lock_reason(session, location_id)

    def location_view_extra(self, session: Any, location_id: str) -> dict:
        from app.content.luoxia import map_access

        return map_access.location_view_extra(session, location_id)

    def after_flags_refresh(self, session: Any) -> dict:
        from app.content.luoxia import map_access

        return map_access.after_flags_packet(session)

    def effect_path_labels(self) -> dict[str, str]:
        return {
            "resources.spirit_stones": "灵石",
            "cultivation.realm": "境界",
            "cultivation.layer": "修为层数",
            "flags.trust": "对你的信任",
            "flags.trust_player": "对你的信任",
            "flags.trusts_player": "是否托付于你",
            "flags.investigating_curse": "追查邪咒",
            "flags.evidence_level": "线索积累",
            "identity.expelled": "被逐出宗",
        }

    def project_session_extra(self, session: Any) -> dict:
        from app.content.luoxia import clue_projection

        pid = session.player_id()
        return {
            "beliefs": [
                clue_projection.enrich_belief_row(b)
                for b in session.beliefs.get(pid, [])
            ],
            "case_lines": clue_projection.project_case_lines(session),
            "clue_flags": clue_projection.project_clue_flags(session),
        }

    def dynamic_prompt_extra(self, session: Any) -> dict:
        return {}

    def enrich_dynamic_extra(
        self,
        session: Any,
        actor_ids: list[str],
        extra: dict | None = None,
    ) -> dict:
        from app.content.luoxia import tendency

        return tendency.attach_tendencies_extra(session, actor_ids, extra)

    def public_tendency_blurb(self, session: Any, actor_id: str) -> str:
        from app.content.luoxia import tendency

        return tendency.public_tendency_blurb(session, actor_id)

    def mock_reply_override(
        self,
        session: Any,
        *,
        speaker_id: str,
        player_utterance: str,
    ) -> Any | None:
        from app.content.luoxia import mock_bias

        return mock_bias.mock_reply_override(
            session, speaker_id=speaker_id, player_utterance=player_utterance
        )

    def bias_intend_goal(self, session: Any, npc_id: str, goal: str) -> str:
        from app.content.luoxia import mock_bias

        return mock_bias.bias_intend_goal(session, npc_id, goal)

    def evaluate_ending_tags(self, session: Any) -> list[str]:
        """
        只读权威状态/flags 打标签——可扩展，非动画分镜。
        """
        tags: list[str] = []
        flags = session.world_flags or {}
        countdown = flags.get("xuanyin_countdown")
        try:
            cd = int(countdown)
        except (TypeError, ValueError):
            cd = None

        if cd == 0 and flags.get("blood_curse_planted"):
            if flags.get("blood_curse_disarmed"):
                tags.append("血阴已解")
            else:
                tags.append("血阴将爆")
                tags.append("宗门危局")

        if flags.get("crisis_averted_noted"):
            tags.append("劫数改写")
        if flags.get("crisis_fired"):
            tags.append("护山曾危")

        if flags.get("fake_secret_realm_letter") and flags.get("letter_exposed"):
            tags.append("假信已揭")

        lin = session.states.get("er_shi_xiong")
        if lin and not lin.alive:
            tags.append("林溯已死")
        elif lin and lin.flags.get("allegiance") == "xuanyin":
            if lin.flags.get("exposed"):
                tags.append("内鬼已揭")
            else:
                tags.append("内鬼未除")

        yun = session.states.get("da_shi_xiong")
        if yun and not yun.alive:
            tags.append("云烨陨落")
        elif yun and yun.alive:
            tags.append("云烨仍在")

        luo = session.states.get("shi_mei")
        if luo and not luo.alive:
            tags.append("洛晴凶信")
        elif luo and luo.flags.get("ally_player"):
            tags.append("洛晴同盟")
        elif luo and luo.flags.get("arc_shi_mei_partial"):
            tags.append("得闻遗命")
        elif luo and luo.flags.get("trusts_player"):
            tags.append("洛晴托付")

        # 剑髓安宗：破阵不强制剑髓；同盟持髓且已镇压 → 叙事加分标签
        if (
            flags.get("blood_curse_disarmed")
            and luo
            and luo.alive
            and (luo.flags.get("ally_player") or luo.flags.get("arc_shi_mei_ally"))
            and luo.flags.get("holds_luoxia_jian_sui")
        ):
            tags.append("剑髓安宗")

        # 站队轻量标签（规格 §6.1）
        p_st = session.states.get(session.player_id())
        pflags = dict(p_st.flags or {}) if p_st else {}
        lin_exposed = bool(lin and lin.flags.get("exposed"))
        if lin_exposed or pflags.get("faction_lean_yun"):
            tags.append("站云烨")
        elif pflags.get("faction_lean_lin") and lin and lin.alive and not lin_exposed:
            tags.append("站林溯")
        elif (
            not flags.get("letter_exposed")
            and not (luo and (luo.flags.get("ally_player") or luo.flags.get("arc_shi_mei_ally")))
            and not pflags.get("faction_lean_lin")
            and not pflags.get("faction_lean_yun")
        ):
            tags.append("独善其身")

        su = session.states.get("san_shi_jie")
        if su and su.flags.get("cursed_backlash"):
            tags.append("苏婉反噬")

        if flags.get("sect_destroyed"):
            tags.append("落霞覆灭")
        elif flags.get("sect_stabilized"):
            tags.append("宗门暂稳")

        return tags
