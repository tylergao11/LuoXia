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

# MEMORY 前缀冻结预算：只增不改；超出部分进 DYNAMIC，禁止砍头
MEMORY_DIGEST_PREFIX_CHARS = 800
MEMORY_LOG_PREFIX_N = 20


def split_digest_for_prompt(digest: str) -> tuple[str, str]:
    """返回 (MEMORY 前缀, DYNAMIC 溢出)。前缀一旦顶满字节冻结。"""
    d = str(digest or "")
    if len(d) <= MEMORY_DIGEST_PREFIX_CHARS:
        return d, ""
    return d[:MEMORY_DIGEST_PREFIX_CHARS], d[MEMORY_DIGEST_PREFIX_CHARS:]


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
    # memory_digest 走 MEMORY/溢出区，避免 DYNAMIC.flags 重复携带
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


def stable_world_block(session: GameSession) -> str:
    """
    局级固定前缀：背景 + 地图 + **全员**静态人设（不含 state/beliefs/day）。
    不按本轮 actor 裁剪，便于跨 NPC / 跨 tag 共享 DeepSeek 前缀缓存。
    """
    bg = session.background_text or ""
    # 背景整段固定；截断也固定长度，避免每轮变
    if len(bg) > 2000:
        bg = bg[:2000]
    map_nodes = {
        nid: {"name": n.name, "summary": (n.summary or "")[:80]}
        for nid, n in sorted(session.map.nodes.items(), key=lambda x: x[0])
    }
    ids = sorted(session.profiles.keys())
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


def frozen_stable_world_block(session: GameSession) -> str:
    """
    会话级冻结 STABLE：首算写入 graph_meta，之后原样返回。
    中途改 profiles 也不改前缀（防打断缓存）；新开局自然无 fingerprint。
    """
    meta = session.graph_meta
    existing = meta.get("stable_world_fingerprint")
    if isinstance(existing, str) and existing.startswith("### STABLE\n"):
        return existing
    block = stable_world_block(session)
    meta["stable_world_fingerprint"] = block
    return block



def memory_block(session: GameSession, actor_ids: list[str] | None = None) -> str:
    """
    半固定记忆区：digest / llm_memory_log 的前缀冻结视图。
    存储层只 append；此处只取前缀，永不滑窗砍头。
    """
    ids = sorted(set(actor_ids or list(session.profiles.keys())))
    digests = {}
    for aid in ids:
        st = session.states.get(aid)
        if not st:
            continue
        d = (st.flags or {}).get("memory_digest")
        if d:
            prefix, _overflow = split_digest_for_prompt(str(d))
            if prefix:
                digests[aid] = prefix
    mem_log = list(session.graph_meta.get("llm_memory_log") or [])
    log_prefix = mem_log[:MEMORY_LOG_PREFIX_N]
    if not digests and not log_prefix:
        return ""
    payload = {"zone": "MEMORY", "digests": digests, "log": log_prefix}
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
    digest_overflow: dict[str, str] = {}
    for aid in ids:
        st = session.states.get(aid)
        if st:
            states[aid] = compact_state(st)
            raw = (st.flags or {}).get("memory_digest")
            if raw:
                _prefix, overflow = split_digest_for_prompt(str(raw))
                if overflow:
                    digest_overflow[aid] = overflow
        beliefs[aid] = compact_beliefs(session, aid, 8)
    # 差分日志（只增）；滑窗仅影响 DYNAMIC，不碰 MEMORY 前缀
    diff_log = list(session.graph_meta.get("llm_state_diff_log") or [])[-30:]
    mem_log = list(session.graph_meta.get("llm_memory_log") or [])
    mem_log_overflow = mem_log[MEMORY_LOG_PREFIX_N:]
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
    if digest_overflow:
        payload["memory_digest_overflow"] = digest_overflow
    if mem_log_overflow:
        payload["memory_log_overflow"] = mem_log_overflow
    if material is not None:
        payload["current_material"] = material
    # 内容包可拔插：公开倾向摘要进 DYNAMIC
    merged_extra = dict(extra or {})
    try:
        from app.container import get_container

        pack = get_container().registry.get(session.world_id)
        enrich = getattr(pack, "enrich_dynamic_extra", None)
        if callable(enrich):
            merged_extra = enrich(session, ids, merged_extra)
    except Exception:
        pass
    if merged_extra:
        payload["extra"] = merged_extra
    return "### DYNAMIC\n" + dumps_stable(payload)


