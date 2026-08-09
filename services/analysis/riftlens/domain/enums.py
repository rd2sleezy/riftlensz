from __future__ import annotations

from enum import IntEnum, StrEnum


class Role(StrEnum):
    TOP = "TOP"
    JUNGLE = "JUNGLE"
    MIDDLE = "MIDDLE"
    BOTTOM = "BOTTOM"
    UTILITY = "UTILITY"
    UNKNOWN = "UNKNOWN"


class Team(IntEnum):
    BLUE = 100
    RED = 200


class GamePhase(StrEnum):
    EARLY = "EARLY"
    MID = "MID"
    LATE = "LATE"


class FactKind(StrEnum):
    POSITION = "POSITION"
    GOLD = "GOLD"
    XP = "XP"
    LEVEL = "LEVEL"
    CS = "CS"
    HEALTH = "HEALTH"
    DAMAGE_ACCUM = "DAMAGE_ACCUM"
    CHAMPION_KILL = "CHAMPION_KILL"
    CHAMPION_ASSIST = "CHAMPION_ASSIST"
    ITEM_PURCHASED = "ITEM_PURCHASED"
    ITEM_SOLD = "ITEM_SOLD"
    ITEM_DESTROYED = "ITEM_DESTROYED"
    WARD_PLACED = "WARD_PLACED"
    WARD_KILL = "WARD_KILL"
    SKILL_LEVEL_UP = "SKILL_LEVEL_UP"
    LEVEL_UP = "LEVEL_UP"
    BUILDING_KILL = "BUILDING_KILL"
    TURRET_PLATE_DESTROYED = "TURRET_PLATE_DESTROYED"
    ELITE_MONSTER_KILL = "ELITE_MONSTER_KILL"
    PAUSE_END = "PAUSE_END"
    GAME_END = "GAME_END"
    OBSERVATION = "OBSERVATION"
    DERIVED = "DERIVED"


class Source(StrEnum):
    RIOT_TIMELINE = "RIOT_TIMELINE"
    RIOT_MATCH = "RIOT_MATCH"
    CV = "CV"
    DERIVED = "DERIVED"
    USER = "USER"


class Severity(StrEnum):
    CRIT = "CRIT"
    HIGH = "HIGH"
    MEDIUM = "MEDIUM"
    LOW = "LOW"


class DataTier(StrEnum):
    RIOT_ONLY = "RIOT_ONLY"
    RIOT_DERIVED = "RIOT_DERIVED"
    CV_REQUIRED = "CV_REQUIRED"


class Lane(StrEnum):
    TOP = "TOP"
    MIDDLE = "MIDDLE"
    BOTTOM = "BOTTOM"
