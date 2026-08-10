from __future__ import annotations

import json
from pathlib import Path

from riftlens.adapters.riot.models import EventDto, MatchDto, TimelineDto
from riftlens.domain.enums import FactKind, Role, Source, Team
from riftlens.domain.fact import SubjectRef
from riftlens.pipeline.ingest_riot.fact_builder import build_game_state_timeline
from riftlens.pipeline.ingest_riot.lane_resolver import resolve_lanes

FIXTURE_ROOT = Path(__file__).resolve().parents[1] / "fixtures" / "riot"


def _load_pair(name: str) -> tuple[MatchDto, TimelineDto]:
    folder = FIXTURE_ROOT / name
    match = MatchDto.model_validate(json.loads((folder / "match.json").read_text(encoding="utf-8")))
    raw_timeline = json.loads((folder / "timeline.json").read_text(encoding="utf-8"))
    timeline = TimelineDto.model_validate(raw_timeline)
    return match, timeline


def _fact_counts(match: MatchDto, timeline: TimelineDto) -> dict[str, int]:
    gst = build_game_state_timeline(match, timeline)
    counts: dict[str, int] = {}
    for fact in gst.facts():
        counts[fact.kind.value] = counts.get(fact.kind.value, 0) + 1
    return dict(sorted(counts.items()))


def test_fact_counts_snapshot_all_fixtures(snapshot: object) -> None:
    payloads = {}
    for name in ("NA1_fixture_a", "NA1_fixture_b", "NA1_fixture_c"):
        match, timeline = _load_pair(name)
        payloads[name] = _fact_counts(match, timeline)
    assert payloads == snapshot


def test_frame_facts_are_riot_timeline_and_confident() -> None:
    match, timeline = _load_pair("NA1_fixture_a")
    gst = build_game_state_timeline(match, timeline)
    subject = SubjectRef(kind="participant", id=5)
    for kind in (
        FactKind.POSITION,
        FactKind.GOLD,
        FactKind.XP,
        FactKind.LEVEL,
        FactKind.CS,
        FactKind.HEALTH,
        FactKind.DAMAGE_ACCUM,
    ):
        facts = gst.facts(kind=kind, subject=subject)
        assert facts
        assert all(fact.source is Source.RIOT_TIMELINE and fact.confidence == 1.0 for fact in facts)
    health = gst.facts(kind=FactKind.HEALTH, subject=subject)[1]
    assert "healthRegen" in health.payload


def test_champion_kill_keeps_damage_arrays() -> None:
    match, timeline = _load_pair("NA1_fixture_a")
    gst = build_game_state_timeline(match, timeline)
    kills = gst.facts(kind=FactKind.CHAMPION_KILL)
    assert kills
    payload = dict(kills[0].payload)
    assert "victimDamageReceived" in payload
    assert "victimDamageDealt" in payload
    assert isinstance(payload["victimDamageReceived"], list)


def test_unknown_event_type_emits_derived() -> None:
    match, timeline = _load_pair("NA1_fixture_a")
    timeline.info.frames[0].events.append(EventDto(type="BRAND_NEW_RIOT_EVENT", timestamp=12))
    gst = build_game_state_timeline(match, timeline)
    derived = [
        fact
        for fact in gst.facts(kind=FactKind.DERIVED)
        if fact.payload.get("raw_type") == "BRAND_NEW_RIOT_EVENT"
    ]
    assert len(derived) == 1
    assert derived[0].t_ms == 12


def test_unpaired_fixture_uses_timeline_identity() -> None:
    match, timeline = _load_pair("NA1_fixture_a")
    gst = build_game_state_timeline(match, timeline)
    assert gst.champion_of(5) == "Pyke"
    assert gst.role_of(5) is Role.UTILITY
    assert gst.participants[5].team is Team.BLUE
    assert gst.lane_opponent(5) == 9
    assert gst.jungler_of(Team.BLUE) == 1
    assert gst.duration_ms == 2022037


def test_team_position_method_when_trusted() -> None:
    match, timeline = _load_pair("NA1_fixture_a")
    assignment = resolve_lanes(match, timeline, trust_match_positions=True)
    assert assignment.method == "team_position"
    assert assignment.roles[5] is Role.UTILITY
    assert assignment.opponents[1] == 10
