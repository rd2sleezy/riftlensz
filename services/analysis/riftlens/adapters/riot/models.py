from __future__ import annotations

from typing import Any

from pydantic import BaseModel, ConfigDict, Field


class RiotModel(BaseModel):
    model_config = ConfigDict(extra="allow", populate_by_name=True)


class MatchMetadataDto(RiotModel):
    match_id: str = Field(alias="matchId")
    participants: list[str] = Field(default_factory=list)
    data_version: str | None = Field(default=None, alias="dataVersion")


class PerkStyleSelectionDto(RiotModel):
    perk: int | None = None
    var1: int | None = None
    var2: int | None = None
    var3: int | None = None


class PerkStyleDto(RiotModel):
    description: str | None = None
    selections: list[PerkStyleSelectionDto] = Field(default_factory=list)
    style: int | None = None


class PerksDto(RiotModel):
    stat_perks: dict[str, Any] | None = Field(default=None, alias="statPerks")
    styles: list[PerkStyleDto] = Field(default_factory=list)


class ParticipantDto(RiotModel):
    assists: int = 0
    baron_kills: int = Field(default=0, alias="baronKills")
    challenges: dict[str, Any] | None = None
    champion_id: int | None = Field(default=None, alias="championId")
    champion_name: str = Field(default="", alias="championName")
    damage_dealt_to_objectives: int = Field(default=0, alias="damageDealtToObjectives")
    damage_dealt_to_turrets: int = Field(default=0, alias="damageDealtToTurrets")
    damage_self_mitigated: int = Field(default=0, alias="damageSelfMitigated")
    deaths: int = 0
    detector_wards_placed: int = Field(default=0, alias="detectorWardsPlaced")
    dragon_kills: int = Field(default=0, alias="dragonKills")
    first_blood_kill: bool = Field(default=False, alias="firstBloodKill")
    first_tower_kill: bool = Field(default=False, alias="firstTowerKill")
    gold_earned: int = Field(default=0, alias="goldEarned")
    gold_spent: int = Field(default=0, alias="goldSpent")
    individual_position: str = Field(default="", alias="individualPosition")
    inhibitor_kills: int = Field(default=0, alias="inhibitorKills")
    item0: int = 0
    item1: int = 0
    item2: int = 0
    item3: int = 0
    item4: int = 0
    item5: int = 0
    item6: int = 0
    kills: int = 0
    largest_killing_spree: int = Field(default=0, alias="largestKillingSpree")
    longest_time_spent_living: int = Field(default=0, alias="longestTimeSpentLiving")
    magic_damage_dealt_to_champions: int = Field(default=0, alias="magicDamageDealtToChampions")
    neutral_minions_killed: int = Field(default=0, alias="neutralMinionsKilled")
    participant_id: int = Field(default=0, alias="participantId")
    perks: PerksDto | dict[str, Any] | None = None
    physical_damage_dealt_to_champions: int = Field(
        default=0, alias="physicalDamageDealtToChampions"
    )
    puuid: str = ""
    riot_id_game_name: str | None = Field(default=None, alias="riotIdGameName")
    riot_id_tagline: str | None = Field(default=None, alias="riotIdTagline")
    summoner1_casts: int = Field(default=0, alias="summoner1Casts")
    summoner1_id: int = Field(default=0, alias="summoner1Id")
    summoner2_casts: int = Field(default=0, alias="summoner2Casts")
    summoner2_id: int = Field(default=0, alias="summoner2Id")
    summoner_name: str | None = Field(default=None, alias="summonerName")
    team_id: int = Field(default=0, alias="teamId")
    team_position: str = Field(default="", alias="teamPosition")
    time_ccing_others: int = Field(default=0, alias="timeCCingOthers")
    total_damage_dealt_to_champions: int = Field(default=0, alias="totalDamageDealtToChampions")
    total_damage_taken: int = Field(default=0, alias="totalDamageTaken")
    total_minions_killed: int = Field(default=0, alias="totalMinionsKilled")
    total_time_cc_dealt: int = Field(default=0, alias="totalTimeCCDealt")
    total_time_spent_dead: int = Field(default=0, alias="totalTimeSpentDead")
    true_damage_dealt_to_champions: int = Field(default=0, alias="trueDamageDealtToChampions")
    turret_kills: int = Field(default=0, alias="turretKills")
    vision_score: int = Field(default=0, alias="visionScore")
    vision_wards_bought_in_game: int = Field(default=0, alias="visionWardsBoughtInGame")
    wards_killed: int = Field(default=0, alias="wardsKilled")
    wards_placed: int = Field(default=0, alias="wardsPlaced")
    win: bool = False
    all_in_pings: int = Field(default=0, alias="allInPings")
    assist_me_pings: int = Field(default=0, alias="assistMePings")
    enemy_missing_pings: int = Field(default=0, alias="enemyMissingPings")
    on_my_way_pings: int = Field(default=0, alias="onMyWayPings")


