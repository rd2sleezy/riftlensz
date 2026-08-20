"""C.1 coaching episode builder tests. Does not change H.8/H.11 behavior."""

from __future__ import annotations

from pathlib import Path

from riftlens.analysis.rules.engine import RuleEngine
from riftlens.analysis.rules.loader import load_rule_pack
from riftlens.coaching.context import (
    COACHING_EPISODE_SCHEMA_VERSION,
    EPISODE_GROUPING_SEMANTICS,
    EpisodeBuilderConfig,
    FindingAssociation,
    ResolutionStatus,
    SnapshotPoint,
    build_coaching_episodes,
    episode_id,
)
from riftlens.coaching.context.models import ContextOrigin
from riftlens.domain.enums import EvidenceKind, FactKind, Severity, Source
from riftlens.domain.evidence import Evidence
from riftlens.domain.fact import Fact, Provenance, SubjectRef
from riftlens.domain.finding import Finding
from tests.helpers.gst import bundled_patch, fact, load_gst, make_gst, make_participant
from tests.helpers.h7_scenarios import r006_fire, r007_fire
from tests.helpers.synthetic import buy, quiet_frames, roster

_PROV = Provenance(producer="c1_test", producer_version=1)
_CONTEXT_ROOT = Path(__file__).resolve().parents[2] / "riftlens" / "coaching" / "context"


def _evidence(label: str, value: object, t_ms: int, *, inferred: bool = False) -> Evidence:
    return Evidence(
        kind=EvidenceKind.FACT,
        label=label,
        value=value,
        source=Source.DERIVED if inferred else Source.RIOT_TIMELINE,
        t_ms=t_ms,
        confidence=0.7 if inferred else 1.0,
    )


def _finding(
    *,
    finding_id: str,
    rule_id: str,
    t_ms: int,
    concept_id: str = "TEST.CONCEPT",
    suppressed: bool = False,
    extra: tuple[Evidence, ...] = (),
) -> Finding:
    items = (_evidence("event", {"t_ms": t_ms, "rule_id": rule_id}, t_ms), *extra)
    return Finding(
        id=finding_id,
        rule_id=rule_id,
        rule_version=1,
        concept_id=concept_id,
        t_ms=t_ms,
        severity=Severity.MEDIUM,
        confidence=0.9,
        title=rule_id,
        evidence=items,
        suppressed=suppressed,
        suppressed_by="R-001" if suppressed else None,
    )


def _base_gst(*, duration_ms: int = 300_000, extra: list[Fact] | None = None):
    people = {1: make_participant(1)}
    facts = [
        fact(0, FactKind.POSITION, 1, {"x": 6000, "y": 6200}),
        fact(60_000, FactKind.POSITION, 1, {"x": 6100, "y": 6300}),
        fact(120_000, FactKind.POSITION, 1, {"x": 6200, "y": 6400}),
        fact(0, FactKind.GOLD, 1, {"currentGold": 1800, "totalGold": 2000, "goldPerSecond": 9}),
        fact(
            60_000,
            FactKind.GOLD,
            1,
            {"currentGold": 1800, "totalGold": 2600, "goldPerSecond": 9},
        ),
        fact(
            120_000,
            FactKind.GOLD,
            1,
            {"currentGold": 1800, "totalGold": 3200, "goldPerSecond": 9},
        ),
        fact(0, FactKind.HEALTH, 1, {"health": 300, "healthMax": 1000, "healthRegen": 12}),
        fact(60_000, FactKind.HEALTH, 1, {"health": 300, "healthMax": 1000, "healthRegen": 12}),
        fact(120_000, FactKind.HEALTH, 1, {"health": 300, "healthMax": 1000, "healthRegen": 12}),
        fact(0, FactKind.LEVEL, 1, {"level": 6}),
        fact(60_000, FactKind.LEVEL, 1, {"level": 6}),
        fact(120_000, FactKind.LEVEL, 1, {"level": 7}),
        fact(0, FactKind.XP, 1, {"xp": 2000}),
        fact(60_000, FactKind.XP, 1, {"xp": 2400}),
        fact(0, FactKind.CS, 1, {"minionsKilled": 40, "jungleMinionsKilled": 0}),
        fact(60_000, FactKind.CS, 1, {"minionsKilled": 50, "jungleMinionsKilled": 0}),
        fact(duration_ms, FactKind.GAME_END, None, {"gameId": 1}),
        *(extra or []),
    ]
    return make_gst(facts, people, match_id="C1_SYNTH", duration_ms=duration_ms)


