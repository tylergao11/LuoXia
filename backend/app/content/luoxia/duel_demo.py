"""落霞交锋：词条字母表、功法、小招组合/校验（内容包真相）。"""

from __future__ import annotations

from typing import Any

# ── 词条字母表（§10.2 封闭骨 · 可扩展）────────────────────────
TAG_ALPHABET: dict[str, str] = {
    "strike": "攻",
    "guard": "守",
    "break": "破势",
    "bind": "缠",
    "reflect": "反噬",
    "drain": "耗",
    "feint": "虚",
    "pierce": "透",
    "crush": "砸",
    "evade": "闪",
    "rally": "振",
    "suppress": "压",
    "swift": "疾",
    "heavy": "沉",
    "chain": "连",
    "seal": "封",
    "poison": "蚀",
    "mend": "息",
    "shock": "震",
    "cloak": "隐",
}

# 境界前缀 → 气上限
QI_CAP_BY_REALM_PREFIX: list[tuple[str, int]] = [
    ("化神", 13),
    ("元婴", 11),
    ("结丹", 9),
    ("金丹", 9),
    ("筑基", 7),
    ("炼气", 5),
    ("练气", 5),
]
QI_CAP_DEFAULT = 5
CULTIVATION_LINEAR_COEF = 0.08

DEFAULT_ART_ID = "art_guest_breath"
DEFAULT_ART: dict[str, Any] = {
    "art_id": DEFAULT_ART_ID,
    "name": "客途吐纳诀",
    "lore": "外门客卿自携的粗浅吐纳，攻守尚可，难登大雅。",
    "tags": ["strike", "guard", "break", "bind", "feint"],
    "axis_bias": {"strike": 1, "guard": 1},
}

NPC_BASIC_ART_ID = "art_sect_basic"
NPC_BASIC_ART: dict[str, Any] = {
    "art_id": NPC_BASIC_ART_ID,
    "name": "外门粗功",
    "lore": "宗门杂役常练的架子。",
    "tags": ["strike", "guard", "break", "crush"],
    "axis_bias": {"strike": 1, "guard": 1},
}


