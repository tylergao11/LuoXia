"""
DeepSeek 磁盘 KV 缓存友好的 prompt 块构造。

匹配规则（官方）：后续请求须与已落盘的 cache prefix unit **整段一致**。
多轮可命中：A+B 后接 A+B+C。
因此：
  - 固定区：字节级稳定（背景/地图/人设）
  - 动态区：只 append，不改历史消息
  - 本轮材料永远在最新 user 末尾
"""

from __future__ import annotations

import json
from typing import Any

from app.core.domain.models import GameSession


def compact_state(st: Any) -> dict[str, Any]:
    if st is None:
        return {}
    if hasattr(st, "model_dump"):
        d = st.model_dump()
    elif isinstance(st, dict):
        d = st
    else:
        return {}
    flags = d.get("flags") or {}
    # memory_digest 走 MEMORY 区，避免 DYNAMIC 每轮带着大段旧文
    flags_out = {k: v for k, v in flags.items() if k != "memory_digest"}
    return {
        "alive": d.get("alive", True),
        "location": d.get("location"),
        "identity": d.get("identity") or {},
        "cultivation": d.get("cultivation") or {},
        "resources": d.get("resources") or {},
        "flags": flags_out,
        "inventory": (d.get("inventory") or [])[:8],
    }


def compact_beliefs(session: GameSession, actor_id: str, limit: int = 8) -> list[dict]:
    out = []
    for b in (session.beliefs.get(actor_id) or [])[:limit]:
        out.append(
            {
                "belief_id": b.belief_id,
                "proposition": b.proposition,
                "source": b.source.value if hasattr(b.source, "value") else b.source,
                "truth_rel": b.truth_rel.value if hasattr(b.truth_rel, "value") else b.truth_rel,
                "confidence": b.confidence,
                "day": b.day,
            }
        )
    return out


def dumps_stable(obj: Any) -> str:
    """稳定序列化：排序 key，保证相同语义 → 相同字节。"""
    return json.dumps(obj, ensure_ascii=False, sort_keys=True, separators=(",", ":"), default=str)


def static_profile(session: GameSession, actor_id: str) -> dict[str, Any] | None:
    prof = session.profiles.get(actor_id)
    if not prof:
        return None
    return {
        "id": prof.id,
        "name": prof.display_name,
        "title": prof.title or "",
        "personality": (prof.personality or "")[:280],
        "drives": (prof.drives or "")[:200],
        "tags": list(prof.tags or []),
        "can_proclaim": bool(prof.can_proclaim),
        "default_location": prof.default_location,
        "is_player": bool(prof.is_player),
        "drive_priority": int(prof.drive_priority or 0),
    }


def stable_world_block(session: GameSession, actor_ids: list[str] | None = None) -> str:
    """局级固定前缀：背景 + 地图 + 静态人设（不含 state/beliefs/day）。"""
    bg = session.background_text or ""
    # 背景整段固定；截断也固定长度，避免每轮变
    if len(bg) > 2000:
        bg = bg[:2000]
    map_nodes = {
        nid: {"name": n.name, "summary": (n.summary or "")[:80]}
        for nid, n in sorted(session.map.nodes.items(), key=lambda x: x[0])
    }
    if actor_ids is None:
        ids = sorted(session.profiles.keys())
    else:
        ids = sorted(set(actor_ids))
    profiles = []
    for aid in ids:
        p = static_profile(session, aid)
        if p:
            profiles.append(p)
    payload = {
        "zone": "STABLE",
        "world_id": session.world_id,
        "background": bg,
        "map": map_nodes,
        "profiles": profiles,
    }
    return "### STABLE\n" + dumps_stable(payload)


def memory_block(session: GameSession, actor_ids: list[str] | None = None) -> str:
    """
    半固定记忆区：只读各 actor flags.memory_digest 与 graph_meta 追加日志。
    注意：digest 若被整段重写会打断缓存；压缩服务应改为 append。
    """
    ids = sorted(set(actor_ids or list(session.profiles.keys())))
    digests = {}
    for aid in ids:
        st = session.states.get(aid)
        if not st:
            continue
        d = (st.flags or {}).get("memory_digest")
        if d:
            digests[aid] = str(d)[:800]
    mem_log = list(session.graph_meta.get("llm_memory_log") or [])
    if not digests and not mem_log:
        return ""
    payload = {"zone": "MEMORY", "digests": digests, "log": mem_log[-20:]}
    return "### MEMORY\n" + dumps_stable(payload)


def dynamic_turn_block(
    session: GameSession,
    *,
    actor_ids: list[str],
    material: dict[str, Any] | None = None,
    extra: dict[str, Any] | None = None,
) -> str:
    """本轮动态：day/ap/flags/states/beliefs/material。单独成块，不进 STABLE。"""
    ids = sorted(set(actor_ids))
    states = {}
    beliefs = {}
    for aid in ids:
        st = session.states.get(aid)
        if st:
            states[aid] = compact_state(st)
        beliefs[aid] = compact_beliefs(session, aid, 8)
    # 差分日志（只增）
    diff_log = list(session.graph_meta.get("llm_state_diff_log") or [])[-30:]
    payload: dict[str, Any] = {
        "zone": "DYNAMIC",
        "day": session.day,
        "remaining_ap": session.ap,
        "world_flags": session.world_flags or {},
        "states": states,
        "beliefs": beliefs,
        "state_diff_log": diff_log,
        "player_id": session.player_id(),
    }
    if material is not None:
        payload["current_material"] = material
    if extra:
        payload["extra"] = extra
    return "### DYNAMIC\n" + dumps_stable(payload)


