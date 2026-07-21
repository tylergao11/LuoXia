"""
真相字典：会话硬状态权威键。

投影只读这些键；graph_meta 全部是草稿/缓存，不算玩家真相。
对白权威 = GameSession.dialogue（不是 graph_meta）。
"""

from __future__ import annotations

from typing import Any

from app.core.domain.models import GameSession

TRUTH_KEYS: frozenset[str] = frozenset(
    {
        "session_id",
        "world_id",
        "phase",
        "day",
        "ap",
        "profiles",
        "states",
        "beliefs",
        "events",
        "map",
        "rules",
        "world_flags",
        "background_text",
        "game_over_reason",
        "evolve_queue",
        "evolve_index",
        "dialogue",
    }
)

# graph_meta 可缓存/草稿，禁止当玩家真相
SHADOW_GRAPH_META_KEYS: frozenset[str] = frozenset(
    {
        "last_effects",
        "last_new_events",
        "settlement_summary",
        "settlement_event_ids",
        "chat_by_actor",  # 旧键；应已迁入 session.dialogue
        "_talk_adj",
        "_talk_material",
        "_talk_fast",
        "_talk_proclamation_content",
        "llm_threads",
        "llm_state_diff_log",
        "llm_memory_log",
        "evolve_intents",
        "evolve_play_order",
        "evolve_last_actor",
        "frozen_stable",
        "frozen_stable_fp",
        "last_talk_thread",
    }
)


def snapshot(session: GameSession) -> dict[str, Any]:
    """只读真相字典切片（投影输入 ⊆ 本 dict）。"""
    from app.core.services import chat_log

    # 触发旧仓迁移
    dialogue = chat_log.chat_store(session)
    phase = session.phase.value if hasattr(session.phase, "value") else str(session.phase)
    return {
        "session_id": session.session_id,
        "world_id": session.world_id,
        "phase": phase,
        "day": session.day,
        "ap": session.ap,
        "profiles": {
            k: (v.model_dump(mode="json") if hasattr(v, "model_dump") else v)
            for k, v in (session.profiles or {}).items()
        },
        "states": {
            k: (v.model_dump(mode="json") if hasattr(v, "model_dump") else v)
            for k, v in (session.states or {}).items()
        },
        "beliefs": {
            k: [
                b.model_dump(mode="json") if hasattr(b, "model_dump") else b
                for b in (lst or [])
            ]
            for k, lst in (session.beliefs or {}).items()
        },
        "events": [
            e.model_dump(mode="json") if hasattr(e, "model_dump") else e
            for e in (session.events or [])
        ],
        "map": session.map.model_dump(mode="json") if hasattr(session.map, "model_dump") else session.map,
        "rules": session.rules.model_dump(mode="json") if hasattr(session.rules, "model_dump") else session.rules,
        "world_flags": dict(session.world_flags or {}),
        "background_text": session.background_text or "",
        "game_over_reason": session.game_over_reason,
        "evolve_queue": list(session.evolve_queue or []),
        "evolve_index": int(session.evolve_index or 0),
        "dialogue": {
            str(k): {
                "actor_id": (th or {}).get("actor_id") or k,
                "updated_day": (th or {}).get("updated_day"),
                "messages": list((th or {}).get("messages") or []),
            }
            for k, th in (dialogue or {}).items()
            if isinstance(th, dict)
        },
    }


def assert_snapshot_keys(snap: dict[str, Any]) -> None:
    keys = frozenset(snap.keys())
    if keys != TRUTH_KEYS:
        missing = TRUTH_KEYS - keys
        extra = keys - TRUTH_KEYS
        raise AssertionError(f"truth snapshot keys mismatch missing={missing} extra={extra}")
