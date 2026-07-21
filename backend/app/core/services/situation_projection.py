"""引擎通用情境行投影：states[player] → 可读 rows（前端只渲染）。"""

from __future__ import annotations

from typing import Any

from app.core.domain.models import GameSession

_RESOURCE_LABEL = {
    "spirit_stones": "灵石",
    "grain": "粮米",
    "contribution": "贡献",
}

_FLAG_LABEL = {
    "expelled": "是否被逐",
    "dead": "已故",
    "trusts_player": "托付于你",
    "trust_player": "对你信任",
    "investigating_curse": "追查邪咒",
    "heard_letter": "闻得密信",
}


def _fmt_cultivation(c: dict[str, Any] | None) -> str:
    if not c or not isinstance(c, dict):
        return "深浅未测"
    realm = c.get("realm") or "深浅未测"
    layer = c.get("layer")
    layer_s = f"·第{layer}层" if layer is not None else ""
    talent = "（根骨不凡）" if c.get("talent") == "high" else ""
    return f"{realm}{layer_s}{talent}"


def _fmt_inventory(inv: list[Any] | None) -> str:
    if not inv:
        return "两袖清风"
    parts: list[str] = []
    for i in inv:
        if not isinstance(i, dict):
            continue
        n = i.get("name") or i.get("item_id") or "异物"
        q = i.get("qty")
        parts.append(f"{n}×{q}" if q is not None and q != 1 else str(n))
    return "、".join(parts) if parts else "两袖清风"


def project_situation_rows(
    session: GameSession,
    *,
    path_labels: dict[str, str] | None = None,
) -> list[dict[str, str]]:
    """
    从真相字典 states[player] 投影情境行。
    path_labels：WorldPack.effect_path_labels 可选补充。
    """
    pid = session.player_id()
    st = session.states.get(pid)
    prof = session.profiles.get(pid)
    if not st:
        return []
    labels = dict(path_labels or {})
    rows: list[dict[str, str]] = []

    title = (st.identity or {}).get("title") or (prof.title if prof else "") or ""
    if title:
        rows.append({"key": "identity", "label": "身份", "value": str(title)})

    loc = st.location
    if loc:
        node = session.map.nodes.get(str(loc))
        loc_name = node.name if node else str(loc)
        rows.append({"key": "location", "label": "所在", "value": loc_name})

    if st.cultivation:
        rows.append(
            {
                "key": "cultivation",
                "label": "修为",
                "value": _fmt_cultivation(dict(st.cultivation or {})),
            }
        )

    for k, v in (st.resources or {}).items():
        if v is None or v == "":
            continue
        lab = labels.get(f"resources.{k}") or _RESOURCE_LABEL.get(k) or str(k)
        rows.append({"key": f"res_{k}", "label": lab, "value": str(v)})

    inv_s = _fmt_inventory(list(st.inventory or []))
    if inv_s and inv_s != "两袖清风":
        rows.append({"key": "inventory", "label": "随身", "value": inv_s})
    elif inv_s == "两袖清风":
        rows.append({"key": "inventory", "label": "随身", "value": inv_s})

    for k, v in (st.flags or {}).items():
        sk = str(k)
        if sk.startswith("_") or sk == "memory_digest":
            continue
        lab = labels.get(f"flags.{sk}") or _FLAG_LABEL.get(sk)
        if not lab:
            # 未登记英文内部键不进情境
            if sk.isascii() and "_" in sk:
                continue
            lab = f"心境·{sk}"
        if v is True:
            val = "是"
        elif v is False:
            val = "否"
        else:
            val = str(v)
        rows.append({"key": f"flag_{sk}", "label": lab, "value": val})

    return rows
