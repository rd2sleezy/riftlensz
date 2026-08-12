from __future__ import annotations

import json
from collections.abc import Iterator
from pathlib import Path

import numpy as np
import pytest
from riftlens.domain.capture import (
    CAPTURE_MANIFEST_NAME,
    CaptureArtifactSpec,
    CaptureManifest,
    CaptureMode,
    CaptureStatus,
    RetentionClass,
)
from riftlens.domain.enums import EvidenceKind, FactKind, Source, Team
from riftlens.domain.ids import is_ulid
from riftlens.domain.observation import (
    FRAME_OBSERVATION_SCHEMA_VERSION,
    CameraControl,
    KnowledgeState,
    VisibilityState,
    VisualClaimKind,
    dumps,
    loads_sequence,
)
from riftlens.domain.observation.common import ScreenRect
from riftlens.domain.replay_errors import ReplayError, ReplayErrorCode
from riftlens.visual.correlate import CorrelationStatus, correlate_subject
from riftlens.visual.detect import ViewportCoverage, classify_viewport, detect_champion_like_bars
from riftlens.visual.errors import CaptureNotRequested, CaptureWindowError
from riftlens.visual.gst_align import align_gst
from riftlens.visual.report import (
    StructuredClaim,
    VisualRuleDiagnostic,
    classify_v1_against_claim,
    format_v1_timeline,
)
from riftlens.visual.track import (
    CandidateKind,
    FrameCandidate,
    FrameDetections,
    TeamEstimate,
    TrackLifecycle,
    finalize_tracks,
    track_candidates,
)
from riftlens.visual.v1_analyze import (
    V1_ANALYZER_ID,
    V1_ANALYZER_VERSION,
    analyze_capture_dir_v1,
)
from riftlens.visual.window import (
    CAPTURE_NOT_REQUESTED,
    FindingStamp,
    capture_covers_window,
    capture_request_for_window,
    capture_window_for_finding,
    refuse_automatic_capture,
    require_explicit_capture,
    select_finding,
    typed_from_replay_error,
)
from tests.helpers.gst import fact, make_gst, make_participant

_MATCH = "NA1_5617764200"
_CAPTURE = "01JZ000000V1CAP00000000001"
_SOURCE = "01JZ000000V1SRC00000000001"
_ARTIFACT = "01JZ000000V1ART00000000001"
_CLOCK = "01JZ000000V1CLK00000000001"
_FINDING = "01JZ000000V1FND00000000001"
_REVIEW = "01JZ000000V1REV00000000001"


def _ids() -> Iterator[str]:
    n = 0
    while True:
        n += 1
        yield f"01JZ000000V1AB{n:012d}"


def _id_factory() -> object:
    stream = _ids()
    return lambda: next(stream)


def _rect(x: int, y: int = 80, width: int = 48, height: int = 5) -> ScreenRect:
    return ScreenRect(x=x, y=y, width=width, height=height)


def _cand(
    x: int,
    *,
    y: int = 80,
    ally: bool | None = True,
    confidence: float = 0.6,
) -> FrameCandidate:
    return FrameCandidate(region=_rect(x, y=y), confidence=confidence, ally_like=ally)


def _frames(
    per_frame: list[tuple[FrameCandidate, ...]],
    *,
    start_ms: int = 1_340_000,
    step_ms: int = 250,
    coverage: ViewportCoverage = ViewportCoverage.USEFUL,
) -> tuple[FrameDetections, ...]:
    out: list[FrameDetections] = []
    for index, candidates in enumerate(per_frame):
        out.append(
            FrameDetections(
                frame_index=index,
                game_t_ms=start_ms + index * step_ms,
                candidates=candidates,
                coverage=coverage if isinstance(coverage, ViewportCoverage) else coverage[index],
            )
        )
    return tuple(out)


def _finding(*, t_ms: int = 1_340_491) -> FindingStamp:
    return FindingStamp(
        finding_id=_FINDING,
        rule_id="R-012",
        t_ms=t_ms,
        match_id=_MATCH,
        review_id=_REVIEW,
        t_end_ms=t_ms + 14_174,
        participant_id=9,
        title="Fought into unaccounted-for enemies",
    )


def _green_bar_frame(
    *,
    count: int = 1,
    width: int = 320,
    height: int = 180,
    x: int = 90,
    y0: int = 70,
    enemy: bool = False,
) -> np.ndarray:
    image = np.zeros((height, width, 3), dtype=np.uint8)
    image[:, :] = (18, 22, 28)
    image[40:140, 40:280] = (40, 50, 60)
    color = (220, 40, 40) if enemy else (40, 220, 50)
    for index in range(count):
        y = y0 + index * 18
        image[y : y + 5, x : x + 48] = color
    return image


