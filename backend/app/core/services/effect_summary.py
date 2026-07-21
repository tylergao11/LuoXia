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
}


def _path_label(path: str, extra: dict[str, str] | None = None) -> str:
    labels = {**_ENGINE_PATH_LABELS, **(extra or {})}
    if path in labels:
        return labels[path]
    if path.startswith("flags."):
        key = path.split(".", 1)[-1]
        return f"心境·{key}"
    if path.startswith("resources."):
        return path.split(".", 1)[-1]
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
    把 state_ops / belief_ops / world_flag_ops 收成玩家可读摘要。
    分组：self / other / others / world
    """
    pid = session.player_id()
    by_actor: dict[str, list[str]] = {}
    path_labels = _pack_labels(session, registry)

    for op in adj.state_ops or []:
        aid = op.actor_id
        label = _path_label(op.path, path_labels)
        if op.path == "location":
            val = _loc_name(session, op.value)
        else:
            val = _fmt_value(op.value)
        if op.op in ("set", "add_resource", "set_flag"):
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

    for bop in adj.belief_ops or []:
        hid = bop.holder_id
        if bop.op == "retract":
            line = f"心念消散：{(bop.proposition or bop.belief_id or '某念')[:40]}"
        elif bop.op == "clear_all":
            line = "心念尽数清空"
        else:
            prop = (bop.proposition or "").strip() or "新的见闻"
            line = f"心生见闻：{prop[:48]}"
        by_actor.setdefault(hid, []).append(line)

    world_lines: list[str] = []
    for k, v in (adj.world_flag_ops or {}).items():
        world_lines.append(f"天下·{k} → {_fmt_value(v)}")

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
        blocks.append("【己身】\n" + "\n".join(f"· {x}" for x in self_lines))
    if other_id and other_lines:
        blocks.append(f"【{other_name}】\n" + "\n".join(f"· {x}" for x in other_lines))
    elif other_id and not other_lines:
        blocks.append(f"【{other_name}】\n· 未见明显状态流转")
    for o in others:
        blocks.append(f"【{o['name']}】\n" + "\n".join(f"· {x}" for x in o["lines"]))
    if world_lines:
        blocks.append("【天下】\n" + "\n".join(f"· {x}" for x in world_lines))

    if not blocks:
        if int(adj.ap_cost or 0) > 0:
            blocks.append(f"【余力】\n· 此番耗费 {adj.ap_cost}")
        else:
            blocks.append("【局势】\n· 暂无可见的状态变化")

    full_text = "\n\n".join(blocks)
    if int(adj.ap_cost or 0) > 0 and "余力" not in full_text:
        full_text += f"\n\n【余力】\n· 此番耗费 {adj.ap_cost}"

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
