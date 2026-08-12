"""V.4 spectator team-color calibration tests. Deterministic fixtures only."""

from __future__ import annotations

from dataclasses import replace

import numpy as np
from riftlens.domain.enums import Team
from riftlens.domain.observation import VisualClaimKind
from riftlens.domain.observation.common import ScreenRect
from riftlens.visual.color_sample import (
    BarColorSample,
    hue_is_blue_like,
    hue_is_red_like,
    sample_bar_color,
)
from riftlens.visual.correlate import CorrelationStatus, SubjectCorrelation
from riftlens.visual.detect_v4 import detect_blue_team_bars, detect_champion_like_entities_v4
from riftlens.visual.team_calibrate import (
    CALIBRATION_VERSION,
    CalibrationConfidence,
    SpectatorColorClass,
    TeamColorAnchor,
    apply_labels_to_tracks,
    build_calibration,
    classify_color_sample,
    label_track,
    relative_team,
)
from riftlens.visual.track import (
    CandidateKind,
    EntityTrack,
    TeamEstimate,
    TrackLifecycle,
    TrackObservation,
)


def _sample(
    *,
    hue: float,
    sat: float = 200.0,
    val: float = 200.0,
    usable: bool = True,
    pixels: int = 40,
) -> BarColorSample:
    return BarColorSample(
        hue_median=hue,
        sat_median=sat,
        val_median=val,
        hue_p25=hue - 2,
        hue_p75=hue + 2,
        sample_pixels=pixels,
        usable=usable,
    )


def _track(
    track_id: str,
    *,
    n: int = 4,
    kind: CandidateKind = CandidateKind.CHAMPION_LIKE,
) -> EntityTrack:
    observations = tuple(
        TrackObservation(
            frame_index=i,
            game_t_ms=900_000 + i * 250,
            region=ScreenRect(x=100, y=80, width=104, height=40),
            confidence=0.7,
            lifecycle=TrackLifecycle.PRESENT if n > 1 else TrackLifecycle.ENTERED_VIEW,
            team_estimate=TeamEstimate.UNKNOWN,
            team_confidence=0.0,
        )
        for i in range(n)
    )
    return EntityTrack(
        track_id=track_id,
        kind=kind,
        observations=observations,
        first_seen_game_t_ms=observations[0].game_t_ms,
        last_seen_game_t_ms=observations[-1].game_t_ms,
        confidence=0.7,
        team_estimate=TeamEstimate.UNKNOWN,
        team_confidence=0.0,
        events=(),
        ambiguous=False,
    )


def _paint_bar(
    image: np.ndarray,
    *,
    x: int,
    y: int,
    color: tuple[int, int, int],
    width: int = 104,
    height: int = 9,
) -> None:
    image[y : y + height, x : x + width] = color


def test_hue_helpers_cover_spectator_red_and_blue() -> None:
    assert hue_is_red_like(5.0)
    assert hue_is_red_like(175.0)
    assert hue_is_blue_like(105.0)
    assert not hue_is_red_like(105.0)
    assert not hue_is_blue_like(5.0)


def test_sample_bar_color_rejects_grey_and_tiny_regions() -> None:
    image = np.zeros((120, 320, 3), dtype=np.uint8)
    image[:, :] = (40, 40, 40)
    grey = sample_bar_color(image, ScreenRect(x=10, y=10, width=80, height=8))
    assert grey.usable is False or grey.sat_median < 80
    tiny = sample_bar_color(image, ScreenRect(x=10, y=10, width=2, height=2))
    assert tiny.usable is False


def test_sample_bar_color_reads_red_and_blue_bars() -> None:
    image = np.zeros((180, 320, 3), dtype=np.uint8)
    image[:, :] = (18, 22, 28)
    _paint_bar(image, x=40, y=60, color=(220, 40, 40))  # RGB red
    _paint_bar(image, x=160, y=60, color=(40, 120, 220))  # RGB blue
    red = sample_bar_color(image, ScreenRect(x=40, y=60, width=104, height=9))
    blue = sample_bar_color(image, ScreenRect(x=160, y=60, width=104, height=9))
    assert red.usable
    assert blue.usable
    assert classify_color_sample(red) is SpectatorColorClass.RED_LIKE
    assert classify_color_sample(blue) is SpectatorColorClass.BLUE_LIKE


def test_low_saturation_sample_is_unknown() -> None:
    assert (
        classify_color_sample(_sample(hue=5.0, sat=20.0, val=200.0))
        is SpectatorColorClass.UNKNOWN
    )


def test_detect_blue_team_bars_finds_spectator_blue() -> None:
    image = np.zeros((360, 640, 3), dtype=np.uint8)
    image[:, :] = (18, 22, 28)
    image[80:200, 80:560] = (40, 50, 60)
    _paint_bar(image, x=200, y=100, color=(40, 140, 220), width=104, height=9)
    bars = detect_blue_team_bars(image)
    assert len(bars) >= 1
    assert all(bar.ally_like is None for bar in bars)