def _write_webm(path: Path, frames: list[np.ndarray], *, fps: int = 10) -> None:
    import av

    container = av.open(str(path), mode="w")
    stream = container.add_stream("libvpx", rate=fps)
    stream.width = int(frames[0].shape[1])
    stream.height = int(frames[0].shape[0])
    stream.pix_fmt = "yuv420p"
    try:
        stream.bit_rate = 250_000
    except Exception:
        pass
    for image in frames:
        video_frame = av.VideoFrame.from_ndarray(image, format="rgb24")
        for packet in stream.encode(video_frame):
            container.mux(packet)
    for packet in stream.encode():
        container.mux(packet)
    container.close()


def _manifest(
    *, start: int = 1_328_491, end: int = 1_355_491, relative: str = "clip.webm"
) -> dict[str, object]:
    spec = CaptureArtifactSpec(
        id=_ARTIFACT,
        kind="clip",
        relative_path=relative,
        game_t_ms=start,
        sha256="b" * 64,
        bytes=100,
        source_t_ms=start + 623,
    )
    manifest = CaptureManifest(
        capture_id=_CAPTURE,
        source_id=_SOURCE,
        match_id=_MATCH,
        clock_map_id=_CLOCK,
        mode=CaptureMode.CLIP,
        codec="webm",
        fps=30.0,
        requested_start_game_ms=start,
        requested_end_game_ms=end,
        start_source_ms=start + 623,
        end_source_ms=end + 623,
        retention=RetentionClass.EPHEMERAL,
        status=CaptureStatus.COMPLETE,
        created_at_ms=1,
        clock_confidence="GOOD",
        clock_verified=True,
        camera_controlled=False,
        artifacts=(spec,),
    )
    return manifest.to_dict()


def _capture_dir(
    tmp_path: Path,
    frames: list[np.ndarray],
    *,
    fps: int = 10,
    start: int = 1_328_491,
    end: int = 1_330_491,
) -> Path:
    folder = tmp_path / "cap"
    folder.mkdir()
    _write_webm(folder / "clip.webm", frames, fps=fps)
    (folder / CAPTURE_MANIFEST_NAME).write_text(
        json.dumps(_manifest(start=start, end=end)), encoding="utf-8"
    )
    return folder


def test_finding_window_maps_game_bounds() -> None:
    plan = capture_window_for_finding(
        _finding(),
        source_id=_SOURCE,
        clock_map_id=_CLOCK,
    )
    assert plan.start_game_ms == 1_340_491 - 12_000
    assert plan.end_game_ms == 1_340_491 + 15_000
    assert plan.duration_ms == 27_000
    assert plan.auto_capture is False
    assert plan.clock_map_id == _CLOCK
    assert plan.source_id == _SOURCE
    request = capture_request_for_window(plan)
    assert request.source_id == _SOURCE
    assert request.start_game_ms == plan.start_game_ms
    assert request.end_game_ms == plan.end_game_ms
    assert request.mode is CaptureMode.CLIP
    assert request.review_id == _REVIEW


def test_window_clips_near_match_bounds() -> None:
    early = capture_window_for_finding(_finding(t_ms=3_000), match_duration_ms=1_800_000)
    assert early.start_game_ms == 0
    assert early.clipped_start is True
    late = capture_window_for_finding(_finding(t_ms=1_790_000), match_duration_ms=1_800_000)
    assert late.end_game_ms == 1_800_000
    assert late.clipped_end is True
    with pytest.raises(CaptureWindowError, match="empty"):
        capture_window_for_finding(_finding(t_ms=0), pad_before_ms=0, pad_after_ms=0)


def test_selects_r012_near_preferred_timestamp() -> None:
    findings = (
        _finding(t_ms=441_593),
        FindingStamp(
            finding_id="01JZ000000V1FND00000000002",
            rule_id="R-012",
            t_ms=1_340_491,
            match_id=_MATCH,
            review_id=_REVIEW,
            participant_id=9,
        ),
        FindingStamp(
            finding_id="01JZ000000V1FND00000000003",
            rule_id="R-001",
            t_ms=1_340_000,
            match_id=_MATCH,
        ),
    )
    chosen = select_finding(findings, prefer_t_ms=1_340_000)
    assert chosen.t_ms == 1_340_491