class TeamObjectivesDto(RiotModel):
    pass


class TeamDto(RiotModel):
    team_id: int = Field(default=0, alias="teamId")
    win: bool = False
    objectives: dict[str, Any] = Field(default_factory=dict)
    bans: list[Any] = Field(default_factory=list)


class MatchInfoDto(RiotModel):
    game_creation: int = Field(alias="gameCreation")
    game_start_timestamp: int | None = Field(default=None, alias="gameStartTimestamp")
    game_duration: int = Field(alias="gameDuration")
    game_end_timestamp: int | None = Field(default=None, alias="gameEndTimestamp")
    game_version: str = Field(alias="gameVersion")
    queue_id: int = Field(alias="queueId")
    map_id: int = Field(alias="mapId")
    participants: list[ParticipantDto]
    teams: list[TeamDto] = Field(default_factory=list)


class MatchDto(RiotModel):
    metadata: MatchMetadataDto
    info: MatchInfoDto


class PositionDto(RiotModel):
    x: int
    y: int


class ChampionStatsDto(RiotModel):
    health: float | int | None = None
    health_max: float | int | None = Field(default=None, alias="healthMax")
    health_regen: float | int | None = Field(default=None, alias="healthRegen")
    power: float | int | None = None
    power_max: float | int | None = Field(default=None, alias="powerMax")
    armor: float | int | None = None
    magic_resist: float | int | None = Field(default=None, alias="magicResist")
    attack_damage: float | int | None = Field(default=None, alias="attackDamage")
    ability_power: float | int | None = Field(default=None, alias="abilityPower")
    movement_speed: float | int | None = Field(default=None, alias="movementSpeed")
    ability_haste: float | int | None = Field(default=None, alias="abilityHaste")


class DamageStatsDto(RiotModel):
    total_damage_done: int = Field(default=0, alias="totalDamageDone")
    total_damage_done_to_champions: int = Field(default=0, alias="totalDamageDoneToChampions")
    total_damage_taken: int = Field(default=0, alias="totalDamageTaken")
    physical_damage_taken: int = Field(default=0, alias="physicalDamageTaken")
    magic_damage_taken: int = Field(default=0, alias="magicDamageTaken")
    true_damage_taken: int = Field(default=0, alias="trueDamageTaken")


class ParticipantFrameDto(RiotModel):
    participant_id: int | None = Field(default=None, alias="participantId")
    position: PositionDto | None = None
    current_gold: int = Field(default=0, alias="currentGold")
    total_gold: int = Field(default=0, alias="totalGold")
    gold_per_second: int = Field(default=0, alias="goldPerSecond")
    xp: int = 0
    level: int = 1
    minions_killed: int = Field(default=0, alias="minionsKilled")
    jungle_minions_killed: int = Field(default=0, alias="jungleMinionsKilled")
    champion_stats: ChampionStatsDto | None = Field(default=None, alias="championStats")
    damage_stats: DamageStatsDto | None = Field(default=None, alias="damageStats")
    time_enemy_spent_controlled: int | None = Field(default=None, alias="timeEnemySpentControlled")


class EventDto(RiotModel):
    type: str
    timestamp: int


class TimelineFrameDto(RiotModel):
    timestamp: int
    participant_frames: dict[str, ParticipantFrameDto] = Field(
        default_factory=dict, alias="participantFrames"
    )
    events: list[EventDto] = Field(default_factory=list)


class TimelineInfoDto(RiotModel):
    frame_interval: int = Field(alias="frameInterval")
    frames: list[TimelineFrameDto]
    participants: list[Any] = Field(default_factory=list)


class TimelineMetadataDto(RiotModel):
    match_id: str | None = Field(default=None, alias="matchId")
    participants: list[str] = Field(default_factory=list)
    data_version: str | None = Field(default=None, alias="dataVersion")


class TimelineDto(RiotModel):
    metadata: TimelineMetadataDto | None = None
    info: TimelineInfoDto


class AccountDto(RiotModel):
    puuid: str
    game_name: str | None = Field(default=None, alias="gameName")
    tag_line: str | None = Field(default=None, alias="tagLine")


class SummonerDto(RiotModel):
    id: str | None = None
    account_id: str | None = Field(default=None, alias="accountId")
    puuid: str
    profile_icon_id: int | None = Field(default=None, alias="profileIconId")
    revision_date: int | None = Field(default=None, alias="revisionDate")
    summoner_level: int | None = Field(default=None, alias="summonerLevel")
    name: str | None = None


class LeagueEntryDto(RiotModel):
    league_id: str | None = Field(default=None, alias="leagueId")
    puuid: str | None = None
    queue_type: str = Field(default="", alias="queueType")
    tier: str | None = None
    rank: str | None = None
    league_points: int = Field(default=0, alias="leaguePoints")
    wins: int = 0
    losses: int = 0
    summoner_id: str | None = Field(default=None, alias="summonerId")
    summoner_name: str | None = Field(default=None, alias="summonerName")
