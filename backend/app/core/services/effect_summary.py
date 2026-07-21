from __future__ import annotations

from typing import Any

from app.core.domain.models import AdjudicationResult, GameSession

# 引擎通用路径标签（中性）；内容专有标签经 WorldPack.effect_path_labels
_ENGINE_PATH_LABELS = {
    "alive": "生死",
    "location": "所在",
    "body.wounded": "伤势",
    "flags.expelled": "是否被逐",
    "flags.dead": "已故",
    "identity.title": "身份",
    "inventory": "随身",
}


def _fmt_item(v: Any) -> str:
    if isinstance(v, list):
        parts = [_fmt_item(x) for x in v]
        return "、".join(p for p in parts if p) or "无"
    if isinstance(v, dict):
        name = v.get("name") or v.get("item_id") or "异物"
        try:
            qty = int(v.get("qty") or 1)
        except (TypeError, ValueError):
            qty = 1
        return f"{name}×{qty}" if qty != 1 else str(name)
    return _fmt_value(v)


# 引擎书签：可写权威，但绝不进玩家可见「局势」文案
_INTERNAL_WORLD_FLAGS = frozenset(
    {
        "fired_clues",
        "map_unlocked",
        "seal_mountain_noted",
        "countdown_ping_10",
        "countdown_ping_3",
        "crisis_fired",
        "crisis_averted_noted",
    }
)


def _is_internal_path(path: str) -> bool:
    """内部计数/引擎书签，永不进玩家可见局势文案。"""
    p = (path or "").strip()
    if not p:
        return True
    key = p.split(".", 1)[-1] if "." in p else p
    if key.startswith("_"):
        return True
    if key in _INTERNAL_WORLD_FLAGS:
        return True
    low = key.lower()
    if low.startswith("talk_count") or "_talk_count" in low:
        return True
    if low.startswith("met_") or low.startswith("visited_") or low.startswith("sim_"):
        return True
    if low.startswith("countdown_ping"):
        return True
    if low.startswith("first_") or low.endswith("_noted") or low.endswith("_fired"):
        return True
    return False


def _is_internal_world_flag(key: str) -> bool:
    k = str(key or "").strip()
    if not k or k.startswith("_"):
        return True
    if k in _INTERNAL_WORLD_FLAGS:
        return True
    low = k.lower()
    if low.startswith("countdown_ping") or low.endswith("_noted") or low.endswith("_fired"):
        return True
    if low in ("fired_clues", "map_unlocked", "seal_mountain_noted"):
        return True
    return False


def _path_label(path: str, extra: dict[str, str] | None = None) -> str:
    if _is_internal_path(path):
        return ""
    labels = {**_ENGINE_PATH_LABELS, **(extra or {})}
    if path in labels:
        return labels[path]
    if path.startswith("flags."):
        key = path.split(".", 1)[-1]
        zh = {
            "heard_letter": "闻得密信之事",
            "expelled": "是否被逐",
            "trust": "信任",
            "trust_player": "对你的信任",
            "trusts_player": "是否托付于你",
            "dead": "已故",
            "investigating_curse": "追查邪咒",
            "evidence_level": "线索积累",
            "ally_player": "与你同盟",
        }.get(key)
        if zh:
            return zh
        # 未登记的英文内部键：不进玩家局势
        if key.isascii() and "_" in key:
            return ""
        return f"心境·{key}"
    if path.startswith("resources."):
        rkey = path.split(".", 1)[-1]
        return {"spirit_stones": "灵石"}.get(rkey, rkey)
    if path.startswith("cultivation."):
        return f"修为·{path.split('.', 1)[-1]}"
    if path.startswith("body."):
        return f"身躯·{path.split('.', 1)[-1]}"
    if path.startswith("identity."):
        return f"身份·{path.split('.', 1)[-1]}"
    return path


def _fmt_value(v: Any) -> str:
    if v is True:
        return "是"
    if v is False:
        return "否"
    if v is None:
        return "无"
    if isinstance(v, float):
        return f"{v:g}"
    return str(v)


def _actor_name(session: GameSession, actor_id: str) -> str:
    if actor_id == session.player_id():
        return "你"
    prof = session.profiles.get(actor_id)
    return prof.display_name if prof else actor_id


def _loc_name(session: GameSession, loc_id: Any) -> str:
    if not loc_id:
        return "未知"
    node = session.map.nodes.get(str(loc_id))
    return node.name if node else str(loc_id)


