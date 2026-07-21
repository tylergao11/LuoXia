"""
落霞线索投影：硬状态 → 见闻分类 / 案线阶段 / 灰字隐情。
真相源：docs/luoxia.md §8.4
UI 只读；不发线索、不按天数解锁。
"""

from __future__ import annotations

from typing import Any

from app.core.domain.enums import BeliefSource, TruthRel
from app.core.domain.models import Belief, GameSession

CATEGORY_LABELS: dict[str, str] = {
    "proclamation": "通告",
    "entrust": "托付",
    "evidence": "实证",
    "rumor": "传闻",
}

CATEGORY_ORDER = ("proclamation", "entrust", "evidence", "rumor")


def _src(b: Belief | dict[str, Any]) -> str:
    if isinstance(b, dict):
        s = b.get("source", "")
    else:
        s = b.source.value if hasattr(b.source, "value") else str(b.source)
    return str(s or "")


def _truth(b: Belief | dict[str, Any]) -> str:
    if isinstance(b, dict):
        t = b.get("truth_rel", "")
    else:
        t = b.truth_rel.value if hasattr(b.truth_rel, "value") else str(b.truth_rel)
    return str(t or "")


def _bid(b: Belief | dict[str, Any]) -> str:
    if isinstance(b, dict):
        return str(b.get("belief_id") or "")
    return b.belief_id or ""


def classify_belief(b: Belief | dict[str, Any]) -> str:
    """优先级：通告 > 托付 > 实证 > 传闻。返回 category id。不扫命题词表。"""
    src = _src(b)
    bid = _bid(b)
    truth = _truth(b)

    if src == BeliefSource.PROCLAMATION.value or src == "proclamation":
        return "proclamation"
    if bid.startswith("shi_mei_"):
        return "entrust"
    if src == BeliefSource.WITNESS.value or src == "witness":
        return "evidence"
    if truth == TruthRel.MATCHES_AUTHORITY.value or truth == "matches_authority":
        return "evidence"
    return "rumor"


def classify_belief_view(b: Belief | dict[str, Any]) -> dict[str, str]:
    cat = classify_belief(b)
    return {"category": cat, "category_label": CATEGORY_LABELS[cat]}


def enrich_belief_row(b: Belief) -> dict[str, Any]:
    cat = classify_belief_view(b)
    return {
        "belief_id": b.belief_id,
        "proposition": b.proposition,
        "source": b.source.value if hasattr(b.source, "value") else b.source,
        "truth_rel": b.truth_rel.value if hasattr(b.truth_rel, "value") else b.truth_rel,
        "confidence": b.confidence,
        "day": b.day,
        **cat,
    }


def _has_belief_id_prefix(session: GameSession, prefixes: tuple[str, ...]) -> bool:
    pid = session.player_id()
    for b in session.beliefs.get(pid, []):
        bid = b.belief_id or ""
        if any(bid.startswith(p) for p in prefixes):
            return True
    return False


def _player_flags(session: GameSession) -> dict[str, Any]:
    st = session.states.get(session.player_id())
    return dict(st.flags or {}) if st else {}


def _evidence_level(session: GameSession) -> int:
    try:
        return int(_player_flags(session).get("evidence_level") or 0)
    except (TypeError, ValueError):
        return 0


def _stage(
    sid: str,
    label: str,
    *,
    revealed: bool,
    blurb: str = "",
) -> dict[str, Any]:
    return {
        "id": sid,
        "label": label if revealed else "？",
        "label_true": label,
        "revealed": revealed,
        "blurb": blurb if revealed else "",
    }


def _current_stage_id(stages: list[dict[str, Any]]) -> str:
    last = ""
    for s in stages:
        if s.get("revealed"):
            last = str(s.get("id") or "")
    return last