def default_art_inventory_item() -> dict[str, Any]:
    return {
        "item_id": DEFAULT_ART_ID,
        "name": DEFAULT_ART["name"],
        "qty": 1,
        "kind": "gongfa",
        "art_id": DEFAULT_ART_ID,
        "lore": DEFAULT_ART["lore"],
        "tags": list(DEFAULT_ART.get("tags") or []),
        "axis_bias": dict(DEFAULT_ART.get("axis_bias") or {}),
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


def validate_move(move: dict[str, Any] | None) -> list[str]:
    if not isinstance(move, dict):
        return ["move_not_object"]
    errs: list[str] = []
    if not str(move.get("move_id") or "").strip():
        errs.append("missing_move_id")
    if not str(move.get("name") or "").strip():
        errs.append("missing_name")
    try:
        cost = int(move.get("qi_cost") or 0)
    except (TypeError, ValueError):
        cost = 0
        errs.append("qi_cost_invalid")
    if cost < 1:
        errs.append("qi_cost_lt_1")
    tags = move.get("tags") or []
    if not isinstance(tags, list) or not tags:
        errs.append("tags_empty")
    else:
        for t in tags:
            if str(t) not in TAG_ALPHABET:
                errs.append(f"tag_unknown:{t}")
    axes = move.get("axes")
    if not isinstance(axes, dict):
        errs.append("axes_not_object")
    else:
        for k, v in axes.items():
            try:
                float(v)
            except (TypeError, ValueError):
                errs.append(f"axis_nan:{k}")
    return errs


def sanitize_moves(moves: list[Any] | None) -> list[dict[str, Any]]:
    """过滤非法小招，规范化字段。"""
    out: list[dict[str, Any]] = []
    seen: set[str] = set()
    for raw in moves or []:
        if not isinstance(raw, dict):
            continue
        m = {
            "move_id": str(raw.get("move_id") or "").strip(),
            "name": str(raw.get("name") or "").strip(),
            "from_art_id": str(raw.get("from_art_id") or "").strip(),
            "qi_cost": int(raw.get("qi_cost") or 0),
            "tags": [str(t) for t in (raw.get("tags") or []) if str(t) in TAG_ALPHABET],
            "axes": {},
            "flavor": str(raw.get("flavor") or "")[:80],
        }
        axes_in = raw.get("axes") if isinstance(raw.get("axes"), dict) else {}
        for k, v in axes_in.items():
            try:
                m["axes"][str(k)] = float(v)
            except (TypeError, ValueError):
                continue
        if validate_move(m):
            continue
        mid = m["move_id"]
        if mid in seen:
            continue
        seen.add(mid)
        out.append(m)
    return out


def compose_moves_from_art(art: dict[str, Any]) -> list[dict[str, Any]]:
    """功法 tags + axis_bias → 3～8 招（确定性，不调用 LLM）。"""
    art_id = str(art.get("art_id") or art.get("item_id") or "art_unknown")
    tags = [str(t) for t in (art.get("tags") or []) if str(t) in TAG_ALPHABET]
    if not tags:
        tags = ["strike", "guard"]
    bias = art.get("axis_bias") if isinstance(art.get("axis_bias"), dict) else {}
    sb = float(bias.get("strike") or 1)
    gb = float(bias.get("guard") or 1)

    recipes: list[tuple[str, str, int, list[str], dict[str, float], str]] = []

    def add(
        suffix: str,
        name: str,
        cost: int,
        tgs: list[str],
        axes: dict[str, float],
        flavor: str,
    ) -> None:
        tgs2 = [t for t in tgs if t in TAG_ALPHABET]
        if not tgs2:
            return
        recipes.append((suffix, name, cost, tgs2, axes, flavor))

    if "strike" in tags:
        add("strike_light", "轻击", 1, ["strike"], {"strike": 1.5 + sb, "guard": 0}, "试探一掌")
        add("strike_heavy", "重斩", 2, ["strike", "heavy"] if "heavy" in tags else ["strike"], {"strike": 2.5 + sb, "guard": 0}, "全力一击")
    if "guard" in tags:
        add("guard_firm", "守势", 1, ["guard"], {"strike": 0, "guard": 1.5 + gb}, "沉肩护心")
    if "break" in tags:
        add("break_rush", "破势", 2, ["break", "strike"] if "strike" in tags else ["break"], {"strike": 2.0 + sb, "guard": 0}, "直取门户")
    if "bind" in tags:
        add("bind_silk", "缠丝", 2, ["bind", "guard"] if "guard" in tags else ["bind"], {"strike": 0.5 + sb * 0.3, "guard": 1.5 + gb}, "粘走卸力")
    if "reflect" in tags:
        add("reflect_mirror", "反噬", 2, ["reflect", "guard"] if "guard" in tags else ["reflect"], {"strike": 1.0, "guard": 1.0 + gb * 0.5}, "以彼之道还施彼身")
    if "drain" in tags:
        add("drain_sip", "抽丝", 2, ["drain", "strike"] if "strike" in tags else ["drain"], {"strike": 1.2 + sb * 0.4, "guard": 0}, "吸其气机")
    if "feint" in tags:
        add("feint_shadow", "虚晃", 1, ["feint", "swift"] if "swift" in tags else ["feint"], {"strike": 1.0 + sb * 0.5, "guard": 0.5}, "声东击西")
    if "pierce" in tags:
        add("pierce_needle", "透劲", 2, ["pierce", "strike"] if "strike" in tags else ["pierce"], {"strike": 2.2 + sb, "guard": 0}, "专破厚防")
    if "crush" in tags:
        add("crush_mountain", "崩砸", 2, ["crush", "heavy"] if "heavy" in tags else ["crush"], {"strike": 2.8 + sb, "guard": 0}, "力压四野")
    if "evade" in tags:
        add("evade_slip", "侧闪", 1, ["evade", "guard"] if "guard" in tags else ["evade"], {"strike": 0, "guard": 2.0 + gb}, "借力化劲")
    if "rally" in tags:
        add("rally_breath", "振息", 1, ["rally", "mend"] if "mend" in tags else ["rally"], {"strike": 0.5, "guard": 1.2 + gb}, "气沉丹田")
    if "suppress" in tags:
        add("suppress_aura", "压境", 2, ["suppress"], {"strike": 1.0, "guard": 1.5}, "以势压人")
    if "swift" in tags and "strike" in tags:
        add("swift_cut", "疾斩", 1, ["swift", "strike"], {"strike": 1.8 + sb * 0.7, "guard": 0}, "快若惊鸿")
    if "chain" in tags:
        add("chain_link", "连击", 2, ["chain", "strike"] if "strike" in tags else ["chain"], {"strike": 1.6 + sb, "guard": 0.3}, "连环三手")
    if "seal" in tags:
        add("seal_lock", "封脉", 2, ["seal", "bind"] if "bind" in tags else ["seal"], {"strike": 0.8, "guard": 1.0}, "锁其气机")
    if "shock" in tags:
        add("shock_clap", "震掌", 2, ["shock", "strike"] if "strike" in tags else ["shock"], {"strike": 2.0 + sb, "guard": 0.5}, "劲透脏腑")
    if "poison" in tags:
        add("poison_touch", "蚀指", 2, ["poison", "drain"] if "drain" in tags else ["poison"], {"strike": 1.4, "guard": 0}, "阴劲入体")
    if "cloak" in tags:
        add("cloak_mist", "隐踪", 1, ["cloak", "evade"] if "evade" in tags else ["cloak"], {"strike": 0.5, "guard": 1.8}, "身形一晃")
    if "mend" in tags and "rally" not in tags:
        add("mend_calm", "调息", 1, ["mend"], {"strike": 0, "guard": 1.5 + gb}, "暂避锋芒")

    if not recipes:
        add("strike_light", "轻击", 1, ["strike"], {"strike": 2.0, "guard": 0}, "试探")
        add("guard_firm", "守势", 1, ["guard"], {"strike": 0, "guard": 2.0}, "架势")

    out: list[dict[str, Any]] = []
    for suffix, name, cost, tgs, axes, flavor in recipes[:8]:
        move = {
            "move_id": f"{art_id}_{suffix}",
            "name": name,
            "from_art_id": art_id,
            "qi_cost": cost,
            "tags": tgs,
            "axes": axes,
            "flavor": flavor,
        }
        if not validate_move(move):
            out.append(move)
    return out


def arts_from_inventory(inventory: list[Any] | None) -> list[dict[str, Any]]:
    arts: list[dict[str, Any]] = []
    seen: set[str] = set()
    for it in inventory or []:
        if not isinstance(it, dict):
            continue
        kind = str(it.get("kind") or "")
        aid = str(it.get("art_id") or it.get("item_id") or "").strip()
        if kind and kind not in ("gongfa", "art", "功法"):
            if not aid:
                continue
        if not aid or aid in seen:
            continue
        seen.add(aid)
        tags = [str(t) for t in (it.get("tags") or []) if str(t) in TAG_ALPHABET]
        if not tags and aid == DEFAULT_ART_ID:
            tags = list(DEFAULT_ART["tags"])
        if not tags and aid == NPC_BASIC_ART_ID:
            tags = list(NPC_BASIC_ART["tags"])
        if not tags:
            tags = ["strike", "guard"]
        arts.append(
            {
                "art_id": aid,
                "name": str(it.get("name") or aid),
                "lore": str(it.get("lore") or ""),
                "tags": tags,
                "axis_bias": dict(it.get("axis_bias") or {}),
            }
        )
    return arts


def moves_for_actor_inventory(
    inventory: list[Any] | None, *, foe_fallback: bool = False
) -> list[dict[str, Any]]:
    arts = arts_from_inventory(inventory)
    if not arts and foe_fallback:
        arts = [dict(NPC_BASIC_ART)]
    seen: set[str] = set()
    out: list[dict[str, Any]] = []
    for art in arts:
        for m in compose_moves_from_art(art):
            mid = str(m.get("move_id") or "")
            if not mid or mid in seen or validate_move(m):
                continue
            seen.add(mid)
            out.append(m)
    return out


def move_catalog() -> list[dict[str, Any]]:
    return compose_moves_from_art(DEFAULT_ART) + compose_moves_from_art(NPC_BASIC_ART)


def move_by_id(move_id: str, catalog: list[dict[str, Any]] | None = None) -> dict[str, Any] | None:
    mid = str(move_id or "").strip()
    for m in catalog or move_catalog():
        if m.get("move_id") == mid:
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


def art_ids_from_inventory(inventory: list[Any] | None) -> list[str]:
    return [a["art_id"] for a in arts_from_inventory(inventory)]


def moves_for_inventory(inventory: list[Any] | None) -> list[dict[str, Any]]:
    return moves_for_actor_inventory(inventory, foe_fallback=False)


def moves_for_art_ids(art_ids: list[str]) -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []
    seen: set[str] = set()
    for aid in art_ids:
        art = (
            dict(DEFAULT_ART)
            if aid == DEFAULT_ART_ID
            else dict(NPC_BASIC_ART)
            if aid == NPC_BASIC_ART_ID
            else {"art_id": aid, "tags": ["strike", "guard"], "axis_bias": {}}
        )
        for m in compose_moves_from_art(art):
            mid = str(m.get("move_id") or "")
            if mid and mid not in seen and not validate_move(m):
                seen.add(mid)
                out.append(m)
    return out


def tag_prompt_block() -> str:
    """注入 LLM：封闭字母表。"""
    lines = ["交锋词条字母表（小招 tags 只能用这些 id）："]
    for k, v in TAG_ALPHABET.items():
        lines.append(f"- {k}: {v}")
    return "\n".join(lines)