def test_v4_entities_defer_team_until_calibration() -> None:
    image = np.zeros((360, 640, 3), dtype=np.uint8)
    image[:, :] = (18, 22, 28)
    image[80:220, 80:560] = (40, 50, 60)
    _paint_bar(image, x=180, y=110, color=(220, 40, 40), width=104, height=9)
    entities = detect_champion_like_entities_v4(image)
    assert all(item.ally_like is None for item in entities)


def test_relative_team_uses_subject_riot_team() -> None:
    assert relative_team(Team.RED, subject_team=Team.RED) is TeamEstimate.ALLY
    assert relative_team(Team.BLUE, subject_team=Team.RED) is TeamEstimate.ENEMY
    assert relative_team(None, subject_team=Team.RED) is TeamEstimate.UNKNOWN


def test_spectator_prior_without_anchors_is_weak() -> None:
    calib = build_calibration(
        subject_team=Team.RED,
        correlation=None,
        track_colors={},
    )
    assert calib.confidence is CalibrationConfidence.WEAK
    assert calib.red_like_team is Team.RED
    assert calib.blue_like_team is Team.BLUE


def test_single_likely_subject_anchor_stays_weak_not_verified() -> None:
    correlation = SubjectCorrelation(
        status=CorrelationStatus.LIKELY,
        track_id="trk_0003",
        participant_id=6,
        champion_id="Vladimir",
        confidence=0.55,
        method="gst_death_alignment",
        claim_kind=VisualClaimKind.INFERRED,
        reasons=("death",),
        conflicts=(),
    )
    calib = build_calibration(
        subject_team=Team.RED,
        correlation=correlation,
        track_colors={"trk_0003": SpectatorColorClass.RED_LIKE},
    )
    assert calib.confidence is CalibrationConfidence.WEAK
    assert calib.confidence is not CalibrationConfidence.VERIFIED
    assert calib.red_like_team is Team.RED
    assert len(calib.anchors) == 1
    assert calib.anchors[0].confidence <= 0.55


def test_two_cluster_agreeing_anchors_reach_good() -> None:
    anchors = (
        TeamColorAnchor(
            track_id="a",
            riot_team=Team.RED,
            color=SpectatorColorClass.RED_LIKE,
            confidence=0.55,
            reason="subject",
        ),
        TeamColorAnchor(
            track_id="b",
            riot_team=Team.BLUE,
            color=SpectatorColorClass.BLUE_LIKE,
            confidence=0.55,
            reason="death",
        ),
    )
    calib = build_calibration(
        subject_team=Team.RED,
        correlation=None,
        track_colors={},
        extra_anchors=anchors,
    )
    assert calib.confidence is CalibrationConfidence.GOOD
    assert calib.red_like_team is Team.RED
    assert calib.blue_like_team is Team.BLUE


def test_verified_requires_strong_multi_anchors() -> None:
    anchors = (
        TeamColorAnchor(
            track_id="a",
            riot_team=Team.RED,
            color=SpectatorColorClass.RED_LIKE,
            confidence=0.8,
            reason="strong_a",
        ),
        TeamColorAnchor(
            track_id="b",
            riot_team=Team.BLUE,
            color=SpectatorColorClass.BLUE_LIKE,
            confidence=0.8,
            reason="strong_b",
        ),
    )
    calib = build_calibration(
        subject_team=Team.RED,
        correlation=None,
        track_colors={},
        extra_anchors=anchors,
    )
    assert calib.confidence is CalibrationConfidence.VERIFIED


def test_conflicting_anchors_yield_unavailable() -> None:
    anchors = (
        TeamColorAnchor(
            track_id="a",
            riot_team=Team.RED,
            color=SpectatorColorClass.RED_LIKE,
            confidence=0.8,
            reason="a",
        ),
        TeamColorAnchor(
            track_id="b",
            riot_team=Team.BLUE,
            color=SpectatorColorClass.RED_LIKE,
            confidence=0.8,
            reason="b",
        ),
    )
    calib = build_calibration(
        subject_team=Team.RED,
        correlation=None,
        track_colors={},
        extra_anchors=anchors,
    )
    assert calib.confidence is CalibrationConfidence.UNAVAILABLE
    assert calib.red_like_team is None


def test_insufficient_subject_team_is_unavailable() -> None:
    calib = build_calibration(subject_team=None, correlation=None, track_colors={})
    assert calib.confidence is CalibrationConfidence.UNAVAILABLE


