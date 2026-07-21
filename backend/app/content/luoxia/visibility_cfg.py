"""落霞可见性配置——引擎 VisibilityService 只读算法，表在内容包。"""

from __future__ import annotations

SENSITIVE_FLAG_KEYS = frozenset(
    {
        "allegiance",
        "knows_treasure_lost",
        "holds_luoxia_jian_sui",
        "knows_master_poisoned",
        "wants_help_but_distrusts",
        "blood_curse_host",
        "is_traitor",
        "secret",
        "believes_curse_only_weakens_array",
    }
)

SENSITIVE_WORLD_FLAGS = frozenset(
    {
        "blood_curse_planted",
        "fake_secret_realm_letter",
        "secret_realm_is_trigger",
        "blood_curse_host_unknown",
        "letter_exposed",
        "blood_curse_disarmed",
        "sect_at_brink",
        "crisis_fired",
        "master_luoyun_poisoned_by_xuanyin",
        "treasure_is_luoxia_jian_sui",
    }
)

PUBLIC_WORLD_FLAGS = frozenset({"xuanyin_countdown", "no_living_master"})

WORLD_FLAG_BELIEF_PREFIXES: dict[str, tuple[str, ...]] = {
    "letter_exposed": ("letter_exposed",),
    "fake_secret_realm_letter": ("letter_exposed", "fake_secret_realm_letter"),
    "blood_curse_planted": ("blood_curse_planted", "curse_planted"),
    "secret_realm_is_trigger": (
        "lin_su_detonate",
        "secret_realm_is_trigger",
        "ritual_detonate",
    ),
    "blood_curse_host_unknown": ("blood_curse_host", "curse_host"),
    "blood_curse_disarmed": ("curse_disarmed", "blood_curse_disarmed"),
    "sect_at_brink": ("sect_at_brink",),
    "crisis_fired": ("crisis_fired",),
    "crisis_averted_noted": ("crisis_averted",),
    "treasure_is_luoxia_jian_sui": (
        "treasure_is_luoxia_jian_sui",
        "shi_mei_hint_treasure",
        "jian_sui",
    ),
    "master_luoyun_poisoned_by_xuanyin": (
        "master_luoyun_poisoned",
        "shi_mei_partial_truth",
        "luoyun_poison",
    ),
}


def as_dict() -> dict:
    return {
        "sensitive_flag_keys": SENSITIVE_FLAG_KEYS,
        "sensitive_world_flags": SENSITIVE_WORLD_FLAGS,
        "public_world_flags": PUBLIC_WORLD_FLAGS,
        "world_flag_belief_prefixes": WORLD_FLAG_BELIEF_PREFIXES,
    }