def build_single_user(
    session: GameSession,
    *,
    actor_ids: list[str],
    material: dict[str, Any] | None = None,
    extra: dict[str, Any] | None = None,
) -> tuple[str, dict[str, Any]]:
    """
    单轮 user = STABLE + MEMORY + DYNAMIC（顺序固定，利于公共前缀）。
    返回 (user_text, metrics)。
    """
    stable = stable_world_block(session, actor_ids)
    mem = memory_block(session, actor_ids)
    dyn = dynamic_turn_block(
        session, actor_ids=actor_ids, material=material, extra=extra
    )
    parts = [stable]
    if mem:
        parts.append(mem)
    parts.append(dyn)
    text = "\n\n".join(parts)
    metrics = {
        "stable_len": len(stable),
        "memory_len": len(mem),
        "dynamic_len": len(dyn),
        "user_len": len(text),
        "expected_hit_mode": "stable_user",
        "actor_ids": actor_ids,
    }
    return text, metrics


def thread_key(kind: str, *parts: str) -> str:
    return kind + ":" + ":".join(parts)


def get_thread(session: GameSession, key: str) -> dict[str, Any]:
    threads = session.graph_meta.setdefault("llm_threads", {})
    if key not in threads or not isinstance(threads[key], dict):
        threads[key] = {
            "messages": [],  # 不含 system；仅 user/assistant 交替
            "stable_fingerprint": "",
        }
    return threads[key]


def freeze_stable_fingerprint(session: GameSession, key: str, stable: str) -> str:
    """首轮锁定 stable；之后不得改写（否则打断多轮前缀）。"""
    th = get_thread(session, key)
    if not th.get("stable_fingerprint"):
        th["stable_fingerprint"] = stable
    return th["stable_fingerprint"]


def append_assistant(session: GameSession, key: str, content: str) -> None:
    th = get_thread(session, key)
    msgs: list = th.setdefault("messages", [])
    msgs.append({"role": "assistant", "content": content})
    # 控制长度：过多则截断头部 user/assistant 对（会降命中，但防爆）
    _trim_thread(th, max_messages=24)


def append_user(session: GameSession, key: str, content: str) -> None:
    th = get_thread(session, key)
    msgs: list = th.setdefault("messages", [])
    msgs.append({"role": "user", "content": content})
    _trim_thread(th, max_messages=24)


def _trim_thread(th: dict[str, Any], max_messages: int = 24) -> None:
    msgs = th.get("messages") or []
    if len(msgs) <= max_messages:
        return
    # 保留第一条 user（含 STABLE 的完整首包）+ 最近若干条
    first = msgs[0]
    tail = msgs[-(max_messages - 1) :]
    if first in tail:
        th["messages"] = tail
    else:
        th["messages"] = [first] + tail


def build_dialogue_api_messages(
    session: GameSession,
    *,
    speaker_id: str,
    player_utterance: str,
    listener_id: str,
) -> tuple[list[dict[str, str]], dict[str, Any]]:
    """
    对话多轮：对齐 DeepSeek Example 1。
    首轮 user = STABLE+MEMORY+DYNAMIC(含本句)
    之后只 append assistant + 新 user(DYNAMIC+本句)，不改历史。
    """
    key = thread_key("dlg", speaker_id)
    th = get_thread(session, key)
    actor_ids = sorted({speaker_id, listener_id, session.player_id()})
    stable = stable_world_block(session, actor_ids)
    # 锁定首包 stable 指纹
    frozen = freeze_stable_fingerprint(session, key, stable)

    material = {
        "type": "dialogue",
        "player_utterance": player_utterance,
        "speaker_id": speaker_id,
        "listener_id": listener_id,
        "location": (session.states.get(speaker_id).location if session.states.get(speaker_id) else None),
    }
    dyn = dynamic_turn_block(
        session,
        actor_ids=actor_ids,
        material=material,
        extra={"speaker_id": speaker_id, "listener_id": listener_id},
    )
    mem = memory_block(session, actor_ids)

    metrics: dict[str, Any] = {
        "stable_len": len(frozen),
        "memory_len": len(mem),
        "dynamic_len": len(dyn),
        "thread_key": key,
        "expected_hit_mode": "multi_turn_append",
    }

    if not th["messages"]:
        # 首轮：整包 user（stable 必须与后续请求中「历史第一条」完全一致）
        parts = [frozen]
        if mem:
            parts.append(mem)
        parts.append(dyn)
        first_user = "\n\n".join(parts)
        th["messages"] = [{"role": "user", "content": first_user}]
        metrics["messages_count"] = 1
        metrics["user_len"] = len(first_user)
        return list(th["messages"]), metrics

    # 后续轮：仅追加 DYNAMIC + 本句（历史 messages 原样保留 → 前缀单元可整段命中）
    follow = dyn
    if mem:
        # 记忆若变了，只放本轮动态里提示，避免改第一条
        follow = dyn + "\n\n" + mem
    th["messages"].append({"role": "user", "content": follow})
    _trim_thread(th)
    metrics["messages_count"] = len(th["messages"])
    metrics["user_len"] = len(follow)
    metrics["stable_len"] = len(th["messages"][0]["content"]) if th["messages"] else 0
    return list(th["messages"]), metrics