def test_stable_track_majority_beats_one_bad_frame() -> None:
    calib = build_calibration(
        subject_team=Team.RED,
        correlation=None,
        track_colors={},
    )
    samples = [
        _sample(hue=5.0),
        _sample(hue=4.0),
        _sample(hue=6.0),
        _sample(hue=110.0),  # one noisy blue frame
        _sample(hue=3.0),
    ]
    label = label_track(_track("trk_1", n=5), samples, calib)
    assert label.team_class is TeamEstimate.ALLY  # red subject, red bars
    assert label.evidence_count == 5
    assert label.calibration_version == CALIBRATION_VERSION


def test_conflicting_track_evidence_is_unknown() -> None:
    calib = build_calibration(
        subject_team=Team.RED,
        correlation=None,
        track_colors={},
    )
    samples = [_sample(hue=5.0), _sample(hue=110.0), _sample(hue=4.0), _sample(hue=112.0)]
    label = label_track(_track("trk_conflict", n=4), samples, calib)
    assert label.team_class is TeamEstimate.UNKNOWN


def test_one_frame_track_confidence_capped() -> None:
    calib = build_calibration(
        subject_team=Team.RED,
        correlation=None,
        track_colors={},
    )
    label = label_track(_track("trk_short", n=1), [_sample(hue=5.0)], calib)
    assert label.team_class is TeamEstimate.ALLY
    assert label.confidence <= 0.4


def test_unknown_calibration_produces_unknown_tracks() -> None:
    calib = build_calibration(subject_team=None, correlation=None, track_colors={})
    label = label_track(_track("trk_x", n=3), [_sample(hue=5.0)] * 3, calib)
    assert label.team_class is TeamEstimate.UNKNOWN
    assert label.confidence == 0.0


def test_apply_labels_does_not_force_noise_tracks() -> None:
    calib = build_calibration(
        subject_team=Team.RED,
        correlation=None,
        track_colors={},
    )
    noise = _track("noise", n=2, kind=CandidateKind.NOISE)
    label = label_track(noise, [_sample(hue=5.0), _sample(hue=5.0)], calib)
    labeled = apply_labels_to_tracks([noise], {"noise": label})
    assert labeled[0].team_estimate is TeamEstimate.UNKNOWN


def test_downstream_confidence_bounded_by_cap() -> None:
    calib = replace(
        build_calibration(subject_team=Team.RED, correlation=None, track_colors={}),
        confidence=CalibrationConfidence.GOOD,
    )
    samples = [_sample(hue=5.0)] * 8
    label = label_track(_track("trk_long", n=8), samples, calib)
    assert label.confidence <= 0.7


def test_weak_calibration_bounds_track_confidence() -> None:
    correlation = SubjectCorrelation(
        status=CorrelationStatus.LIKELY,
        track_id="trk_0003",
        participant_id=6,
        champion_id="Vladimir",
        confidence=0.55,
        method="gst_death_alignment",
        claim_kind=VisualClaimKind.INFERRED,
        reasons=("death",),
        conflicts=(),
    )
    calib = build_calibration(
        subject_team=Team.RED,
        correlation=correlation,
        track_colors={"trk_0003": SpectatorColorClass.RED_LIKE},
    )
    assert calib.confidence is CalibrationConfidence.WEAK
    label = label_track(_track("trk_0003", n=4), [_sample(hue=5.0)] * 4, calib)
    assert label.confidence <= 0.55


def test_disappearing_near_ignores_post_death_flashes() -> None:
    from riftlens.visual.gst_align import disappearing_near

    before = _track("before", n=3)
    before = replace(
        before,
        first_seen_game_t_ms=900_000,
        last_seen_game_t_ms=902_500,
        observations=tuple(
            replace(item, game_t_ms=900_000 + i * 250) for i, item in enumerate(before.observations)
        ),
    )
    after = _track("after", n=1)
    after = replace(
        after,
        first_seen_game_t_ms=904_000,
        last_seen_game_t_ms=904_000,
        observations=(
            replace(after.observations[0], game_t_ms=904_000, frame_index=0),
        ),
    )
    near = disappearing_near((before, after), 903_000, window_ms=2_000)
    assert [item.track_id for item in near] == ["before"]


def test_selected_bar_outline_variation_still_classifies() -> None:
    """Bright selected outline should not flip red→blue if core is red."""
    image = np.zeros((180, 320, 3), dtype=np.uint8)
    image[:, :] = (18, 22, 28)
    # Core red bar with a thin bright border.
    _paint_bar(image, x=40, y=60, color=(240, 240, 240), width=108, height=11)
    _paint_bar(image, x=42, y=61, color=(220, 40, 40), width=104, height=9)
    sample = sample_bar_color(image, ScreenRect(x=42, y=61, width=104, height=9))
    assert sample.usable
    assert classify_color_sample(sample) is SpectatorColorClass.RED_LIKE