def test_zero_findings_yield_zero_episodes() -> None:
    gst = _base_gst()
    assert build_coaching_episodes(gst, [], 1) == []


def test_single_finding_one_bounded_episode() -> None:
    gst = _base_gst()
    item = _finding(finding_id="f1", rule_id="R-001", t_ms=90_000)
    episodes = build_coaching_episodes(gst, [item], 1)
    assert len(episodes) == 1
    episode = episodes[0]
    assert episode.schema_version == COACHING_EPISODE_SCHEMA_VERSION
    assert episode.grouping == EPISODE_GROUPING_SEMANTICS
    assert episode.start_ms == 30_000
    assert episode.end_ms == 120_000
    assert episode.findings[0].association is FindingAssociation.ANCHOR
    assert episode.findings[0].finding_id == "f1"
    points = {sample.point for sample in episode.samples}
    assert points == {SnapshotPoint.BEFORE, SnapshotPoint.ANCHOR, SnapshotPoint.AFTER}


def test_game_start_and_end_clamping() -> None:
    gst = _base_gst(duration_ms=250_000)
    early = _finding(finding_id="early", rule_id="R-001", t_ms=5_000)
    late = _finding(finding_id="late", rule_id="R-004", t_ms=240_000)
    episodes = build_coaching_episodes(gst, [early, late], 1)
    by_id = {item.findings[0].finding_id: item for item in episodes}
    assert by_id["early"].start_ms == 0
    assert by_id["late"].end_ms == 250_000


def test_overlapping_windows_group_and_separated_windows_do_not() -> None:
    gst = _base_gst(duration_ms=400_000)
    close_a = _finding(finding_id="a", rule_id="R-001", t_ms=100_000)
    close_b = _finding(finding_id="b", rule_id="R-003", t_ms=130_000)
    far = _finding(finding_id="c", rule_id="R-008", t_ms=300_000)
    episodes = build_coaching_episodes(gst, [far, close_b, close_a], 1)
    assert len(episodes) == 2
    merged = next(item for item in episodes if len(item.findings) == 2)
    ids = [row.finding_id for row in merged.findings]
    assert ids == ["a", "b"]
    assert all(row.association is FindingAssociation.ANCHOR for row in merged.findings)
    solo = next(item for item in episodes if item.findings[0].finding_id == "c")
    assert solo.start_ms == 240_000


def test_episode_ids_and_orders_are_deterministic() -> None:
    gst = _base_gst()
    items = [
        _finding(finding_id="b", rule_id="R-003", t_ms=100_000),
        _finding(finding_id="a", rule_id="R-001", t_ms=90_000),
    ]
    first = build_coaching_episodes(gst, items, 1)
    second = build_coaching_episodes(gst, list(reversed(items)), 1)
    assert first[0].to_dict() == second[0].to_dict()
    expected = episode_id(
        "C1_SYNTH",
        1,
        first[0].start_ms,
        first[0].end_ms,
        ("a", "b"),
    )
    assert first[0].id == expected
    pairs = [(row.t_ms, row.kind.value, str(row.subject_id)) for row in first[0].fact_refs]
    assert pairs == sorted(pairs)


def test_provenance_and_quarantine_and_no_visual_source() -> None:
    visual = Fact(
        t_ms=90_000,
        kind=FactKind.OBSERVATION,
        subject=SubjectRef(kind="participant", id=1),
        payload={"omniscient": False, "via": "visual"},
        source=Source.VISUAL,
        confidence=0.4,
        provenance=_PROV,
    )
    gst = _base_gst(extra=[visual])
    item = _finding(finding_id="f1", rule_id="R-001", t_ms=90_000)
    episode = build_coaching_episodes(gst, [item], 1)[0]
    sources = {row.source for row in episode.fact_refs}
    assert Source.VISUAL not in sources
    assert Source.VISUAL_INFERRED not in sources
    assert Source.CV not in sources
    payloads = [dict(row.payload) for row in episode.fact_refs if row.kind is FactKind.GOLD]
    assert payloads
    for payload in payloads:
        assert "goldPerSecond" not in payload
        assert "healthRegen" not in payload
    inferred = next(row for row in episode.samples if row.point is SnapshotPoint.ANCHOR)
    assert inferred.current_gold is not None
    if not inferred.current_gold.exact:
        assert inferred.current_gold.origin is ContextOrigin.GST_DERIVED
    gap_fields = {gap.field for gap in episode.gaps}
    assert "true_fog" in gap_fields
    assert "ward_map" in gap_fields
    assert "summoner_state" in gap_fields
    assert "wave_state" in gap_fields
    assert "visual_observations" in gap_fields


