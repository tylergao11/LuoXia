"""青溪小驿——迷你世界包，证明引擎可挂第二套内容。"""

from __future__ import annotations

from typing import Any

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

BACKGROUND = """
青溪小驿是山道上的普通驿站。没有秘境死线，只有过客、店家与捕快的日常因果。
本世界包用于验证：同一套引擎可加载不同地图与角色。
""".strip()


class QingxiWorldPack(WorldPack):
    @property
    def world_id(self) -> str:
        return "qingxi"

    @property
    def display_name(self) -> str:
        return "青溪小驿"

    def background_text(self) -> str:
        return BACKGROUND

    def rules(self) -> WorldRules:
        return WorldRules(
            max_days=14,
            daily_ap=5,
            move_ap_cost=1,
            player_actor_id="player",
            high_drive_min_priority=40,
        )

    def build_map(self) -> MapGraph:
        nodes = {
            "yard": LocationNode(
                id="yard",
                name="驿站前院",
                summary="拴马石与尘土飞扬。",
                art_key="yard",
                tags=["public", "order"],
            ),
            "hall": LocationNode(
                id="hall",
                name="大堂",
                summary="酒饭与闲话。",
                art_key="hall",
                tags=["public", "social"],
            ),
            "room": LocationNode(
                id="room",
                name="客房",
                summary="木床与纸窗。",
                art_key="room",
                tags=["secluded"],
            ),
            "road": LocationNode(
                id="road",
                name="官道",
                summary="南来北往。",
                art_key="road",
                tags=["public"],
            ),
        }
        edges = {
            "yard": ["hall", "road"],
            "hall": ["yard", "room"],
            "room": ["hall"],
            "road": ["yard"],
        }
        # 双向
        for a, tos in list(edges.items()):
            for b in tos:
                edges.setdefault(b, [])
                if a not in edges[b]:
                    edges[b].append(a)
        return MapGraph(nodes=nodes, edges=edges)

    def build_profiles(self) -> dict[str, ActorProfile]:
        raw = [
            ActorProfile(
                id="player",
                display_name="过客",
                title="旅客",
                summary="借住一晚的过客。",
                personality="由玩家决定",
                drives="歇脚或探听",
                is_player=True,
                default_location="room",
            ),
            ActorProfile(
                id="innkeeper",
                display_name="老郑",
                title="驿丞",
                summary="精明的驿站主人。",
                personality="热心、爱打听",
                drives="做生意、听八卦",
                drive_priority=60,
                default_location="hall",
                tags=["gossip", "social"],
            ),
            ActorProfile(
                id="constable",
                display_name="阿捕",
                title="巡路捕快",
                summary="路过盘查的官差。",
                personality="刻板、尽职",
                drives="查案、维持治安",
                drive_priority=70,
                can_proclaim=True,
                default_location="yard",
                tags=["law", "investigator"],
            ),
            ActorProfile(
                id="wanderer",
                display_name="青衫客",
                title="游侠",
                summary="不多话的剑客。",
                personality="冷淡寡言",
                drives="独自赶路",
                drive_priority=50,
                default_location="road",
                tags=["reclusive"],
            ),
        ]
        return {p.id: p for p in raw}

    def build_initial_states(
        self, profiles: dict[str, ActorProfile]
    ) -> dict[str, AuthorityState]:
        out: dict[str, AuthorityState] = {}
        for pid, prof in profiles.items():
            out[pid] = AuthorityState(
                actor_id=pid,
                location=prof.default_location,
                identity={"title": prof.title},
                cultivation={"realm": "凡人"} if pid != "wanderer" else {"realm": "炼气"},
                resources={"spirit_stones": 10 if pid == "player" else 5},
                inventory=[{"item_id": "bag", "name": "行囊", "qty": 1}]
                if pid == "player"
                else [],
            )
        return out

    def build_initial_beliefs(
        self, profiles: dict[str, ActorProfile]
    ) -> dict[str, list[Belief]]:
        return {pid: [] for pid in profiles}

    def build_world_flags(self) -> dict[str, Any]:
        return {"peaceful_inn": True, "xuanyin_countdown": 14}

    def on_new_game(self, session: Any) -> dict:
        from app.core.domain.models import BeliefOp

        pid = session.player_id()
        text = "你在青溪小驿落脚。可先到大堂找老郑打听官道消息，或在前院见见捕快。"
        return {
            "state_ops": [],
            "belief_ops": [
                BeliefOp(
                    holder_id=pid,
                    op="upsert",
                    belief_id="qingxi_guide",
                    proposition=text,
                    source=BeliefSource.SELF,
                    day=1,
                )
            ],
            "events": [
                WorldEvent(
                    kind=EventKind.WORLD,
                    severity=Severity.TRIVIAL,
                    title="驿站一宿",
                    summary=text,
                    actor_ids=[pid],
                    day=1,
                    known_to=[pid],
                    card_headline="落脚",
                    card_body=text,
                    involves_player=True,
                    tags=["guide"],
                )
            ],
            "world_flag_ops": {},
            "notes": [],
        }

    def on_day_rollover(self, session: Any) -> dict:
        if "xuanyin_countdown" not in (session.world_flags or {}):
            return {}
        try:
            cd = max(0, int(session.world_flags["xuanyin_countdown"]) - 1)
        except (TypeError, ValueError):
            cd = 0
        return {
            "state_ops": [],
            "belief_ops": [],
            "events": [],
            "world_flag_ops": {"xuanyin_countdown": cd},
            "notes": [],
        }

    def evaluate_ending_tags(self, session: Any) -> list[str]:
        tags = ["青溪一宿"]
        if session.day >= session.rules.max_days:
            tags.append("继续赶路")
        st = session.states.get("player")
        if st and st.flags.get("expelled"):
            tags.append("被赶出驿站")
        return tags