def project_case_lines(session: GameSession) -> list[dict[str, Any]]:
    """三条案线：结构常显，未成立阶段为？。"""
    flags = session.world_flags or {}
    pflags = _player_flags(session)
    luo = session.states.get("shi_mei")
    luo_flags = dict(luo.flags or {}) if luo else {}

    letter_rumor = bool(
        pflags.get("heard_letter")
        or pflags.get("investigating_letter")
        or pflags.get("suspects_letter")
        or _has_belief_id_prefix(session, ("letter_", "heard_letter", "fake_letter"))
    )
    letter_doubt = _evidence_level(session) >= 2 or bool(
        pflags.get("investigating_letter") or pflags.get("suspects_letter")
    )
    letter_exposed = bool(flags.get("letter_exposed"))
    letter_public = bool(pflags.get("letter_public")) or _has_belief_id_prefix(
        session, ("proclamation_letter",)
    )
    if letter_exposed and not letter_public:
        for b in session.beliefs.get(session.player_id(), []):
            if _src(b) == "proclamation" and (b.belief_id or "").startswith("proclamation"):
                letter_public = True
                break
        if not letter_public:
            for ev in session.events:
                tags = set(ev.tags or [])
                if "proclamation" in tags and ("letter" in tags or "假信" in tags):
                    letter_public = True
                    break

    letter_stages = [
        _stage(
            "hear",
            "风闻",
            revealed=letter_rumor or letter_doubt or letter_exposed,
            blurb="你已听说密信或秘境来函之事。",
        ),
        _stage(
            "doubt",
            "疑窦",
            revealed=letter_doubt or letter_exposed,
            blurb="密信疑点已在心中成形。",
        ),
        _stage("prove", "坐实", revealed=letter_exposed, blurb="假信已被坐实。"),
        _stage(
            "public",
            "公开",
            revealed=letter_public,
            blurb="假信之事已见通告或公开传开。",
        ),
    ]

    omen = True  # 开局劫数已知 → 异兆结构亮
    investigating = bool(
        pflags.get("investigating_curse")
        or pflags.get("investigating_array")
        or _evidence_level(session) >= 3
    )
    disarmed = bool(flags.get("blood_curse_disarmed") or flags.get("sect_stabilized"))
    crisis = bool(flags.get("crisis_fired"))
    averted = bool(flags.get("crisis_averted_noted"))

    burst_label = "化险" if averted and not crisis else "爆发"
    blood_stages = [
        _stage("omen", "异兆", revealed=omen, blurb="护山与劫数的异兆已入你耳。"),
        _stage(
            "probe",
            "查阵",
            revealed=investigating or disarmed or crisis or averted,
            blurb="你已着手查证血阴/阵眼。",
        ),
        _stage("break", "破阵", revealed=disarmed, blurb="血阴之患已暂镇或宗门暂稳。"),
        _stage(
            "burst",
            burst_label,
            revealed=crisis or averted,
            blurb=(
                "劫数已改写，化险为夷。"
                if averted and not crisis
                else "护山异变已起。"
                if crisis
                else ""
            ),
        ),
    ]

    try:
        trust_n = int(luo_flags.get("trust_player") or 0)
    except (TypeError, ValueError):
        trust_n = 0
    entrusted = bool(
        luo_flags.get("trusts_player")
        or trust_n >= 2
        or luo_flags.get("arc_shi_mei_hint")
        or luo_flags.get("arc_shi_mei_partial")
        or luo_flags.get("arc_shi_mei_warming")
    )
    allied = bool(luo_flags.get("ally_player") or luo_flags.get("arc_shi_mei_ally"))
    betrayal = bool(
        (luo is not None and not luo.alive)
        or luo_flags.get("betrayed_by_player")
        or luo_flags.get("arc_shi_mei_hostile")
    )

    heart_stages = [
        _stage("guarded", "隔心", revealed=True, blurb="洛晴对宗门中人仍多防备。"),
        _stage(
            "entrust",
            "托重",
            revealed=entrusted or allied,
            blurb="她对你渐有托付之意。",
        ),
        _stage("ally", "同盟", revealed=allied, blurb="洛晴愿与你联手。"),
        _stage("rift", "反目", revealed=betrayal, blurb="人心已裂，或闻凶信。"),
    ]

    return [
        {
            "id": "letter",
            "title": "假信",
            "stages": letter_stages,
            "current": _current_stage_id(letter_stages),
        },
        {
            "id": "blood",
            "title": "血阴",
            "stages": blood_stages,
            "current": _current_stage_id(blood_stages),
        },
        {
            "id": "heart",
            "title": "人心",
            "stages": heart_stages,
            "current": _current_stage_id(heart_stages),
        },
    ]