def test_no_automatic_production_capture() -> None:
    plan = capture_window_for_finding(_finding(), source_id=_SOURCE, clock_map_id=_CLOCK)
    outcome = refuse_automatic_capture(plan)
    assert outcome.ok is False
    assert outcome.code == CAPTURE_NOT_REQUESTED
    with pytest.raises(CaptureNotRequested):
        require_explicit_capture(False, plan)
    typed = typed_from_replay_error(ReplayError(ReplayErrorCode.CAPTURE_RECORDING_FAILED))
    assert typed.ok is False
    assert typed.code == ReplayErrorCode.CAPTURE_RECORDING_FAILED.value


def test_existing_capture_linkage_and_no_hardcoded_rofl() -> None:
    assert capture_covers_window(
        capture_start_game_ms=1_328_000,
        capture_end_game_ms=1_356_000,
        window_start_game_ms=1_328_491,
        window_end_game_ms=1_355_491,
    )
    source = Path("riftlens/visual/window.py").read_text(encoding="utf-8")
    assert ".rofl" not in source
    assert "Documents" not in source
    request = capture_request_for_window(
        capture_window_for_finding(_finding(), source_id=_SOURCE, clock_map_id=_CLOCK)
    )
    assert not hasattr(request, "rofl_path")


def test_track_one_moving_candidate() -> None:
    frames = _frames([(_cand(40 + index * 8),) for index in range(8)])
    tracks = finalize_tracks(track_candidates(frames))
    champion = [item for item in tracks if item.kind is CandidateKind.CHAMPION_LIKE]
    assert len(champion) == 1
    assert champion[0].track_id == "trk_0001"
    assert champion[0].observation_count == 8
    assert champion[0].events[0].kind is TrackLifecycle.ENTERED_VIEW


def test_track_two_separate_candidates() -> None:
    frames = _frames([(_cand(40), _cand(180, ally=False)) for _ in range(6)])
    tracks = finalize_tracks(track_candidates(frames))
    champion = [item for item in tracks if item.kind is CandidateKind.CHAMPION_LIKE]
    assert len(champion) == 2
    teams = {item.team_estimate for item in champion}
    assert TeamEstimate.ALLY in teams
    assert TeamEstimate.ENEMY in teams


def test_crossing_does_not_swap_identity() -> None:
    opposite = _frames(
        [
            (_cand(20), _cand(200, ally=False)),
            (_cand(50), _cand(170, ally=False)),
            (_cand(80), _cand(140, ally=False)),
            (_cand(110), _cand(110, y=82, ally=False)),
            (_cand(140), _cand(80, ally=False)),
        ]
    )
    first = finalize_tracks(track_candidates(opposite))
    second = finalize_tracks(track_candidates(opposite))
    assert [item.track_id for item in first] == [item.track_id for item in second]
    teams = {item.track_id: item.team_estimate for item in first}
    assert TeamEstimate.ALLY in teams.values()
    assert TeamEstimate.ENEMY in teams.values()
    same = _frames(
        [
            (_cand(20), _cand(200)),
            (_cand(50), _cand(170)),
            (_cand(80), _cand(140)),
            (_cand(108), _cand(116)),
            (_cand(140), _cand(80)),
        ]
    )
    crossed = finalize_tracks(track_candidates(same))
    # Same-team crossing must not invent a swapped continuous identity.
    early = [item for item in crossed if item.first_seen_game_t_ms == 1_340_000]
    assert len(early) == 2
    assert any(item.ambiguous or item.fragmented for item in crossed) or len(crossed) >= 3


def test_enter_exit_and_temporary_miss() -> None:
    present = (_cand(80),)
    empty: tuple[FrameCandidate, ...] = ()
    missed = [present, present, empty, present, present]
    disappeared = [empty] * 10
    reappeared = [present, present]
    frames = _frames(missed + disappeared + reappeared)
    tracks = finalize_tracks(track_candidates(frames))
    champion = [item for item in tracks if item.kind is CandidateKind.CHAMPION_LIKE]
    assert any(item.observation_count >= 4 for item in champion)
    assert len(champion) >= 2
    assert champion[0].track_id != champion[-1].track_id


def test_static_ui_and_noise_and_empty() -> None:
    static = _frames([(_cand(30, y=40, confidence=0.5),) for _ in range(8)])
    tracks = finalize_tracks(track_candidates(static))
    assert all(item.kind is CandidateKind.NOISE for item in tracks)
    empty = finalize_tracks(track_candidates(_frames([() for _ in range(4)])))
    assert empty == ()
    noisy = _frames([(_cand(40, confidence=0.3),)])
    weak = finalize_tracks(track_candidates(noisy))
    assert weak[0].kind is CandidateKind.UNKNOWN


