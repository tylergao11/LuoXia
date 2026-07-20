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

    def evaluate_ending_tags(self, session: "GameSession") -> list[str]:
        """世界包结局标签（读权威状态/flags，勿在引擎写死剧情）。"""
        return []

    def on_new_game(self, session: "GameSession") -> None:
        """开局钩子：可写入引导事件/初始信念。"""
        return None

    def on_day_end(self, session: "GameSession") -> list:
        """日终内容钩子（可选）。返回额外 WorldEvent 列表。"""
        return []

    def on_dialogue(
        self,
        session: "GameSession",
        *,
        player_id: str,
        npc_id: str,
        utterance: str,
    ) -> dict:
        """
        对话后内容钩子（可选）。
        返回 {notes?, events?}；引擎/Mock 可合并进叙事。
        """
        return {}
