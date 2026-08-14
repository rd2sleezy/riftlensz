"""V.5 trajectory/continuity subject-cue tests. Deterministic fixtures only."""

from __future__ import annotations

from riftlens.domain.enums import FactKind, Team
from riftlens.domain.observation import CameraControl, VisualClaimKind
from riftlens.domain.observation.common import ScreenRect
from riftlens.visual.continuity import (
    CueType,
    CueVerdict,
    evaluate_continuity,
)
from riftlens.visual.correlate import CorrelationStatus, SubjectCorrelation, correlate_subject
from riftlens.visual.correlate_v5 import refine_subject_correlation
from riftlens.visual.gst_align import align_gst
from riftlens.visual.track import (
    CandidateKind,
    EntityTrack,
    TeamEstimate,
    TrackLifecycle,
    TrackObservation,
)
from riftlens.visual.trajectory import MotionClass, classify_motion, measure_trajectory
from tests.helpers.gst import fact, make_gst, make_participant

_MATCH = "NA1_V5_SYNTH"
_PID = 6


def _obs(
    frame: int,
    *,
    t_ms: int,
    x: int,
    y: int = 80,
    w: int = 104,
    h: int = 40,
    confidence: float = 0.7,
) -> TrackObservation:
    return TrackObservation(
        frame_index=frame,
        game_t_ms=t_ms,
        region=ScreenRect(x=x, y=y, width=w, height=h),
        confidence=confidence,
        lifecycle=TrackLifecycle.PRESENT,
        team_estimate=TeamEstimate.UNKNOWN,
        team_confidence=0.0,
    )


def _track(
    track_id: str,
    observations: tuple[TrackObservation, ...],
    *,
    team: TeamEstimate = TeamEstimate.ALLY,
) -> EntityTrack:
    return EntityTrack(
        track_id=track_id,
        kind=CandidateKind.CHAMPION_LIKE,
        observations=observations,
        first_seen_game_t_ms=observations[0].game_t_ms,
        last_seen_game_t_ms=observations[-1].game_t_ms,
        confidence=0.7,
        team_estimate=team,
        team_confidence=0.55,
        events=(),
        ambiguous=False,
    )


def _likely(track_id: str, conf: float = 0.55) -> SubjectCorrelation:
    return SubjectCorrelation(
        status=CorrelationStatus.LIKELY,
        track_id=track_id,
        participant_id=_PID,
        champion_id="Vladimir",
        confidence=conf,
        method="gst_death_alignment",
        claim_kind=VisualClaimKind.INFERRED,
        reasons=("synthetic",),
        conflicts=(),
    )


def _gst_with_death(death_t: int):
    return make_gst(
        [
            fact(
                death_t,
                FactKind.CHAMPION_KILL,
                _PID,
                {"killerId": 1, "victimId": _PID},
            )
        ],
        participants={_PID: make_participant(_PID, team=Team.RED, champion="Vladimir")},
        match_id=_MATCH,
        duration_ms=2_000_000,
    )


def test_smooth_continuous_track_into_death() -> None:
    death = 903_411
    observations = tuple(
        _obs(i, t_ms=death - 2_000 + i * 250, x=100 + i * 25) for i in range(9)
    )
    track = _track("trk_0003", observations)
    bundle = evaluate_continuity(track, death_t_ms=death, all_tracks=(track,))
    assert bundle.trajectory is not None
    assert bundle.trajectory.motion_class is MotionClass.SMOOTH_MOVING
    pre = next(c for c in bundle.cues if c.cue_type is CueType.PRE_DEATH_CONTINUITY)
    assert pre.verdict is CueVerdict.SUPPORT
    prox = next(c for c in bundle.cues if c.cue_type is CueType.DEATH_TIME_PROXIMITY)
    assert prox.verdict is CueVerdict.SUPPORT


def test_stationary_but_continuous_track() -> None:
    death = 100_000
    observations = tuple(_obs(i, t_ms=death - 1_500 + i * 250, x=200) for i in range(7))
    track = _track("trk_s", observations)
    assert classify_motion(observations) is MotionClass.STATIONARY
    bundle = evaluate_continuity(track, death_t_ms=death, all_tracks=(track,))
    motion = next(c for c in bundle.cues if c.cue_type is CueType.MOTION_CONTINUITY)
    assert motion.verdict is CueVerdict.SUPPORT


def test_fragmented_track_with_small_acceptable_gaps() -> None:
    death = 200_000
    # 500 ms gap once — acceptable.
    times = [death - 2_000, death - 1_750, death - 1_250, death - 1_000, death - 750, death - 250]
    observations = tuple(_obs(i, t_ms=t, x=120 + i * 3) for i, t in enumerate(times))
    track = _track("trk_gap_ok", observations)
    bundle = evaluate_continuity(track, death_t_ms=death, all_tracks=(track,))
    pre = next(c for c in bundle.cues if c.cue_type is CueType.PRE_DEATH_CONTINUITY)
    assert pre.verdict in {CueVerdict.SUPPORT, CueVerdict.NEUTRAL}
    assert pre.verdict is not CueVerdict.CONFLICT


