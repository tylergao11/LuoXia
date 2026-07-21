"""交锋遭遇：点选耗气 → 双确（PVE 自动对方）→ 对拼结算 → ContentPacket。"""

from __future__ import annotations

import random
import uuid
from typing import Any

from app.core.domain.enums import EventKind, GamePhase, Severity
from app.core.domain.models import ActionRequest, ActionResult, GameSession, WorldEvent
from app.core.ports.world_pack import WorldPack
from app.core.services.content_packet import apply_packet, empty_packet
from app.core.services.state_applier import StateApplier

ENCOUNTER_FLAG = "active_encounter"
MAX_HANDS = 3


def handle_encounter(
    session: GameSession,
    req: ActionRequest,
    pack: WorldPack,
    applier: StateApplier,
) -> ActionResult:
    if session.phase != GamePhase.PLAYER_TURN:
        return ActionResult(
            ok=False,
            message="此刻不可交锋",
            session=session,
            error_code="BAD_PHASE",
        )

    op = str((req.payload or {}).get("op") or "start").strip().lower()
    if op == "start":
        return _start(session, req, pack, applier)
    if op == "pick":
        return _pick(session, req, pack)
    if op == "confirm":
        return _confirm(session, req, pack, applier)
    if op == "cancel":
        return _cancel(session, applier)
    return ActionResult(
        ok=False,
        message=f"未知交锋操作: {op}",
        session=session,
        error_code="BAD_OP",
    )


def _player_moves(session: GameSession, pack: WorldPack) -> list[dict[str, Any]]:
    fn = getattr(pack, "encounter_moves_for", None)
    if callable(fn):
        return list(fn(session, session.player_id()) or [])
    return list(pack.encounter_move_catalog() or [])


def _foe_moves(session: GameSession, pack: WorldPack, foe_id: str) -> list[dict[str, Any]]:
    fn = getattr(pack, "encounter_moves_for", None)
    if callable(fn):
        return list(fn(session, foe_id) or [])
    return list(pack.encounter_move_catalog() or [])


def project_encounter_view(session: GameSession, pack: WorldPack | None) -> dict[str, Any] | None:
    raw = (session.world_flags or {}).get(ENCOUNTER_FLAG)
    if not isinstance(raw, dict) or raw.get("kind") != "duel":
        return None
    pid = session.player_id()
    foe_id = str(raw.get("foe_id") or "")
    self_name = (
        session.profiles[pid].display_name if pid in session.profiles else "客卿"
    )
    foe_name = (
        session.profiles[foe_id].display_name if foe_id in session.profiles else "对手"
    )
    catalog = _player_moves(session, pack) if pack is not None else []
    art_names: list[str] = []
    st = session.states.get(pid)
    for it in (st.inventory if st else None) or []:
        if isinstance(it, dict) and str(it.get("kind") or "") in ("gongfa", "art", "功法"):
            n = str(it.get("name") or "").strip()
            if n and n not in art_names:
                art_names.append(n)
    return {
        "kind": "duel",
        "phase": str(raw.get("phase") or "pick"),
        "foe_id": foe_id,
        "foe_name": foe_name,
        "self_name": self_name,
        "qi_max": int(raw.get("qi_max") or 0),
        "qi_spent": _spent_qi(raw.get("player_moves") or [], catalog),
        "picked": list(raw.get("player_moves") or []),
        "moves": catalog,
        "arts": art_names,
        "stage_module": "duel",
        "self_mark": (self_name or "我")[:1],
        "foe_mark": (foe_name or "敌")[:1],
    }


