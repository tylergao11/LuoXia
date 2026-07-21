from __future__ import annotations

from abc import ABC, abstractmethod
from typing import Any, TYPE_CHECKING

from app.core.domain.models import (
    ActorProfile,
    AuthorityState,
    Belief,
    MapGraph,
    WorldRules,
)

if TYPE_CHECKING:
    from app.core.domain.models import GameSession


class WorldPack(ABC):
    """
    世界内容包抽象。

    引擎只依赖本接口：换世界 = 换 WorldPack 实现，不改 DayLoop / 天道端口。
    落霞宗是第一个具体包，不是引擎本身。
    """

    @property
    @abstractmethod
    def world_id(self) -> str:
        ...

    @property
    @abstractmethod
    def display_name(self) -> str:
        ...

    @abstractmethod
    def background_text(self) -> str:
        """常驻世界背景（精简，供天道输入）。"""

    @abstractmethod
    def rules(self) -> WorldRules:
        ...

    @abstractmethod
    def build_map(self) -> MapGraph:
        ...

    @abstractmethod
    def build_profiles(self) -> dict[str, ActorProfile]:
        ...

    @abstractmethod
    def build_initial_states(
        self, profiles: dict[str, ActorProfile]
    ) -> dict[str, AuthorityState]:
        ...

    def build_initial_beliefs(
        self, profiles: dict[str, ActorProfile]
    ) -> dict[str, list[Belief]]:
        """默认空信念；子类可覆写开局见闻。"""
        return {pid: [] for pid in profiles}

    def build_world_flags(self) -> dict[str, Any]:
        """开局隐藏种子 / 世界级 flags。"""
        return {}

    def evolve_priority_ids(self, day: int, flags: dict[str, Any]) -> list[str] | None:
        """
        日终优先队列提示（可选）。
        返回 None 表示交给引擎按 drive_priority + evolve_actor_scores 排序。
        """
        return None

    def evolve_actor_scores(self, session: "GameSession") -> dict[str, float]:
        """
        日终额外权重（内容包配置阴谋/线进度，引擎只做数值相加排序）。
        返回 actor_id -> 加分；默认空。
        """
        return {}

    def on_new_game(self, session: "GameSession") -> dict:
        """
        开局钩子：只返回同构 ContentPacket，由引擎 StateApplier 落地。
        禁止直改 session.states / beliefs / world_flags / events。
        """
        return {}

    def on_day_end(self, session: "GameSession") -> dict:
        """日终内容钩子：返回同构包（state/belief/flag/events），引擎 apply。"""
        return {}

    def on_day_rollover(self, session: "GameSession") -> dict:
        """day += 1 之后：倒计时/危机等；返回同构包，引擎 apply。"""
        return {}

    def on_dialogue(
        self,
        session: "GameSession",
        *,
        player_id: str,
        npc_id: str,
        utterance: str,
    ) -> dict:
        """
        对话后内容钩子：条件线索等固定包。
        返回同构包；引擎合并进 AdjudicationResult → StateApplier。
        禁止直改 session；禁止按台词关键词推进。
        """
        return {}

    def on_move(
        self,
        session: "GameSession",
        *,
        player_id: str,
        from_location: str | None,
        to_location: str,
    ) -> dict:
        """移动成功后：条件线索（首次抵达等）固定包。"""
        return {}

    def visibility_config(self) -> dict:
        """可见性表（敏感旗 / belief 前缀）；默认空=无内容专有置灰。"""
        return {}

    def merge_clue_packets(
        self,
        session: "GameSession",
        clue_ids: list[str],
        *,
        player_id: str,
        npc_id: str,
        location: str | None = None,
    ) -> dict:
        """按线索 id 合并同构包（调试/工具用）。默认空。"""
        return {
            "state_ops": [],
            "belief_ops": [],
            "events": [],
            "world_flag_ops": {},
            "notes": [],
        }

    def refresh_access_state(self, session: "GameSession") -> None:
        """
        移动/展示前的只读同步钩子。
        不得写 session；锁判定应纯读 flags/条件。
        """
        return None

    def location_open(self, session: "GameSession", location_id: str) -> bool:
        """地点是否对玩家开放。默认 True。"""
        return True

    def location_lock_reason(self, session: "GameSession", location_id: str) -> str:
        return ""

    def location_view_extra(self, session: "GameSession", location_id: str) -> dict:
        """客户端地图行附加字段。"""
        return {"unlocked": True, "locked": False, "lock_reason": "", "start_open": True}

    def after_flags_refresh(self, session: "GameSession") -> dict:
        """
        裁决落地后按硬状态补解锁/封山同步等。
        返回同构包；引擎 apply。不得直改 session。
        """
        return {}

    def effect_path_labels(self) -> dict[str, str]:
        """state_ops 路径 → 玩家可读标签（内容扩展；引擎仅通用兜底）。"""
        return {}

    def project_session_extra(self, session: "GameSession") -> dict:
        """
        客户端知识投影（见闻分类 / 隐情灰字 / 交锋 DTO 等）。
        返回 {beliefs?, clue_flags?, encounter?}；空则 api 用默认。
        """
        return {}

    def encounter_move_catalog(self) -> list[dict]:
        """交锋可选小招表（兼容）；优先用 encounter_moves_for。"""
        return []

    def encounter_moves_for(self, session: "GameSession", actor_id: str) -> list[dict]:
        """按持有功法解析小招；无功法时玩家空表、NPC 可回落底库。"""
        return []

    def encounter_qi_cap(self, cultivation: dict) -> int:
        """境界 → 本场气上限。"""
        return 5

    def encounter_cultivation_amp(self, cultivation: dict) -> float:
        """修为线性放大系数（有效值乘数）。"""
        layer = 0
        try:
            layer = int((cultivation or {}).get("layer") or 0)
        except (TypeError, ValueError):
            layer = 0
        return 1.0 + max(0, layer) * 0.08

    def dynamic_prompt_extra(self, session: "GameSession") -> dict[str, Any]:
        """LLM DYNAMIC 附加（倾向摘要等）。"""
        return {}

    def enrich_dynamic_extra(
        self,
        session: "GameSession",
        actor_ids: list[str],
        extra: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        return dict(extra or {})

    def public_tendency_blurb(self, session: "GameSession", actor_id: str) -> str:
        return ""