CLUE_FLAG_ORDER: list[tuple[str, str]] = [
    ("xuanyin_countdown", "劫数倒计时"),
    ("letter_exposed", "假信坐实"),
    ("fake_secret_realm_letter", "密信为假"),
    ("blood_curse_planted", "血阴已种"),
    ("secret_realm_is_trigger", "仪式即引爆"),
    ("blood_curse_disarmed", "血阴已解"),
    ("crisis_fired", "护山异变"),
    ("crisis_averted_noted", "劫数改写"),
    ("treasure_is_luoxia_jian_sui", "至宝为落霞剑髓"),
    ("master_luoyun_poisoned_by_xuanyin", "落云子为下毒"),
    ("sect_at_brink", "宗门危局"),
    ("blood_curse_host_unknown", "咒种寄宿未明"),
]

CLUE_FLAG_DISPLAY_TRUE: dict[str, str] = {
    "letter_exposed": "密信骗局已坐实",
    "fake_secret_realm_letter": "秘境来函实为假信",
    "blood_curse_planted": "护山阵眼已种血阴咒",
    "secret_realm_is_trigger": "开启仪式约等于引爆",
    "blood_curse_disarmed": "血阴之患已被镇压",
    "crisis_fired": "护山异变已起",
    "crisis_averted_noted": "劫数已被改写",
    "treasure_is_luoxia_jian_sui": "宗门至宝乃落霞剑髓",
    "master_luoyun_poisoned_by_xuanyin": "落云子坐化实为玄阴下毒",
    "sect_at_brink": "宗门已至危局",
    "blood_curse_host_unknown": "血阴寄宿之所尚未查明",
}


def _clue_flag_known(session: GameSession, key: str) -> bool:
    """内容包内知情判定：用本包 visibility_cfg，不经 container。"""
    from app.content.luoxia import visibility_cfg

    st = session.states.get(session.player_id())
    if st and (st.flags or {}).get(f"knows_{key}"):
        return True
    prefixes = visibility_cfg.WORLD_FLAG_BELIEF_PREFIXES.get(key) or (key,)
    pid = session.player_id()
    for b in session.beliefs.get(pid, []):
        bid = b.belief_id or ""
        if any(bid.startswith(p) for p in prefixes):
            return True
    return False


def project_clue_flags(session: GameSession) -> list[dict[str, Any]]:
    """有序灰字面板：结构常显；未证实显示？？？。"""
    out: list[dict[str, Any]] = []
    for key, label_zh in CLUE_FLAG_ORDER:
        raw = session.world_flags.get(key)
        if key == "xuanyin_countdown":
            out.append(
                {
                    "key": key,
                    "label_zh": label_zh,
                    "greyed": False,
                    "value": raw,
                    "display": str(raw) if raw is not None else "—",
                }
            )
            continue
        # 结构常显；点亮只认硬知情（flag / belief_id）
        known = _clue_flag_known(session, key)
        if known:
            if raw is True:
                display = CLUE_FLAG_DISPLAY_TRUE.get(key, str(raw))
            elif raw is False or raw is None:
                display = "尚未坐实"
            else:
                display = CLUE_FLAG_DISPLAY_TRUE.get(key, str(raw))
        else:
            display = "？？？（未证实）"
        out.append(
            {
                "key": key,
                "label_zh": label_zh,
                "greyed": not known,
                "value": raw if known else None,
                "display": display,
            }
        )
    return out