def _start(
    session: GameSession,
    req: ActionRequest,
    pack: WorldPack,
    applier: StateApplier,
) -> ActionResult:
    if (session.world_flags or {}).get(ENCOUNTER_FLAG):
        return ActionResult(
            ok=False,
            message="已在交锋之中",
            session=session,
            error_code="BUSY",
        )

    pid = session.player_id()
    foe_id = str(req.target_id or (req.payload or {}).get("foe_id") or "").strip()
    if not foe_id or foe_id == pid:
        return ActionResult(
            ok=False,
            message="未指定对手",
            session=session,
            error_code="NO_FOE",
        )
    if foe_id not in session.profiles or foe_id not in session.states:
        return ActionResult(
            ok=False,
            message="对手不在此界",
            session=session,
            error_code="NO_FOE",
        )

    p_st = session.states[pid]
    f_st = session.states[foe_id]
    if not p_st.alive:
        return ActionResult(ok=False, message="你已无法动手", session=session, error_code="DEAD")
    if not f_st.alive:
        return ActionResult(ok=False, message="对方已故", session=session, error_code="FOE_DEAD")
    if (p_st.location or "") != (f_st.location or ""):
        return ActionResult(
            ok=False,
            message="对方不在此处",
            session=session,
            error_code="NOT_HERE",
        )

    # 旧存档无默认功法：开战时补发客途吐纳诀
    grant_note = ""
    ensure = getattr(pack, "encounter_ensure_default_art_packet", None)
    if callable(ensure):
        packet = ensure(session) or {}
        if packet:
            apply_packet(session, packet, applier=applier)
            grant_note = "（已执出客途吐纳诀）"

    catalog = _player_moves(session, pack)
    if not catalog:
        return ActionResult(
            ok=False,
            message="未携功法，无招可出",
            session=session,
            error_code="NO_ART",
        )
    foe_catalog = _foe_moves(session, pack, foe_id)
    if not foe_catalog:
        return ActionResult(
            ok=False,
            message="对方无招可对",
            session=session,
            error_code="FOE_NO_ART",
        )

    qi_max = int(pack.encounter_qi_cap(dict(p_st.cultivation or {})))
    foe_qi_max = int(pack.encounter_qi_cap(dict(f_st.cultivation or {})))
    blob = {
        "kind": "duel",
        "phase": "pick",
        "foe_id": foe_id,
        "qi_max": qi_max,
        "foe_qi_max": foe_qi_max,
        "player_moves": [],
        "foe_moves": [],
        "player_amp": float(pack.encounter_cultivation_amp(dict(p_st.cultivation or {}))),
        "foe_amp": float(pack.encounter_cultivation_amp(dict(f_st.cultivation or {}))),
        "seed": random.randint(1, 10_000_000),
    }
    session.world_flags[ENCOUNTER_FLAG] = blob
    foe_name = session.profiles[foe_id].display_name
    return ActionResult(
        ok=True,
        message=f"与{foe_name}对峙，气机已满。点选小招后确定。{grant_note}",
        session=session,
    )


def _pick(
    session: GameSession,
    req: ActionRequest,
    pack: WorldPack,
) -> ActionResult:
    blob = _require_blob(session)
    if blob is None:
        return ActionResult(
            ok=False, message="尚无交锋", session=session, error_code="NO_ENCOUNTER"
        )
    if blob.get("phase") != "pick":
        return ActionResult(
            ok=False, message="此刻不可改招", session=session, error_code="BAD_PHASE"
        )

    catalog = _player_moves(session, pack)
    moves = (req.payload or {}).get("moves")
    if not isinstance(moves, list):
        return ActionResult(
            ok=False, message="招式序列无效", session=session, error_code="BAD_MOVES"
        )
    cleaned = [str(m).strip() for m in moves if str(m).strip()]
    if len(cleaned) > MAX_HANDS:
        return ActionResult(
            ok=False,
            message=f"至多出手 {MAX_HANDS} 次",
            session=session,
            error_code="TOO_MANY",
        )

    by_id = {m["move_id"]: m for m in catalog}
    spent = 0
    for mid in cleaned:
        m = by_id.get(mid)
        if not m:
            return ActionResult(
                ok=False, message=f"未知招式: {mid}", session=session, error_code="BAD_MOVE"
            )
        spent += int(m.get("qi_cost") or 1)
    qi_max = int(blob.get("qi_max") or 0)
    if spent > qi_max:
        return ActionResult(
            ok=False,
            message=f"气不足（需 {spent}，上限 {qi_max}）",
            session=session,
            error_code="NO_QI",
        )

    blob["player_moves"] = cleaned
    session.world_flags[ENCOUNTER_FLAG] = blob
    return ActionResult(ok=True, message="已记下招式次序", session=session)