def _pack_labels(session: GameSession, registry: Any | None) -> dict[str, str]:
    if registry is None:
        return {}
    try:
        pack = registry.get(session.world_id)
        fn = getattr(pack, "effect_path_labels", None)
        if callable(fn):
            return dict(fn() or {})
    except Exception:
        pass
    return {}


def summarize_adjudication(
    session: GameSession,
    adj: AdjudicationResult,
    *,
    focus_other_id: str | None = None,
    registry: Any | None = None,
) -> dict[str, Any]:
    """
    本轮「机械局势」——唯一职责：把 state_ops / 公开 world_flag_ops 收成短文。

    真相边界（勿再写反）：
    - 见闻 / 情报 → session.beliefs，UI 走见闻簿投影；**禁止**在此复述 belief_ops
    - 场面叙事 → events[].card_body；**禁止**把本摘要贴进每张事件卡
    - 本函数产出为 turn 级投影（dialogue effect / ActionResult.effects），不按事件复制
    """
    pid = session.player_id()
    by_actor: dict[str, list[str]] = {}
    path_labels = _pack_labels(session, registry)

    for op in adj.state_ops or []:
        if _is_internal_path(op.path):
            continue
        aid = op.actor_id
        label = _path_label(op.path, path_labels)
        if not label:
            continue
        if op.path == "location":
            val = _loc_name(session, op.value)
        elif op.path == "inventory" or str(op.path).endswith(".inventory"):
            val = _fmt_item(op.value)
        else:
            val = _fmt_value(op.value)
        if op.path == "inventory" or str(op.path).endswith(".inventory"):
            if op.op == "add" or (op.op == "set" and isinstance(op.value, dict)):
                line = f"获物·{val}"
            elif op.op == "remove":
                line = f"失物·{val}"
            elif op.op == "set":
                line = f"随身 → {val}"
            else:
                line = f"随身 → {val}"
        elif op.op in ("set", "add_resource", "set_flag"):
            if op.op == "add_resource" or (op.op == "add"):
                line = f"{label} {val if str(val).startswith(('+','-')) else '+'+str(val)}"
            else:
                line = f"{label} → {val}"
        elif op.op == "add":
            line = f"{label} {val if str(val).startswith(('+','-')) else '+'+str(val)}"
        elif op.op == "remove":
            line = f"{label} 减 {val}"
        elif op.op == "delete_key":
            line = f"{label} 消散"
        else:
            line = f"{label} → {val}"
        by_actor.setdefault(aid, []).append(line)

    world_lines: list[str] = []
    for k, v in (adj.world_flag_ops or {}).items():
        if _is_internal_world_flag(k):
            continue
        if isinstance(v, (list, dict)):
            continue
        label = {
            "xuanyin_countdown": "劫数余日",
            "seal_mountain": "封山",
            "sect_at_brink": "宗门危局",
            "letter_exposed": "假信半公开",
            "blood_curse_planted": "血咒已种",
            "blood_curse_disarmed": "血咒已解",
            "sect_stabilized": "宗门稍安",
        }.get(k)
        if not label:
            continue
        world_lines.append(f"{label} → {_fmt_value(v)}")

    self_lines = list(by_actor.get(pid) or [])
    other_id = focus_other_id
    other_lines: list[str] = []
    other_name = ""
    if other_id:
        other_lines = list(by_actor.get(other_id) or [])
        other_name = _actor_name(session, other_id)

    others: list[dict[str, Any]] = []
    for aid, lines in by_actor.items():
        if aid == pid:
            continue
        if other_id and aid == other_id:
            continue
        others.append({"id": aid, "name": _actor_name(session, aid), "lines": lines})

    blocks: list[str] = []
    if self_lines:
        blocks.append("己身：" + "；".join(self_lines))
    if other_id and other_lines:
        blocks.append(f"{other_name}：" + "；".join(other_lines))
    for o in others:
        if o["lines"]:
            blocks.append(f"{o['name']}：" + "；".join(o["lines"]))
    if world_lines:
        blocks.append("天下：" + "；".join(world_lines))

    full_text = "\n".join(blocks)

    return {
        "self_lines": self_lines,
        "other_id": other_id or "",
        "other_name": other_name,
        "other_lines": other_lines,
        "others": others,
        "world_lines": world_lines,
        "ap_cost": int(adj.ap_cost or 0),
        "full_text": full_text,
        "has_any": bool(self_lines or other_lines or others or world_lines),
    }
