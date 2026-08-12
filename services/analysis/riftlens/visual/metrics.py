"""Research-only track fragmentation metrics. Not coaching scores."""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from typing import Any

from riftlens.visual.track import (
    CandidateKind,
    EntityTrack,
    fragmented_track_count,
    stable_track_count,
)


@dataclass(frozen=True)
class TrackMetrics:
    """Numeric comparison of detector+tracker output. Not a quality grade."""

    total_detections: int
    total_tracks: int
    stable_tracks: int
    tracks_ge_1s: int
    tracks_ge_3s: int
    one_frame_tracks: int
    fragmented_tracks: int
    avg_observations: float
    median_duration_ms: float
    mean_detections_per_frame: float
    sample_count: int

    def to_dict(self) -> dict[str, Any]:
        return {
            "total_detections": self.total_detections,
            "total_tracks": self.total_tracks,
            "stable_tracks": self.stable_tracks,
            "tracks_ge_1s": self.tracks_ge_1s,
            "tracks_ge_3s": self.tracks_ge_3s,
            "one_frame_tracks": self.one_frame_tracks,
            "fragmented_tracks": self.fragmented_tracks,
            "avg_observations": self.avg_observations,
            "median_duration_ms": self.median_duration_ms,
            "mean_detections_per_frame": self.mean_detections_per_frame,
            "sample_count": self.sample_count,
        }


def measure_tracks(
    tracks: Sequence[EntityTrack],
    *,
    sample_count: int,
    interval_ms: int,
) -> TrackMetrics:
    """Compute fragmentation metrics from V.1 tracks."""
    champion = [item for item in tracks if item.kind is CandidateKind.CHAMPION_LIKE]
    detections = sum(item.observation_count for item in champion)
    durations = [
        max(0, item.last_seen_game_t_ms - item.first_seen_game_t_ms) for item in champion
    ]
    one_frame = sum(1 for item in champion if item.observation_count <= 1)
    ge_1s = sum(1 for duration in durations if duration >= 1_000)
    ge_3s = sum(1 for duration in durations if duration >= 3_000)
    avg_obs = (
        round(sum(item.observation_count for item in champion) / float(len(champion)), 3)
        if champion
        else 0.0
    )
    median = float(_median(durations)) if durations else 0.0
    mean_per_frame = (
        round(detections / float(max(1, sample_count)), 3) if sample_count else 0.0
    )
    _ = interval_ms
    return TrackMetrics(
        total_detections=detections,
        total_tracks=len(champion),
        stable_tracks=stable_track_count(tracks),
        tracks_ge_1s=ge_1s,
        tracks_ge_3s=ge_3s,
        one_frame_tracks=one_frame,
        fragmented_tracks=fragmented_track_count(tracks),
        avg_observations=avg_obs,
        median_duration_ms=round(median, 1),
        mean_detections_per_frame=mean_per_frame,
        sample_count=sample_count,
    )


def _median(values: Sequence[int]) -> float:
    ordered = sorted(values)
    count = len(ordered)
    if count == 0:
        return 0.0
    mid = count // 2
    if count % 2 == 1:
        return float(ordered[mid])
    return (ordered[mid - 1] + ordered[mid]) / 2.0