def test_coarse_position_is_not_marked_exact() -> None:
    gst = _base_gst()
    item = _finding(finding_id="f1", rule_id="R-001", t_ms=90_000)
    sample = next(
        row
        for row in build_coaching_episodes(gst, [item], 1)[0].samples
        if row.point is SnapshotPoint.ANCHOR
    )
    assert sample.position_x is not None
    assert sample.position_x.exact is False
    assert sample.position_x.origin is ContextOrigin.GST_DERIVED
    gaps = build_coaching_episodes(gst, [item], 1)[0].gaps
    assert any(gap.field == "position_precision" for gap in gaps)


def test_unspent_gold_absent_without_patch() -> None:
    gst = _base_gst()
    item = _finding(finding_id="f1", rule_id="R-006", t_ms=90_000)
    sample = next(
        row
        for row in build_coaching_episodes(gst, [item], 1)[0].samples
        if row.point is SnapshotPoint.ANCHOR
    )
    assert sample.unspent_gold is None
    assert sample.alive is None


def test_suppressed_findings_are_associated_not_anchors() -> None:
    gst = _base_gst()
    seed = _finding(finding_id="seed", rule_id="R-001", t_ms=90_000)
    quiet = _finding(finding_id="quiet", rule_id="R-003", t_ms=95_000, suppressed=True)
    episode = build_coaching_episodes(gst, [quiet, seed], 1)[0]
    by_id = {row.finding_id: row for row in episode.findings}
    assert by_id["seed"].association is FindingAssociation.ANCHOR
    assert by_id["quiet"].association is FindingAssociation.TEMPORALLY_ASSOCIATED
    assert by_id["quiet"].suppressed is True
    assert build_coaching_episodes(gst, [quiet], 1) == []


def test_strength_findings_can_anchor_an_episode() -> None:
    gst = _base_gst()
    item = _finding(
        finding_id="p1",
        rule_id="P-001",
        t_ms=90_000,
        concept_id="STRENGTH.CLEAN_LANE_PHASE",
    )
    episode = build_coaching_episodes(gst, [item], 1)[0]
    assert episode.findings[0].rule_id == "P-001"
    assert episode.findings[0].association is FindingAssociation.ANCHOR


def test_r006_purchase_resolves_and_unsupported_stays_not_evaluated() -> None:
    gst = _base_gst(extra=[buy(100_000, 1, 1038)])
    dead = _finding(
        finding_id="r6",
        rule_id="R-006",
        t_ms=90_000,
        extra=(_evidence("unspent gold samples", {"values": [1800], "threshold": 1300}, 90_000),),
    )
    risk = _finding(finding_id="r1", rule_id="R-001", t_ms=92_000)
    episode = build_coaching_episodes(gst, [dead, risk], 1)[0]
    by_id = {row.finding_id: row for row in episode.resolutions}
    assert by_id["r6"].status is ResolutionStatus.RESOLVED
    assert by_id["r6"].resolver == "r006_unspent_gold_purchase"
    assert "not mean the original decision was correct" in by_id["r6"].note
    assert by_id["r1"].status is ResolutionStatus.NOT_EVALUATED


def test_r006_persisted_on_exact_gold_frame() -> None:
    gst = _base_gst()
    item = _finding(
        finding_id="r6",
        rule_id="R-006",
        t_ms=90_000,
        extra=(_evidence("unspent gold samples", {"threshold": 1300}, 90_000),),
    )
    row = build_coaching_episodes(gst, [item], 1)[0].resolutions[0]
    assert row.status is ResolutionStatus.PERSISTED
    assert row.resolver == "r006_unspent_gold_frame"


