from enum import Enum


class GamePhase(str, Enum):
    BOOT = "BOOT"
    PLAYER_TURN = "PLAYER_TURN"
    ADJUDICATING = "ADJUDICATING"
    WORLD_EVOLVE = "WORLD_EVOLVE"
    DAY_ROLLOVER = "DAY_ROLLOVER"
    MONTH_END = "MONTH_END"
    GAME_OVER = "GAME_OVER"
    ERROR = "ERROR"


class TruthRel(str, Enum):
    """信念相对权威真相的关系。"""

    MATCHES_AUTHORITY = "matches_authority"
    CONFLICTS_AUTHORITY = "conflicts_authority"
    UNKNOWN_TO_AUTHORITY = "unknown_to_authority"


class BeliefSource(str, Enum):
    WITNESS = "witness"
    TOLD_BY = "told_by"
    PROCLAMATION = "proclamation"
    RUMOR = "rumor"
    INFERENCE = "inference"
    SELF = "self"


class EventKind(str, Enum):
    SOCIAL = "social"
    CONFLICT = "conflict"
    DEATH = "death"
    ITEM = "item"
    CULTIVATION = "cultivation"
    LAW = "law"
    RUMOR = "rumor"
    WORLD = "world"
    OTHER = "other"


class Severity(str, Enum):
    TRIVIAL = "trivial"
    MINOR = "minor"
    MAJOR = "major"
    CRITICAL = "critical"


class ActionType(str, Enum):
    """引擎认识的玩家/系统动作类型——可扩展字符串由内容包补充。"""

    TALK = "talk"
    MOVE = "move"
    END_DAY = "end_day"
    ENCOUNTER = "encounter"
    CUSTOM = "custom"
