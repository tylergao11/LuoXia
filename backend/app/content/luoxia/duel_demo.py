"""落霞交锋：默认功法 + 封闭小招表 + 境界气上限（最小切片，非 LLM）。"""

from __future__ import annotations

from typing import Any

# 境界前缀 → 气上限（与 docs/luoxia.md §10.2 对齐）
QI_CAP_BY_REALM_PREFIX: list[tuple[str, int]] = [
    ("结丹", 9),
    ("筑基", 7),
    ("炼气", 5),
    ("练气", 5),
]
QI_CAP_DEFAULT = 5

# 修为线性放大：有效值 = 底数 × (1 + layer * COEF)
CULTIVATION_LINEAR_COEF = 0.08

# 客卿开局默认功法（进不了功法阁也能切磋）
DEFAULT_ART_ID = "art_guest_breath"

DEFAULT_ART: dict[str, Any] = {
    "art_id": DEFAULT_ART_ID,
    "name": "客途吐纳诀",
    "lore": "外门客卿自携的粗浅吐纳，攻守尚可，难登大雅。",
    "tags": ["strike", "guard", "break", "bind"],
    "axis_bias": {"strike": 1, "guard": 1},
}

# 由默认功法词条「预组合」出的小招（日后改 LLM 生成，结构不变）
DEFAULT_ART_MOVES: list[dict[str, Any]] = [
    {
        "move_id": "guest_strike_light",
        "name": "轻击",
        "from_art_id": DEFAULT_ART_ID,
        "qi_cost": 1,
        "tags": ["strike"],
        "axes": {"strike": 2, "guard": 0},
        "flavor": "试探一掌",
    },
    {
        "move_id": "guest_guard_firm",
        "name": "守势",
        "from_art_id": DEFAULT_ART_ID,
        "qi_cost": 1,
        "tags": ["guard"],
        "axes": {"strike": 0, "guard": 2},
        "flavor": "沉肩护心",
    },
    {
        "move_id": "guest_break_rush",
        "name": "破势",
        "from_art_id": DEFAULT_ART_ID,
        "qi_cost": 2,
        "tags": ["break", "strike"],
        "axes": {"strike": 3, "guard": 0},
        "flavor": "直取门户",
    },
    {
        "move_id": "guest_bind_silk",
        "name": "缠丝",
        "from_art_id": DEFAULT_ART_ID,
        "qi_cost": 2,
        "tags": ["bind", "guard"],
        "axes": {"strike": 1, "guard": 2},
        "flavor": "粘走卸力",
    },
]

# NPC 无功法时的底库（宗门粗功，不进玩家背包）
NPC_BASIC_ART_ID = "art_sect_basic"
NPC_BASIC_MOVES: list[dict[str, Any]] = [
    {
        "move_id": "sect_strike",
        "name": "劈掌",
        "from_art_id": NPC_BASIC_ART_ID,
        "qi_cost": 1,
        "tags": ["strike"],
        "axes": {"strike": 2, "guard": 0},
        "flavor": "外门常手",
    },
    {
        "move_id": "sect_guard",
        "name": "横拦",
        "from_art_id": NPC_BASIC_ART_ID,
        "qi_cost": 1,
        "tags": ["guard"],
        "axes": {"strike": 0, "guard": 2},
        "flavor": "架势一挡",
    },
    {
        "move_id": "sect_break",
        "name": "崩拳",
        "from_art_id": NPC_BASIC_ART_ID,
        "qi_cost": 2,
        "tags": ["break", "strike"],
        "axes": {"strike": 3, "guard": 0},
        "flavor": "力贯臂弯",
    },
]

# art_id → 小招表（生成器落地后往这里挂）
ART_MOVES: dict[str, list[dict[str, Any]]] = {
    DEFAULT_ART_ID: DEFAULT_ART_MOVES,
    NPC_BASIC_ART_ID: NPC_BASIC_MOVES,
}


def default_art_inventory_item() -> dict[str, Any]:
    """开局 / 补发用的随身功法条目。"""
    return {
        "item_id": DEFAULT_ART_ID,
        "name": DEFAULT_ART["name"],
        "qty": 1,
        "kind": "gongfa",
        "art_id": DEFAULT_ART_ID,
        "lore": DEFAULT_ART["lore"],
        "tags": list(DEFAULT_ART.get("tags") or []),
    }


def qi_cap_for(cultivation: dict[str, Any] | None) -> int:
    realm = str((cultivation or {}).get("realm") or "")
    for prefix, cap in QI_CAP_BY_REALM_PREFIX:
        if realm.startswith(prefix):
            return cap
    return QI_CAP_DEFAULT


def cultivation_amp(cultivation: dict[str, Any] | None) -> float:
    layer = 0
    try:
        layer = int((cultivation or {}).get("layer") or 0)
    except (TypeError, ValueError):
        layer = 0
    return 1.0 + max(0, layer) * CULTIVATION_LINEAR_COEF


def move_catalog() -> list[dict[str, Any]]:
    """全表（调试 / 兼容）；正式交锋应用 moves_for_inventory。"""
    out: list[dict[str, Any]] = []
    for moves in ART_MOVES.values():
        out.extend(dict(m) for m in moves)
    return out


def moves_for_art_ids(art_ids: list[str]) -> list[dict[str, Any]]:
    seen: set[str] = set()
    out: list[dict[str, Any]] = []
    for aid in art_ids:
        for m in ART_MOVES.get(str(aid), []):
            mid = str(m.get("move_id") or "")
            if not mid or mid in seen:
                continue
            seen.add(mid)
            out.append(dict(m))
    return out


def art_ids_from_inventory(inventory: list[Any] | None) -> list[str]:
    ids: list[str] = []
    seen: set[str] = set()
    for it in inventory or []:
        if not isinstance(it, dict):
            continue
        kind = str(it.get("kind") or "")
        aid = str(it.get("art_id") or it.get("item_id") or "").strip()
        if kind and kind not in ("gongfa", "art", "功法"):
            # 无 kind 时：item_id 在 ART_MOVES 里也算功法
            if aid not in ART_MOVES:
                continue
        elif not aid:
            continue
        if aid not in ART_MOVES:
            continue
        if aid in seen:
            continue
        seen.add(aid)
        ids.append(aid)
    return ids


def moves_for_inventory(inventory: list[Any] | None) -> list[dict[str, Any]]:
    return moves_for_art_ids(art_ids_from_inventory(inventory))


def moves_for_actor_inventory(
    inventory: list[Any] | None, *, foe_fallback: bool = False
) -> list[dict[str, Any]]:
    moves = moves_for_inventory(inventory)
    if moves:
        return moves
    if foe_fallback:
        return [dict(m) for m in NPC_BASIC_MOVES]
    return []


def move_by_id(move_id: str) -> dict[str, Any] | None:
    mid = str(move_id or "").strip()
    for m in move_catalog():
        if m["move_id"] == mid:
            return dict(m)
    return None


def inventory_has_art(inventory: list[Any] | None, art_id: str = DEFAULT_ART_ID) -> bool:
    want = str(art_id)
    for it in inventory or []:
        if not isinstance(it, dict):
            continue
        if str(it.get("art_id") or it.get("item_id") or "") == want:
            return True
    return False