def test_fragmented_track_with_large_gaps() -> None:
    death = 300_000
    times = [death - 2_800, death - 500, death - 250]
    observations = tuple(_obs(i, t_ms=t, x=100) for i, t in enumerate(times))
    track = _track("trk_gap_bad", observations)
    bundle = evaluate_continuity(track, death_t_ms=death, all_tracks=(track,))
    pre = next(c for c in bundle.cues if c.cue_type is CueType.PRE_DEATH_CONTINUITY)
    assert pre.verdict is CueVerdict.CONFLICT


def test_impossible_screen_jump() -> None:
    death = 400_000
    observations = (
        _obs(0, t_ms=death - 750, x=40),
        _obs(1, t_ms=death - 500, x=40),
        _obs(2, t_ms=death - 250, x=900),  # huge jump
    )
    track = _track("trk_jump", observations)
    assert measure_trajectory(track).motion_class is MotionClass.JUMPY
    bundle = evaluate_continuity(track, death_t_ms=death, all_tracks=(track,))
    motion = next(c for c in bundle.cues if c.cue_type is CueType.MOTION_CONTINUITY)
    assert motion.verdict is CueVerdict.CONFLICT


def test_two_competing_candidate_tracks() -> None:
    death = 500_000
    a = _track(
        "trk_a",
        tuple(_obs(i, t_ms=death - 1_000 + i * 250, x=80) for i in range(5)),
    )
    b = _track(
        "trk_b",
        tuple(_obs(i, t_ms=death - 1_000 + i * 250, x=400) for i in range(5)),
    )
    bundle = evaluate_continuity(a, death_t_ms=death, all_tracks=(a, b))
    prox = next(c for c in bundle.cues if c.cue_type is CueType.DEATH_TIME_PROXIMITY)
    assert prox.verdict is CueVerdict.CONFLICT
    assert prox.raw["unique_disappearance"] is False


def test_track_disappears_near_death() -> None:
    death = 600_000
    observations = tuple(_obs(i, t_ms=death - 1_000 + i * 250, x=150) for i in range(4))
    track = _track("trk_die", observations)
    # last_seen == death - 250
    bundle = evaluate_continuity(track, death_t_ms=death, all_tracks=(track,))
    post = next(c for c in bundle.cues if c.cue_type is CueType.POST_DEATH_ABSENCE)
    assert post.verdict is CueVerdict.SUPPORT


def test_track_remains_clearly_alive_after_death() -> None:
    death = 700_000
    observations = tuple(_obs(i, t_ms=death - 500 + i * 250, x=150) for i in range(10))
    track = _track("trk_alive", observations)
    bundle = evaluate_continuity(track, death_t_ms=death, all_tracks=(track,))
    post = next(c for c in bundle.cues if c.cue_type is CueType.POST_DEATH_ABSENCE)
    assert post.verdict is CueVerdict.CONFLICT


def test_weak_no_motion_evidence() -> None:
    death = 800_000
    observations = (_obs(0, t_ms=death - 100, x=90),)
    track = _track("trk_one", observations)
    cue = measure_trajectory(track)
    assert cue.motion_class is MotionClass.SPARSE
    bundle = evaluate_continuity(track, death_t_ms=death, all_tracks=(track,))
    motion = next(c for c in bundle.cues if c.cue_type is CueType.MOTION_CONTINUITY)
    assert motion.verdict is CueVerdict.NEUTRAL


def test_camera_motion_like_displacement_not_overinterpreted() -> None:
    death = 900_000
    # Large coherent steps (~120px) → CAMERA_LIKE, not SUPPORT identity.
    observations = tuple(_obs(i, t_ms=death - 1_500 + i * 250, x=50 + i * 120) for i in range(7))
    track = _track("trk_cam", observations)
    assert classify_motion(observations) is MotionClass.CAMERA_LIKE
    bundle = evaluate_continuity(track, death_t_ms=death, all_tracks=(track,))
    motion = next(c for c in bundle.cues if c.cue_type is CueType.MOTION_CONTINUITY)
    assert motion.verdict is CueVerdict.NEUTRAL
    assert "camera_like" in motion.reason


def test_team_label_agrees() -> None:
    death = 910_000
    observations = tuple(_obs(i, t_ms=death - 1_000 + i * 250, x=100) for i in range(5))
    track = _track("trk_ally", observations, team=TeamEstimate.ALLY)
    bundle = evaluate_continuity(
        track,
        death_t_ms=death,
        all_tracks=(track,),
        subject_team_label=TeamEstimate.ALLY,
    )
    team = next(c for c in bundle.cues if c.cue_type is CueType.TEAM_LABEL_AGREES)
    assert team.verdict is CueVerdict.SUPPORT
    assert "independence" in team.raw