def build_single_user(
    session: GameSession,
    *,
    actor_ids: list[str],
    material: dict[str, Any] | None = None,
    extra: dict[str, Any] | None = None,
) -> tuple[str, dict[str, Any]]:
    """
    整包单条 user = STABLE(全员冻结) + MEMORY + DYNAMIC。
    新路径优先用 build_threaded_api_messages（多轮 append）。
    """
    stable = frozen_stable_world_block(session)
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
        "stable_roster": "all",
    }
    return text, metrics


def thread_key(kind: str, *parts: str) -> str:
    return kind + ":" + ":".join(str(p) for p in parts)


def get_thread(session: GameSession, key: str) -> dict[str, Any]:
    threads = session.graph_meta.setdefault("llm_threads", {})
    if key not in threads or not isinstance(threads[key], dict):
        threads[key] = {
            "messages": [],  # 不含 system；仅 user/assistant 交替
            "stable_fingerprint": "",
        }
    return threads[key]


def freeze_stable_fingerprint(session: GameSession, key: str, stable: str | None = None) -> str:
    """
    对话线程锁定 STABLE：与会话级 frozen_stable_world_block 对齐。
    若线程已有历史指纹则保留（避免改写首条 user）。
    """
    session_frozen = frozen_stable_world_block(session)
    th = get_thread(session, key)
    if not th.get("stable_fingerprint"):
        th["stable_fingerprint"] = session_frozen
    return str(th["stable_fingerprint"] or session_frozen)


def append_assistant(session: GameSession, key: str, content: str) -> None:
    th = get_thread(session, key)
    msgs: list = th.setdefault("messages", [])
    msgs.append({"role": "assistant", "content": content})
    _trim_thread(th, max_messages=24)


def append_user(session: GameSession, key: str, content: str) -> None:
    th = get_thread(session, key)
    msgs: list = th.setdefault("messages", [])
    msgs.append({"role": "user", "content": content})
    _trim_thread(th, max_messages=24)


def dumps_assistant_json(raw: dict[str, Any]) -> str:
    return json.dumps(raw, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


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


def build_threaded_api_messages(
    session: GameSession,
    *,
    kind: str,
    thread_parts: list[str],
    actor_ids: list[str],
    material: dict[str, Any] | None = None,
    extra: dict[str, Any] | None = None,
) -> tuple[list[dict[str, str]], dict[str, Any]]:
    """
    通用多轮：首包 STABLE(全员冻结)+MEMORY+DYNAMIC，之后只 append DYNAMIC(+MEMORY 提示)。
    kind/thread_parts → llm_threads 键，例如 intend:lin_su、adj:world_evolve。
    """
    key = thread_key(kind, *thread_parts)
    th = get_thread(session, key)
    ids = sorted(set(actor_ids))
    frozen = freeze_stable_fingerprint(session, key)
    dyn = dynamic_turn_block(
        session, actor_ids=ids, material=material, extra=extra
    )
    mem = memory_block(session, ids)

    metrics: dict[str, Any] = {
        "stable_len": len(frozen),
        "memory_len": len(mem),
        "dynamic_len": len(dyn),
        "thread_key": key,
        "expected_hit_mode": "multi_turn_append",
        "stable_roster": "all",
        "actor_ids": ids,
    }

    if not th["messages"]:
        parts = [frozen]
        if mem:
            parts.append(mem)
        parts.append(dyn)
        first_user = "\n\n".join(parts)
        th["messages"] = [{"role": "user", "content": first_user}]
        metrics["messages_count"] = 1
        metrics["user_len"] = len(first_user)
        return list(th["messages"]), metrics

    follow = dyn
    if mem:
        follow = dyn + "\n\n" + mem
    th["messages"].append({"role": "user", "content": follow})
    _trim_thread(th)
    metrics["messages_count"] = len(th["messages"])
    metrics["user_len"] = len(follow)
    metrics["stable_len"] = len(th["messages"][0]["content"]) if th["messages"] else 0
    return list(th["messages"]), metrics


def build_dialogue_api_messages(
    session: GameSession,
    *,
    speaker_id: str,
    player_utterance: str,
    listener_id: str,
) -> tuple[list[dict[str, str]], dict[str, Any]]:
    """对话多轮：dlg:{speaker} 线程。"""
    actor_ids = sorted({speaker_id, listener_id, session.player_id()})
    location = None
    st = session.states.get(speaker_id)
    if st is not None:
        location = st.location
    return build_threaded_api_messages(
        session,
        kind="dlg",
        thread_parts=[speaker_id],
        actor_ids=actor_ids,
        material={
            "type": "dialogue",
            "player_utterance": player_utterance,
            "speaker_id": speaker_id,
            "listener_id": listener_id,
            "location": location,
        },
        extra={"speaker_id": speaker_id, "listener_id": listener_id},
    )
