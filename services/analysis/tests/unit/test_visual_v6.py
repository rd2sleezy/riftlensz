"""V.6 death-window candidate ranking tests. Deterministic fixtures only."""

from __future__ import annotations

from riftlens.domain.enums import FactKind, Team
from riftlens.domain.observation import CameraControl, VisualClaimKind
from riftlens.domain.observation.common import ScreenRect
from riftlens.visual.correlate import (
    LIKELY_CONFIDENCE_CAP,
    CorrelationStatus,
    SubjectCorrelation,
    correlate_subject,
)
from riftlens.visual.correlate_v6 import refine_with_death_ranking
from riftlens.visual.death_candidate import CANDIDATE_POOL_MS, rank_death_candidates
from riftlens.visual.gst_align import DEATH_ALIGN_MS, align_gst
from riftlens.visual.track import (
    CandidateKind,
    EntityTrack,
    TeamEstimate,
    TrackLifecycle,
    TrackObservation,
)
from tests.helpers.gst import fact, make_gst, make_participant

_MATCH = "NA1_V6_SYNTH"
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
    fragmented: bool = False,
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
        fragmented=fragmented,
        closed_reason=TrackLifecycle.LEFT_VIEW,
    )


def _gst(death_t: int):
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


def _alignment(death_t: int, tracks: tuple[EntityTrack, ...] = ()):
    gst = _gst(death_t)
    return align_gst(
        gst,
        start_game_ms=death_t - 20_000,
        end_game_ms=death_t + 20_000,
        subject_pid=_PID,
        tracks=tracks,
    )


def _unknown_base() -> SubjectCorrelation:
    return SubjectCorrelation(
        status=CorrelationStatus.UNKNOWN,
        track_id=None,
        participant_id=None,
        champion_id=None,
        confidence=0.0,
        method="none",
        claim_kind=VisualClaimKind.INFERRED,
        reasons=("synthetic_unknown",),
        conflicts=(),
    )


def _near_death_obs(
    death: int, *, n: int = 8, end_offset: int = -200
) -> tuple[TrackObservation, ...]:
    """Continuous observations ending ``end_offset`` ms from death."""
    last = death + end_offset
    start = last - (n - 1) * 250
    return tuple(_obs(i, t_ms=start + i * 250, x=100 + i * 10) for i in range(n))


def test_unique_candidate_near_death_team_agree_likely() -> None:
    death = 100_000
    track = _track("trk_win", _near_death_obs(death), team=TeamEstimate.ALLY)
    result = refine_with_death_ranking(
        _unknown_base(),
        (track,),
        alignment=_alignment(death, (track,)),
        subject_pid=_PID,
        subject_champion="Vladimir",
        subject_team_label=TeamEstimate.ALLY,
    )
    assert result.refined.status is CorrelationStatus.LIKELY
    assert result.refined.track_id == "trk_win"
    assert result.identity_change == "promoted"
    assert result.refined.confidence <= LIKELY_CONFIDENCE_CAP


def test_two_similar_candidates_unknown() -> None:
    death = 200_000
    a = _track("trk_a", _near_death_obs(death, end_offset=-200), team=TeamEstimate.ALLY)
    b = _track("trk_b", _near_death_obs(death, end_offset=-250), team=TeamEstimate.ALLY)
    result = refine_with_death_ranking(
        _unknown_base(),
        (a, b),
        alignment=_alignment(death, (a, b)),
        subject_pid=_PID,
        subject_team_label=TeamEstimate.ALLY,
    )
    assert result.refined.status is CorrelationStatus.UNKNOWN
    assert result.ranking is not None
    assert result.ranking.reject_reason == "top_candidates_too_close"


def test_alive_after_death_unknown() -> None:
    death = 300_000
    obs = tuple(_obs(i, t_ms=death - 500 + i * 400, x=120) for i in range(8))
    track = _track("trk_alive", obs, team=TeamEstimate.ALLY)
    result = refine_with_death_ranking(
        _unknown_base(),
        (track,),
        alignment=_alignment(death, (track,)),
        subject_pid=_PID,
        subject_team_label=TeamEstimate.ALLY,
    )
    assert result.refined.status is CorrelationStatus.UNKNOWN
    assert result.ranking is not None
    assert any(c.alive_after_death for c in result.ranking.candidates)