def test_team_label_conflicts() -> None:
    death = 920_000
    observations = tuple(_obs(i, t_ms=death - 1_000 + i * 250, x=100) for i in range(5))
    track = _track("trk_enemy", observations, team=TeamEstimate.ENEMY)
    bundle = evaluate_continuity(
        track,
        death_t_ms=death,
        all_tracks=(track,),
        subject_team_label=TeamEstimate.ALLY,
    )
    team = next(c for c in bundle.cues if c.cue_type is CueType.TEAM_LABEL_AGREES)
    assert team.verdict is CueVerdict.CONFLICT


def test_trajectory_supports_likely_but_does_not_force_correlated() -> None:
    death = 930_000
    observations = tuple(_obs(i, t_ms=death - 2_000 + i * 250, x=100 + i * 5) for i in range(9))
    track = _track("trk_0003", observations, team=TeamEstimate.ALLY)
    gst = _gst_with_death(death)
    alignment = align_gst(
        gst,
        start_game_ms=death - 12_000,
        end_game_ms=death + 15_000,
        subject_pid=_PID,
        tracks=(track,),
    )
    base = correlate_subject(
        (track,),
        subject_pid=_PID,
        subject_champion="Vladimir",
        alignment=alignment,
        camera_control=CameraControl.UNCONTROLLED,
    )
    assert base.status is CorrelationStatus.LIKELY
    refined = refine_subject_correlation(
        base,
        (track,),
        alignment=alignment,
        camera_control=CameraControl.UNCONTROLLED,
        subject_team_label=TeamEstimate.ALLY,
    )
    assert refined.refined.status is CorrelationStatus.LIKELY
    assert refined.refined.status is not CorrelationStatus.CORRELATED
    assert refined.refined.confidence <= 0.55
    assert refined.identity_change in {"stronger", "unchanged"}


def test_conflicting_trajectory_does_not_swap_identity() -> None:
    death = 940_000
    # Jumpy track that would be LIKELY by death timing alone.
    observations = (
        _obs(0, t_ms=death - 750, x=40),
        _obs(1, t_ms=death - 500, x=40),
        _obs(2, t_ms=death - 250, x=900),
    )
    track = _track("trk_bad", observations)
    base = _likely("trk_bad")
    gst = _gst_with_death(death)
    alignment = align_gst(
        gst,
        start_game_ms=death - 5_000,
        end_game_ms=death + 5_000,
        subject_pid=_PID,
        tracks=(track,),
    )
    refined = refine_subject_correlation(
        base,
        (track,),
        alignment=alignment,
        camera_control=CameraControl.UNCONTROLLED,
    )
    assert refined.refined.status is CorrelationStatus.UNKNOWN
    assert refined.refined.track_id is None
    assert refined.identity_change == "cleared"


def test_no_uncaught_failure_on_sparse_observations() -> None:
    death = 950_000
    track = _track("trk_sparse", (_obs(0, t_ms=death - 50, x=10),))
    bundle = evaluate_continuity(track, death_t_ms=death, all_tracks=(track,))
    assert bundle.trajectory is not None
    refined = refine_subject_correlation(
        _likely("trk_sparse"),
        (track,),
        alignment=align_gst(
            _gst_with_death(death),
            start_game_ms=death - 1_000,
            end_game_ms=death + 1_000,
            subject_pid=_PID,
            tracks=(track,),
        ),
        camera_control=CameraControl.UNCONTROLLED,
    )
    # Sparse may stay LIKELY or clear on conflict; must not raise.
    assert refined.refined.status in {CorrelationStatus.LIKELY, CorrelationStatus.UNKNOWN}


def test_unknown_base_cannot_be_invented_by_trajectory() -> None:
    death = 960_000
    observations = tuple(_obs(i, t_ms=death - 1_000 + i * 250, x=100 + i) for i in range(6))
    track = _track("trk_x", observations)
    base = SubjectCorrelation(
        status=CorrelationStatus.UNKNOWN,
        track_id=None,
        participant_id=None,
        champion_id=None,
        confidence=0.0,
        method="none",
        claim_kind=VisualClaimKind.INFERRED,
        reasons=("no_death",),
        conflicts=(),
    )
    refined = refine_subject_correlation(
        base,
        (track,),
        alignment=align_gst(
            _gst_with_death(death),
            start_game_ms=death - 5_000,
            end_game_ms=death + 5_000,
            subject_pid=_PID,
            tracks=(track,),
        ),
    )
    assert refined.refined.status is CorrelationStatus.UNKNOWN
    assert refined.identity_change == "unchanged"
