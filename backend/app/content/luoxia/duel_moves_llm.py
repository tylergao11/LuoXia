"""开战时可选：LLM 按功法花式组合小招；校验失败回退 compose_moves_from_art。"""

from __future__ import annotations

import logging
from typing import Any

from app.content.luoxia import duel_demo

logger = logging.getLogger("luoxia.duel.moves")

_GEN_SYSTEM = """你是落霞交锋的「小招组合器」。
根据功法的 tags 与 axis_bias，生成 4～6 个合法小招。
只输出一个 JSON 对象：
{"moves":[{"move_id","name","from_art_id","qi_cost","tags","axes","flavor"},...]}

硬规则：
- tags 每个 id 必须 ∈ 给定字母表
- qi_cost ≥ 1 整数；单招不超过 3
- axes 为数值对象，至少含 strike 或 guard 之一（可为 0）
- move_id 用英文 snake，带 from_art_id 前缀防撞
- name/flavor 可花式中文；禁止表外机制描述当规则
- 整段只 JSON，无 markdown
"""


def generate_moves_for_arts(
    arts: list[dict[str, Any]],
    *,
    llm_client: Any | None = None,
    realm: str = "",
) -> list[dict[str, Any]]:
    """
    尝试 LLM 生成；任一失败或全非法 → 规则组合。
    战斗过程中不要调用。
    """
    fallback: list[dict[str, Any]] = []
    for art in arts:
        fallback.extend(duel_demo.compose_moves_from_art(art))
    fallback = duel_demo.sanitize_moves(fallback)
    if not arts:
        return fallback
    if llm_client is None or not getattr(llm_client, "available", False):
        return fallback

    alphabet = sorted(duel_demo.TAG_ALPHABET.keys())
    user = {
        "alphabet": alphabet,
        "realm": realm or "",
        "arts": [
            {
                "art_id": a.get("art_id"),
                "name": a.get("name"),
                "tags": a.get("tags"),
                "axis_bias": a.get("axis_bias") or {},
                "lore": (a.get("lore") or "")[:80],
            }
            for a in arts
        ],
        "hint": duel_demo.tag_prompt_block(),
    }
    try:
        import json

        raw = llm_client.chat_json(
            system=_GEN_SYSTEM,
            user=json.dumps(user, ensure_ascii=False),
            temperature=0.55,
            max_tokens=700,
            tag="duel:compose_moves",
        )
        moves = duel_demo.sanitize_moves(raw.get("moves") if isinstance(raw, dict) else None)
        # 至少能打出一手（存在 qi_cost<=气 的招由外层保证；这里保证非空且覆盖每门功法感）
        if len(moves) >= 3:
            logger.info("[duel] LLM moves ok n=%s", len(moves))
            return moves
        logger.warning("[duel] LLM moves too few n=%s → fallback", len(moves))
    except Exception as e:  # noqa: BLE001
        logger.warning("[duel] LLM moves fail: %s → fallback", e)
    return fallback