def test_team_mismatch_unknown() -> None:
    death = 400_000
    track = _track("trk_enemy", _near_death_obs(death), team=TeamEstimate.ENEMY)
    result = refine_with_death_ranking(
        _unknown_base(),
        (track,),
        alignment=_alignment(death, (track,)),
        subject_pid=_PID,
        subject_team_label=TeamEstimate.ALLY,
    )
    assert result.refined.status is CorrelationStatus.UNKNOWN
    assert result.ranking is not None
    assert "team_mismatch" in result.ranking.candidates[0].conflicts


def test_long_continuous_no_temporal_join_unknown() -> None:
    death = 500_000
    # Ends well before the candidate pool.
    far = death - CANDIDATE_POOL_MS - 3_000
    obs = tuple(_obs(i, t_ms=far - 2_000 + i * 250, x=100 + i) for i in range(10))
    track = _track("trk_far", obs, team=TeamEstimate.ALLY)
    result = refine_with_death_ranking(
        _unknown_base(),
        (track,),
        alignment=_alignment(death, (track,)),
        subject_pid=_PID,
        subject_team_label=TeamEstimate.ALLY,
    )
    assert result.refined.status is CorrelationStatus.UNKNOWN


def test_fragmented_legitimate_continuity_allowed() -> None:
    death = 600_000
    # 500 ms gap once — acceptable under V.5 continuity.
    times = [death - 2_000, death - 1_750, death - 1_250, death - 1_000, death - 750, death - 200]
    obs = tuple(_obs(i, t_ms=t, x=120 + i * 3) for i, t in enumerate(times))
    track = _track("trk_frag_ok", obs, team=TeamEstimate.ALLY, fragmented=True)
    result = refine_with_death_ranking(
        _unknown_base(),
        (track,),
        alignment=_alignment(death, (track,)),
        subject_pid=_PID,
        subject_team_label=TeamEstimate.ALLY,
    )
    assert result.refined.status is CorrelationStatus.LIKELY
    assert result.refined.track_id == "trk_frag_ok"


def test_duplicate_tracks_uniqueness_fail() -> None:
    death = 700_000
    a = _track("trk_dup_a", _near_death_obs(death, end_offset=-100), team=TeamEstimate.ALLY)
    b = _track("trk_dup_b", _near_death_obs(death, end_offset=-150), team=TeamEstimate.ALLY)
    ranking = rank_death_candidates(
        (a, b),
        death_t_ms=death,
        subject_team_label=TeamEstimate.ALLY,
    )
    assert ranking.winner_track_id is None
    assert ranking.reject_reason is not None


def test_trajectory_strengthens_only_valid_candidate() -> None:
    death = 800_000
    # Single sparse observation near death: temporal join possible, no independent support.
    obs = (_obs(0, t_ms=death - 100, x=90),)
    track = _track("trk_sparse", obs, team=TeamEstimate.UNKNOWN)
    result = refine_with_death_ranking(
        _unknown_base(),
        (track,),
        alignment=_alignment(death, (track,)),
        subject_pid=_PID,
        subject_team_label=None,
    )
    assert result.refined.status is CorrelationStatus.UNKNOWN
    assert result.ranking is not None
    assert result.ranking.reject_reason == "temporal_join_without_independent_support"


def test_framing_camera_ownership_alone_unknown() -> None:
    death = 900_000
    track = _track("trk_cam", _near_death_obs(death), team=TeamEstimate.ALLY)
    result = refine_with_death_ranking(
        _unknown_base(),
        (track,),
        alignment=_alignment(death, (track,)),
        subject_pid=_PID,
        subject_team_label=TeamEstimate.ALLY,
        camera_implies_identity=True,
    )
    assert result.refined.status is CorrelationStatus.UNKNOWN
    assert "camera_ownership" in (result.ranking.reject_reason or "")


def test_subject_attachment_alone_unknown() -> None:
    death = 950_000
    track = _track("trk_att", _near_death_obs(death), team=TeamEstimate.ALLY)
    result = refine_with_death_ranking(
        _unknown_base(),
        (track,),
        alignment=_alignment(death, (track,)),
        subject_pid=_PID,
        subject_team_label=TeamEstimate.ALLY,
        subject_attachment_implies_identity=True,
    )
    assert result.refined.status is CorrelationStatus.UNKNOWN