def _confirm(
    session: GameSession,
    req: ActionRequest,
    pack: WorldPack,
    applier: StateApplier,
) -> ActionResult:
    blob = _require_blob(session)
    if blob is None:
        return ActionResult(
            ok=False, message="尚无交锋", session=session, error_code="NO_ENCOUNTER"
        )
    if blob.get("phase") != "pick":
        return ActionResult(
            ok=False, message="交锋已定", session=session, error_code="BAD_PHASE"
        )

    catalog = _player_moves(session, pack)
    player_moves = list(blob.get("player_moves") or [])
    if not player_moves:
        raw = (req.payload or {}).get("moves")
        if isinstance(raw, list) and raw:
            pick = _pick(session, req, pack)
            if not pick.ok:
                return pick
            blob = _require_blob(session) or {}
            player_moves = list(blob.get("player_moves") or [])
    if not player_moves:
        return ActionResult(
            ok=False, message="尚未点选招式", session=session, error_code="EMPTY"
        )

    by_id = {m["move_id"]: m for m in catalog}
    foe_id = str(blob.get("foe_id") or "")
    foe_catalog = _foe_moves(session, pack, foe_id)
    foe_by_id = {m["move_id"]: m for m in foe_catalog}
    # 合并字典供结算查名（双方招式 id 不重叠则安全）
    resolve_by_id = {**foe_by_id, **by_id}

    foe_qi_max = int(blob.get("foe_qi_max") or blob.get("qi_max") or 5)
    rng = random.Random(int(blob.get("seed") or 1))
    foe_moves = _ai_pick(foe_catalog, foe_qi_max, rng)

    p_amp = float(blob.get("player_amp") or 1.0)
    f_amp = float(blob.get("foe_amp") or 1.0)
    p_score, f_score, lines = _resolve_clash(
        player_moves, foe_moves, resolve_by_id, p_amp, f_amp
    )

    pid = session.player_id()
    foe_name = (
        session.profiles[foe_id].display_name if foe_id in session.profiles else "对手"
    )

    if p_score > f_score:
        verdict = "win"
        summary = f"与{foe_name}交锋，你略胜一筹。"
        loser_id = foe_id
        body_val = "bruised"
    elif f_score > p_score:
        verdict = "lose"
        summary = f"与{foe_name}交锋，你落了下风。"
        loser_id = pid
        body_val = "bruised"
    else:
        verdict = "draw"
        summary = f"与{foe_name}交锋，各退一步，难分高下。"
        loser_id = ""
        body_val = ""

    detail = "；".join(lines) if lines else "招式相交。"
    card = f"{summary}\n{detail}"

    packet = empty_packet()
    packet["world_flag_ops"][ENCOUNTER_FLAG] = None
    if loser_id and body_val:
        packet["state_ops"].append(
            {
                "actor_id": loser_id,
                "op": "set",
                "path": f"body.{body_val}",
                "value": True,
            }
        )
    ev = WorldEvent(
        event_id=f"duel_{uuid.uuid4().hex[:10]}",
        day=session.day,
        kind=EventKind.CONFLICT,
        severity=Severity.MINOR,
        title="演武交锋",
        summary=summary,
        card_body=card,
        location=session.states[pid].location,
        actor_ids=[pid, foe_id] if foe_id else [pid],
        involves_player=True,
        known_to=[pid, foe_id] if foe_id else [pid],
        tags=["combat", "duel", verdict],
    )
    packet["events"].append(ev)

    applied = apply_packet(session, packet, applier=applier)
    if session.world_flags.get(ENCOUNTER_FLAG) is None:
        session.world_flags.pop(ENCOUNTER_FLAG, None)
    return ActionResult(
        ok=True,
        message=summary,
        session=session,
        new_events=list(applied or [ev]),
    )


