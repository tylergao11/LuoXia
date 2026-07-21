"""
按 actor 分仓的对白仓 = 真相字典键 `session.dialogue`。

权威职责（只这些）：
- player / npc / sys 文本（说了什么）
- event_card：事件封条引用（event_id + 题面；正文权威在 events）
- effect：本轮机械局势投影一行（非见闻复述）

禁止：见闻命题、整轮裁决摘要、发明世界事实。
旧存档若仍在 graph_meta.chat_by_actor，首次访问时迁入 dialogue。
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any
from uuid import uuid4

from app.core.domain.models import GameSession

SCENE_KEY = "_scene"
MAX_MESSAGES_PER_THREAD = 80
ALLOWED_ROLES = frozenset(
    {"player", "npc", "sys", "event_card", "event_body", "effect"}
)
LEGACY_META_KEY = "chat_by_actor"


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _migrate_legacy(session: GameSession) -> None:
    """graph_meta.chat_by_actor → session.dialogue（合并空线程后删除旧键）。"""
    meta = session.graph_meta if isinstance(session.graph_meta, dict) else {}
    legacy = meta.get(LEGACY_META_KEY)
    if not isinstance(session.dialogue, dict):
        session.dialogue = {}
    if isinstance(legacy, dict) and legacy:
        for k, th in legacy.items():
            cur = session.dialogue.get(k)
            if not isinstance(cur, dict) or not (cur.get("messages") or []):
                session.dialogue[str(k)] = th if isinstance(th, dict) else {"actor_id": k, "messages": []}
        meta.pop(LEGACY_META_KEY, None)
        session.graph_meta = meta
    elif LEGACY_META_KEY in meta:
        meta.pop(LEGACY_META_KEY, None)
        session.graph_meta = meta


def chat_store(session: GameSession) -> dict[str, Any]:
    """真相字典 dialogue 本体（可写）。"""
    _migrate_legacy(session)
    if not isinstance(session.dialogue, dict):
        session.dialogue = {}
    return session.dialogue


def ensure_thread(session: GameSession, actor_id: str) -> dict[str, Any]:
    aid = str(actor_id or SCENE_KEY)
    store = chat_store(session)
    th = store.get(aid)
    if not isinstance(th, dict):
        th = {"actor_id": aid, "updated_day": session.day, "messages": []}
        store[aid] = th
    th.setdefault("actor_id", aid)
    msgs = th.get("messages")
    if not isinstance(msgs, list):
        th["messages"] = []
    return th


def get_messages(session: GameSession, actor_id: str) -> list[dict[str, Any]]:
    th = ensure_thread(session, actor_id)
    return list(th.get("messages") or [])


def trim_thread(th: dict[str, Any], *, max_messages: int = MAX_MESSAGES_PER_THREAD) -> None:
    msgs = th.get("messages") or []
    if len(msgs) > max_messages:
        th["messages"] = list(msgs[-max_messages:])


def append_messages(
    session: GameSession,
    actor_id: str,
    *items: dict[str, Any],
) -> list[dict[str, Any]]:
    """追加到 dialogue 线程；非法 role 丢弃。"""
    th = ensure_thread(session, actor_id)
    msgs: list = th.setdefault("messages", [])
    written: list[dict[str, Any]] = []
    for raw in items:
        if not raw:
            continue
        msg = dict(raw)
        role = str(msg.get("role") or "")
        if role not in ALLOWED_ROLES:
            continue
        msg.setdefault("id", f"m_{uuid4().hex[:12]}")
        msg.setdefault("day", session.day)
        msg.setdefault("ts", _now_iso())
        msgs.append(msg)
        written.append(msg)
    th["updated_day"] = session.day
    trim_thread(th)
    return written


def append_sys(session: GameSession, text: str, *, actor_id: str = SCENE_KEY) -> dict[str, Any]:
    written = append_messages(
        session,
        actor_id,
        {"role": "sys", "text": str(text or "").strip()},
    )
    return written[0] if written else {}


def record_talk_turn(
    session: GameSession,
    *,
    npc_id: str,
    player_text: str,
    npc_text: str,
    events: list[Any] | None = None,
    effects: dict[str, Any] | None = None,
) -> None:
    """
    一次谈话写入 dialogue（该 NPC 线程）：
    - player / npc 对白（对白权威）
    - 本轮新事件 → sealed event_card（只引用 events）
    - 机械局势 → 至多一条 effect（投影，非见闻）
    """
    aid = str(npc_id or "").strip()
    if not aid:
        return
    batch: list[dict[str, Any]] = []
    pt = str(player_text or "").strip()
    if pt:
        batch.append({"role": "player", "text": pt})
    nt = str(npc_text or "").strip()
    batch.append({"role": "npc", "text": nt or "（对方未答话）"})
    for ev in events or []:
        if hasattr(ev, "model_dump"):
            d = ev.model_dump(mode="json")
        elif isinstance(ev, dict):
            d = ev
        else:
            continue
        eid = d.get("event_id")
        if not eid:
            continue
        batch.append(
            {
                "role": "event_card",
                "event_id": eid,
                "headline": d.get("card_headline") or d.get("title") or "旧事",
                "sealed": True,
                "day": d.get("day") or session.day,
                "kind": d.get("kind"),
                "severity": d.get("severity"),
            }
        )
    fx = effects if isinstance(effects, dict) else {}
    fx_text = str(fx.get("full_text") or "").strip()
    if fx_text and fx.get("has_any", True):
        batch.append({"role": "effect", "text": fx_text, "turn_effect": True})
    if batch:
        append_messages(session, aid, *batch)


def seed_scene_guide(session: GameSession, text: str) -> None:
    """开局须知只进 _scene。"""
    body = str(text or "").strip()
    if not body:
        return
    th = ensure_thread(session, SCENE_KEY)
    for m in th.get("messages") or []:
        if m.get("role") == "sys" and body[:40] in str(m.get("text") or ""):
            return
    append_sys(session, body, actor_id=SCENE_KEY)


def export_store(session: GameSession) -> dict[str, Any]:
    """SessionView 投影：dialogue → chat_by_actor DTO。"""
    store = chat_store(session)
    out: dict[str, Any] = {}
    for k, th in store.items():
        if not isinstance(th, dict):
            continue
        out[str(k)] = {
            "actor_id": th.get("actor_id") or k,
            "updated_day": th.get("updated_day"),
            "messages": list(th.get("messages") or []),
        }
    return out


def transcript_for_llm(
    session: GameSession,
    actor_id: str,
    *,
    limit: int = 12,
) -> list[dict[str, str]]:
    """近 N 条 player/npc，供 DYNAMIC。"""
    rows: list[dict[str, str]] = []
    for m in get_messages(session, actor_id):
        role = m.get("role")
        if role not in ("player", "npc"):
            continue
        text = str(m.get("text") or "").strip()
        if not text:
            continue
        rows.append({"role": "player" if role == "player" else "npc", "text": text})
    return rows[-limit:]