def test_r006_unknown_without_post_frame_or_purchase() -> None:
    gst = make_gst(
        [
            fact(0, FactKind.GOLD, 1, {"currentGold": 1800, "totalGold": 1800}),
            fact(60_000, FactKind.GOLD, 1, {"currentGold": 1800, "totalGold": 1800}),
            fact(180_000, FactKind.GAME_END, None, {}),
        ],
        {1: make_participant(1)},
        duration_ms=180_000,
    )
    item = _finding(finding_id="r6", rule_id="R-006", t_ms=90_000)
    config = EpisodeBuilderConfig(post_context_ms=20_000)
    row = build_coaching_episodes(gst, [item], 1, config)[0].resolutions[0]
    assert row.status is ResolutionStatus.UNKNOWN


def test_r007_resolves_on_exact_high_hp_frame() -> None:
    extra = [
        fact(110_000, FactKind.HEALTH, 1, {"health": 900, "healthMax": 1000, "healthRegen": 0}),
    ]
    gst = _base_gst(extra=extra)
    item = _finding(finding_id="r7", rule_id="R-007", t_ms=90_000)
    row = build_coaching_episodes(gst, [item], 1)[0].resolutions[0]
    assert row.status is ResolutionStatus.RESOLVED
    assert row.resolver == "r007_hp_frame"


def test_resolution_thresholds_match_rule_yaml() -> None:
    pack = load_rule_pack()
    config = EpisodeBuilderConfig()
    r006 = next(rule for rule in pack.rules if rule.id == "R-006")
    r007 = next(rule for rule in pack.rules if rule.id == "R-007")
    assert config.r006_unspent_gold_min == int(r006.params["unspent_gold_min"])
    assert config.r007_hp_fraction_max == float(r007.params["hp_fraction_max"])
    assert config.r007_unspent_gold_min == int(r007.params["unspent_gold_min"])


def test_real_h7_gst_and_riot_fixture_build_episodes() -> None:
    patch = bundled_patch()
    engine = RuleEngine(load_rule_pack(), patch=patch)
    r6_gst = r006_fire()
    r6_findings = engine.run(r6_gst, 1)
    r6_episodes = build_coaching_episodes(r6_gst, r6_findings, 1, patch=patch)
    if r6_findings:
        assert r6_episodes
        assert all(item.schema_version == COACHING_EPISODE_SCHEMA_VERSION for item in r6_episodes)
    fixture = load_gst("NA1_fixture_a")
    t_ms = min(300_000, fixture.duration_ms // 2)
    synthetic = _finding(finding_id="fx", rule_id="R-001", t_ms=t_ms)
    patch_fx = bundled_patch(fixture.patch)
    episode = build_coaching_episodes(fixture, [synthetic], 1, patch=patch_fx)[0]
    assert episode.match_id == fixture.match_id
    assert episode.samples
    visual = {Source.VISUAL, Source.VISUAL_INFERRED, Source.CV}
    assert not any(row.source in visual for row in episode.fact_refs)
    r7_findings = engine.run(r007_fire(), 1)
    build_coaching_episodes(r007_fire(), r7_findings, 1, patch=patch)


def test_h7_full_roster_quiet_frames_do_not_raise() -> None:
    gst = make_gst(quiet_frames(180_000), roster(), match_id="c1_quiet", duration_ms=180_000)
    item = _finding(finding_id="p1", rule_id="P-001", t_ms=90_000)
    episodes = build_coaching_episodes(gst, [item], 1, patch=bundled_patch())
    assert len(episodes) == 1
    assert episodes[0].samples[0].unspent_gold is not None


def test_c1_sources_forbid_visual_llm_and_replay_imports() -> None:
    forbidden = (
        "riftlens.visual",
        "riftlens.replay_host",
        "riftlens.coaching.providers",
        "riftlens.coaching.composer",
        "openai",
        "anthropic",
    )
    for path in _CONTEXT_ROOT.rglob("*.py"):
        for line in path.read_text(encoding="utf-8").splitlines():
            stripped = line.strip()
            if stripped.startswith("#"):
                continue
            if stripped.startswith("from ") or stripped.startswith("import "):
                for token in forbidden:
                    assert token not in stripped, f"{path} imports {token}"