def _cancel(session: GameSession, applier: StateApplier) -> ActionResult:
    if not (session.world_flags or {}).get(ENCOUNTER_FLAG):
        return ActionResult(ok=True, message="并无交锋", session=session)
    packet = empty_packet()
    packet["world_flag_ops"][ENCOUNTER_FLAG] = None
    apply_packet(session, packet, applier=applier)
    if session.world_flags.get(ENCOUNTER_FLAG) is None:
        session.world_flags.pop(ENCOUNTER_FLAG, None)
    return ActionResult(ok=True, message="收势罢手", session=session)


def _require_blob(session: GameSession) -> dict[str, Any] | None:
    raw = (session.world_flags or {}).get(ENCOUNTER_FLAG)
    return raw if isinstance(raw, dict) else None


def _spent_qi(move_ids: list[Any], catalog: list[dict[str, Any]]) -> int:
    by_id = {m["move_id"]: m for m in catalog}
    total = 0
    for mid in move_ids:
        m = by_id.get(str(mid))
        if m:
            total += int(m.get("qi_cost") or 1)
    return total


def _ai_pick(
    catalog: list[dict[str, Any]], qi_max: int, rng: random.Random
) -> list[str]:
    pool = list(catalog)
    rng.shuffle(pool)
    picked: list[str] = []
    spent = 0
    for m in pool:
        if len(picked) >= MAX_HANDS:
            break
        cost = int(m.get("qi_cost") or 1)
        if spent + cost > qi_max:
            continue
        picked.append(str(m["move_id"]))
        spent += cost
    if not picked and catalog:
        # 至少一手最便宜的
        cheapest = min(catalog, key=lambda x: int(x.get("qi_cost") or 1))
        if int(cheapest.get("qi_cost") or 1) <= qi_max:
            picked = [str(cheapest["move_id"])]
    return picked


def _axis(move: dict[str, Any], key: str, amp: float) -> float:
    axes = move.get("axes") or {}
    try:
        base = float(axes.get(key) or 0)
    except (TypeError, ValueError):
        base = 0.0
    return base * amp


def _resolve_clash(
    player_ids: list[str],
    foe_ids: list[str],
    by_id: dict[str, dict[str, Any]],
    p_amp: float,
    f_amp: float,
) -> tuple[int, int, list[str]]:
    n = max(len(player_ids), len(foe_ids), 1)
    p_score = 0
    f_score = 0
    lines: list[str] = []
    for i in range(n):
        pm = by_id.get(player_ids[i]) if i < len(player_ids) else None
        fm = by_id.get(foe_ids[i]) if i < len(foe_ids) else None
        p_strike = _axis(pm, "strike", p_amp) if pm else 0.0
        p_guard = _axis(pm, "guard", p_amp) if pm else 0.0
        f_strike = _axis(fm, "strike", f_amp) if fm else 0.0
        f_guard = _axis(fm, "guard", f_amp) if fm else 0.0
        p_tags = set(pm.get("tags") or []) if pm else set()
        f_tags = set(fm.get("tags") or []) if fm else set()

        # 词条：破势压守；缠丝略削对方攻
        if "break" in p_tags:
            f_guard = max(0.0, f_guard - 1.5 * p_amp)
        if "break" in f_tags:
            p_guard = max(0.0, p_guard - 1.5 * f_amp)
        if "bind" in p_tags:
            f_strike = max(0.0, f_strike - 1.0 * p_amp)
        if "bind" in f_tags:
            p_strike = max(0.0, p_strike - 1.0 * f_amp)

        p_power = p_strike - f_guard
        f_power = f_strike - p_guard
        pn = (pm or {}).get("name") or "空"
        fn = (fm or {}).get("name") or "空"
        if p_power > f_power + 0.05:
            p_score += 1
            lines.append(f"第{i + 1}手：你「{pn}」压过「{fn}」")
        elif f_power > p_power + 0.05:
            f_score += 1
            lines.append(f"第{i + 1}手：对方「{fn}」压过「{pn}」")
        else:
            lines.append(f"第{i + 1}手：「{pn}」与「{fn}」相持")
    return p_score, f_score, lines