def test_unknown_never_becomes_correlated() -> None:
    death = 1_000_000
    track = _track("trk_ok", _near_death_obs(death), team=TeamEstimate.ALLY)
    result = refine_with_death_ranking(
        _unknown_base(),
        (track,),
        alignment=_alignment(death, (track,)),
        subject_pid=_PID,
        subject_champion="Vladimir",
        camera_control=CameraControl.CONTROLLED_SUBJECT,
        subject_team_label=TeamEstimate.ALLY,
    )
    assert result.refined.status is CorrelationStatus.LIKELY
    assert result.refined.status is not CorrelationStatus.CORRELATED


def test_likely_confidence_never_exceeds_cap() -> None:
    death = 1_100_000
    track = _track("trk_cap", _near_death_obs(death), team=TeamEstimate.ALLY)
    # Inflate track confidence above cap.
    track = EntityTrack(
        track_id=track.track_id,
        kind=track.kind,
        observations=track.observations,
        first_seen_game_t_ms=track.first_seen_game_t_ms,
        last_seen_game_t_ms=track.last_seen_game_t_ms,
        confidence=0.99,
        team_estimate=track.team_estimate,
        team_confidence=track.team_confidence,
        events=(),
        closed_reason=TrackLifecycle.LEFT_VIEW,
    )
    result = refine_with_death_ranking(
        _unknown_base(),
        (track,),
        alignment=_alignment(death, (track,)),
        subject_pid=_PID,
        subject_team_label=TeamEstimate.ALLY,
    )
    assert result.refined.status is CorrelationStatus.LIKELY
    assert result.refined.confidence <= LIKELY_CONFIDENCE_CAP


def test_sparse_observations_do_not_crash() -> None:
    death = 1_200_000
    track = _track("trk_one", (_obs(0, t_ms=death - 50, x=10),))
    ranking = rank_death_candidates((track,), death_t_ms=death)
    assert ranking.candidates
    result = refine_with_death_ranking(
        _unknown_base(),
        (track,),
        alignment=_alignment(death, (track,)),
        subject_pid=_PID,
    )
    assert result.refined.status is CorrelationStatus.UNKNOWN


def test_gst_remains_byte_identical() -> None:
    death = 1_300_000
    gst = _gst(death)
    before_facts = [
        (int(f.t_ms), str(f.kind), dict(f.payload), float(f.confidence)) for f in gst.facts()
    ]
    before_match = gst.match_id
    track = _track("trk_gst", _near_death_obs(death), team=TeamEstimate.ALLY)
    alignment = align_gst(
        gst,
        start_game_ms=death - 10_000,
        end_game_ms=death + 10_000,
        subject_pid=_PID,
        tracks=(track,),
    )
    refine_with_death_ranking(
        _unknown_base(),
        (track,),
        alignment=alignment,
        subject_pid=_PID,
        subject_team_label=TeamEstimate.ALLY,
    )
    assert alignment.mutated_gst is False
    assert gst.match_id == before_match
    after_facts = [
        (int(f.t_ms), str(f.kind), dict(f.payload), float(f.confidence)) for f in gst.facts()
    ]
    assert after_facts == before_facts


def test_death_align_ms_unchanged() -> None:
    assert DEATH_ALIGN_MS == 2_000
    assert CANDIDATE_POOL_MS == 5_000
    assert CANDIDATE_POOL_MS != DEATH_ALIGN_MS


def test_v4_binary_path_still_works_alongside_v6() -> None:
    death = 1_400_000
    track = _track("trk_v4", _near_death_obs(death, end_offset=-100), team=TeamEstimate.ALLY)
    alignment = _alignment(death, (track,))
    v4 = correlate_subject(
        (track,),
        subject_pid=_PID,
        subject_champion="Vladimir",
        alignment=alignment,
    )
    assert v4.status is CorrelationStatus.LIKELY
    v6 = refine_with_death_ranking(
        v4,
        (track,),
        alignment=alignment,
        subject_pid=_PID,
        subject_team_label=TeamEstimate.ALLY,
    )
    assert v6.refined.status is CorrelationStatus.LIKELY
    assert v6.refined.track_id == "trk_v4"