def test_transition_frame_does_not_invent_candidates() -> None:
    coverages = [
        ViewportCoverage.USEFUL,
        ViewportCoverage.TRANSITION,
        ViewportCoverage.OBSTRUCTED,
        ViewportCoverage.USEFUL,
    ]
    frames = _frames(
        [(_cand(80),), (_cand(80),), (_cand(80),), (_cand(88),)],
        coverage=coverages,  # type: ignore[arg-type]
    )
    tracks = finalize_tracks(track_candidates(frames))
    assert tracks
    observed_indexes = {
        item.frame_index
        for track in tracks
        for item in track.observations
    }
    assert 1 not in observed_indexes
    assert 2 not in observed_indexes


def test_confidence_does_not_increase_on_miss() -> None:
    frames = _frames([(_cand(80, confidence=0.5),), (), (_cand(84, confidence=0.9),)])
    tracks = track_candidates(frames)
    assert tracks[0].confidence <= 0.5 + 0.06 + 1e-9


def test_team_classification_synthetic_bars() -> None:
    green = detect_champion_like_bars(_green_bar_frame(count=1, enemy=False))
    red = detect_champion_like_bars(_green_bar_frame(count=1, enemy=True))
    assert green and green[0].ally_like is True
    assert red and red[0].ally_like is False
    assert classify_viewport(_green_bar_frame()) is ViewportCoverage.USEFUL
    assert classify_viewport(np.zeros((180, 320, 3), dtype=np.uint8)) is ViewportCoverage.OBSTRUCTED


def test_subject_correlation_unknown_without_gst() -> None:
    frames = _frames([(_cand(80),) for _ in range(5)])
    tracks = finalize_tracks(track_candidates(frames))
    result = correlate_subject(tracks, subject_pid=9, capture_review_pid=9)
    assert result.status is CorrelationStatus.UNKNOWN
    assert result.participant_id is None
    team_only = correlate_subject(tracks, subject_pid=9, team_implies_identity=True)
    assert team_only.status is CorrelationStatus.UNKNOWN
    owned = correlate_subject(tracks, subject_pid=None, capture_review_pid=9)
    assert owned.status is CorrelationStatus.UNKNOWN


def test_death_alignment_likely_and_conflicts_unknown() -> None:
    frames = _frames([(_cand(80),) for _ in range(6)] + [() for _ in range(4)])
    tracks = finalize_tracks(track_candidates(frames))
    death_t = tracks[0].last_seen_game_t_ms
    gst = make_gst(
        [
            fact(
                death_t,
                FactKind.CHAMPION_KILL,
                9,
                {"killerId": 2, "victimId": 9},
            )
        ],
        participants={9: make_participant(9, team=Team.RED, champion="Kaisa")},
        match_id=_MATCH,
        duration_ms=1_800_000,
    )
    alignment = align_gst(
        gst,
        start_game_ms=1_340_000,
        end_game_ms=1_350_000,
        subject_pid=9,
        tracks=tracks,
    )
    assert alignment.mutated_gst is False
    likely = correlate_subject(
        tracks,
        subject_pid=9,
        subject_champion="Kaisa",
        alignment=alignment,
        capture_review_pid=9,
    )
    assert likely.status is CorrelationStatus.LIKELY
    assert likely.track_id == tracks[0].track_id
    assert likely.confidence <= 0.55
    assert likely.claim_kind is VisualClaimKind.INFERRED
    extra = list(frames)
    extra[0] = FrameDetections(
        frame_index=0,
        game_t_ms=1_340_000,
        candidates=(_cand(80), _cand(180, ally=False)),
        coverage=ViewportCoverage.USEFUL,
    )
    # Two tracks disappearing at the same death → UNKNOWN
    both = _frames([(_cand(80), _cand(180, ally=False)) for _ in range(6)] + [() for _ in range(4)])
    both_tracks = finalize_tracks(track_candidates(both))
    conflicted = correlate_subject(
        both_tracks,
        subject_pid=9,
        alignment=align_gst(
            gst,
            start_game_ms=1_340_000,
            end_game_ms=1_350_000,
            subject_pid=9,
            tracks=both_tracks,
        ),
    )
    assert conflicted.status is CorrelationStatus.UNKNOWN
    strong = correlate_subject(
        tracks,
        subject_pid=9,
        subject_champion="Kaisa",
        alignment=alignment,
        camera_control=CameraControl.CONTROLLED_SUBJECT,
        subject_team_estimate=TeamEstimate.ALLY,
        assume_subject_perspective_hud=True,
    )
    assert strong.status is CorrelationStatus.CORRELATED
    assert strong.confidence <= 0.75


