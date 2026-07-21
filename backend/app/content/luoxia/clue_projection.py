"""
落霞投影：硬状态 → 见闻分类 / 灰字隐情（无强制案线进度）。
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
