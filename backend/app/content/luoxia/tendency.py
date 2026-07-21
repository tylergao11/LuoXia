"""
公开倾向摘要：进 DYNAMIC / 夜演 SLOT，不进冻结 STABLE，不剧透权威隐秘。
真相源：docs/luoxia.md §3 / §7
"""

from __future__ import annotations

from typing import Any

from app.core.domain.models import GameSession

# 禁止出现在公开 blurb 的词（防止误注入）
_FORBIDDEN = (
    "内应",
    "玄阴殿内应",
    "allegiance",
    "xuanyin",
    "落霞剑髓在",
    "下毒杀",
    "持有剑髓",
)


def public_tendency_blurb(session: GameSession, actor_id: str) -> str:
    """单角色短公开倾向；无则空串。"""
    prof = session.profiles.get(actor_id)
    st = session.states.get(actor_id)
    if not prof or not st or not st.alive:
        return ""

    parts: list[str] = []
    # 公开人设一句（截断，去掉可能泄密的 drives 半句）
    pers = (prof.personality or "").strip()
    if pers:
        parts.append(pers.split("；")[0][:40])

    flags = st.flags or {}

    if actor_id == "er_shi_xiong":
        if flags.get("knows_curse_will_detonate"):
            stance = str(flags.get("shake_stance") or "self_protect")
            parts.append(
                {
                    "self_protect": "近来神色不稳，似在权衡自保",
                    "consider_flip": "似在寻退路，对可倚之人试探示好",
                    "frantic": "谈及护山时易慌乱撇清",
                }.get(stance, "近来神色不稳，似在权衡自保")
            )
        else:
            parts.append("对外圆融，喜谈机缘与人缘")

    elif actor_id == "shi_mei":
        if flags.get("ally_player") or flags.get("arc_shi_mei_ally"):
            parts.append("对客卿已有联手之意，仍谨慎")
        elif flags.get("trusts_player") or int(flags.get("trust_player") or 0) >= 2:
            parts.append("对客卿防备略松，话仍不多")
        else:
            parts.append("冷淡寡言，对宗门中人多有防备")

    elif actor_id == "da_shi_xiong":
        parts.append("寡言守业，暗查宗门异动，不轻易信人")

    elif actor_id == "zhang_lao_fa":
        parts.append("讲规矩，重程序，通告权在握")

    elif actor_id == "san_shi_jie":
        if flags.get("cursed_backlash"):
            parts.append("秩序执念更重，易走极端")
        else:
            parts.append("冷傲好正统，厌见混乱")

    elif "gossip" in (prof.tags or []):
        parts.append("耳软嘴碎，爱传闲话")

    elif "law" in (prof.tags or []):
        parts.append("按令行事，少有私心表态")

    text = "；".join(p for p in parts if p)
    for bad in _FORBIDDEN:
        if bad in text:
            text = text.replace(bad, "……")
    return text[:120]


def tendencies_map(session: GameSession, actor_ids: list[str] | None = None) -> dict[str, str]:
    ids = actor_ids if actor_ids is not None else list(session.profiles.keys())
    out: dict[str, str] = {}
    for aid in sorted(set(ids)):
        if aid == session.player_id():
            continue
        blurb = public_tendency_blurb(session, aid)
        if blurb:
            out[aid] = blurb
    return out


def attach_tendencies_extra(
    session: GameSession,
    actor_ids: list[str],
    extra: dict[str, Any] | None,
) -> dict[str, Any]:
    """合并到 DYNAMIC.extra，不覆盖调用方已有键。"""
    base = dict(extra or {})
    if "tendencies" not in base:
        base["tendencies"] = tendencies_map(session, actor_ids)
    return base