def test_v1_emits_r11_and_keeps_visual_provenance(tmp_path: Path) -> None:
    frames = [_green_bar_frame(count=1, x=90 + index) for index in range(12)]
    folder = _capture_dir(tmp_path, frames, fps=10, start=1_328_491, end=1_329_691)
    result = analyze_capture_dir_v1(
        folder,
        fps=4.0,
        id_factory=_id_factory(),  # type: ignore[arg-type]
        subject_pid=9,
        subject_champion="Kaisa",
        capture_review_pid=9,
    )
    sequence = result.sequence
    assert sequence.detector_id == V1_ANALYZER_ID
    assert sequence.detector_version == V1_ANALYZER_VERSION
    assert sequence.schema_version == FRAME_OBSERVATION_SCHEMA_VERSION
    assert sequence.match_id == _MATCH
    assert sequence.capture_interval_id == _CAPTURE
    assert sequence.media_artifact_id == _ARTIFACT
    assert sequence.gameplay_source_id == _SOURCE
    assert sequence.clock_map_id == _CLOCK
    assert sequence.frames
    first = sequence.frames[0]
    assert first.source is Source.VISUAL
    assert first.claim_kind is VisualClaimKind.OBSERVED
    assert first.camera.control is CameraControl.UNCONTROLLED
    for entity in first.entities:
        assert entity.participant_id is None
        assert entity.champion_id is None
        assert entity.visibility is VisibilityState.VISIBLE
        assert is_ulid(entity.entity_observation_id)
    encoded = dumps(sequence)
    assert dumps(loads_sequence(encoded)) == encoded
    for inferred in result.inferred_frames:
        assert inferred.source is Source.VISUAL_INFERRED
        assert inferred.source is not Source.RIOT_TIMELINE
        assert inferred.claim_kind is VisualClaimKind.INFERRED
    timeline = format_v1_timeline(result)
    assert "bad fight" not in timeline
    assert "overextended" not in timeline
    assert "fog of war" not in timeline.lower()
    diagnostic = classify_v1_against_claim(
        result,
        StructuredClaim(
            rule_id="R-012",
            t_ms=1_328_800,
            summary="Fought into unaccounted-for enemies",
        ),
    )
    assert diagnostic in {
        VisualRuleDiagnostic.PARTIALLY_SUPPORTED,
        VisualRuleDiagnostic.INSUFFICIENT_VISUAL_EVIDENCE,
    }


def test_v1_does_not_mutate_coaching() -> None:
    from riftlens.analysis.rules.engine import RuleEngine
    from riftlens.analysis.rules.loader import load_rule_pack
    from tests.helpers.gst import bundled_patch, load_gst

    gst = load_gst("NA1_fixture_a")
    pack = load_rule_pack()
    patch = bundled_patch(gst.patch)
    before = [
        (item.rule_id, item.t_ms, item.title, item.severity.value)
        for item in RuleEngine(pack, patch=patch).run(gst, 5)
    ]
    import riftlens.visual as visual_spike

    assert visual_spike.V1_ANALYZER_ID == V1_ANALYZER_ID
    after = [
        (item.rule_id, item.t_ms, item.title, item.severity.value)
        for item in RuleEngine(pack, patch=patch).run(gst, 5)
    ]
    assert before == after
    assert not any(
        item.kind is EvidenceKind.FRAME
        for finding in RuleEngine(pack, patch=patch).run(gst, 5)
        for item in finding.evidence
    )


def test_hud_remains_unknown(tmp_path: Path) -> None:
    frames = [_green_bar_frame(count=1) for _ in range(6)]
    folder = _capture_dir(tmp_path, frames, fps=10, start=1_328_491, end=1_329_091)
    result = analyze_capture_dir_v1(folder, fps=4.0, id_factory=_id_factory())  # type: ignore[arg-type]
    for frame in result.sequence.frames:
        assert frame.hud is not None
        assert frame.hud.get("health").knowledge is KnowledgeState.UNKNOWN
        assert frame.spatial is not None
        assert frame.spatial.minimap_visible is KnowledgeState.UNKNOWN
