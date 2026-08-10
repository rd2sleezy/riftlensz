from __future__ import annotations

import json
from collections.abc import Iterable, Mapping
from pathlib import Path

from riftlens.adapters.ddragon.patch_data import PatchDataProvider
from riftlens.adapters.riot.models import MatchDto, TimelineDto
from riftlens.domain.enums import DataTier, FactKind, Role, Source, Team
from riftlens.domain.fact import Fact, Provenance, SubjectRef
from riftlens.domain.timeline import GameStateTimeline, ParticipantInfo
from riftlens.pipeline.ingest_riot.fact_builder import build_game_state_timeline

FIXTURE_ROOT = Path(__file__).resolve().parents[1] / "fixtures" / "riot"
_PROVENANCE = Provenance(producer="test", producer_version=1)


def load_fixture_pair(name: str = "NA1_fixture_a") -> tuple[MatchDto, TimelineDto]:
    """Return MatchDto+TimelineDto. Assumes a committed NA1_fixture_* folder."""
    folder = FIXTURE_ROOT / name
    match = MatchDto.model_validate(json.loads((folder / "match.json").read_text(encoding="utf-8")))
    timeline = TimelineDto.model_validate(
        json.loads((folder / "timeline.json").read_text(encoding="utf-8"))
    )
    return match, timeline


def load_gst(name: str = "NA1_fixture_a") -> GameStateTimeline:
    """Return a GST built from a committed fixture. Assumes no network."""
    match, timeline = load_fixture_pair(name)
    return build_game_state_timeline(match, timeline)


def bundled_patch(game_version: str = "12.4.423.2790") -> PatchDataProvider:
    """Return PatchDataProvider from shipped tables. Assumes no network."""
    provider = PatchDataProvider()
    provider.load_bundled(game_version)
    return provider


def make_participant(
    pid: int,
    *,
    team: Team = Team.BLUE,
    role: Role = Role.MIDDLE,
    champion: str = "Ahri",
) -> ParticipantInfo:
    """Return a test ParticipantInfo. Assumes ``pid`` is unique in the GST."""
    return ParticipantInfo(
        participant_id=pid,
        champion=champion,
        role=role,
        team=team,
        puuid=f"puuid-{pid}",
    )


def make_gst(
    facts: Iterable[Fact],
    participants: Mapping[int, ParticipantInfo] | None = None,
    *,
    match_id: str = "SYNTHETIC",
    patch: str = "12.4.423.2790",
    duration_ms: int = 600_000,
    lane_opponents: Mapping[int, int | None] | None = None,
) -> GameStateTimeline:
    """Return a GST from explicit facts. Assumes facts already use game-clock ms."""
    roster = dict(participants or {1: make_participant(1)})
    gst = GameStateTimeline(
        match_id=match_id,
        patch=patch,
        queue_id=420,
        duration_ms=duration_ms,
        participants=roster,
        available_data_tiers=frozenset({DataTier.RIOT_ONLY, DataTier.RIOT_DERIVED}),
        lane_opponents=lane_opponents,
    )
    gst.add_facts(facts)
    return gst


def fact(
    t_ms: int,
    kind: FactKind,
    pid: int | None,
    payload: Mapping[str, object],
    *,
    confidence: float = 1.0,
) -> Fact:
    """Return a test Fact. Assumes ``pid`` is None for global subjects."""
    subject = (
        SubjectRef(kind="global")
        if pid is None
        else SubjectRef(kind="participant", id=pid)
    )
    return Fact(
        t_ms=t_ms,
        kind=kind,
        subject=subject,
        payload=dict(payload),
        source=Source.RIOT_TIMELINE,
        confidence=confidence,
        provenance=_PROVENANCE,
    )
