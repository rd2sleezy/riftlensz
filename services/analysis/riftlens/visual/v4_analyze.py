"""V.4 visual pipeline: spectator detect → V.1 track → team calibration → R.11."""

from __future__ import annotations

import json
import time
from collections.abc import Sequence
from dataclasses import dataclass, replace
from pathlib import Path
from typing import Any

from riftlens.domain.capture import CAPTURE_MANIFEST_NAME, CaptureManifest
from riftlens.domain.enums import Team
from riftlens.domain.ids import new_ulid
from riftlens.domain.observation import (
    CameraProvenance,
    FrameObservation,
    HudObservation,
    KnowledgeState,
    ObservationSequence,
    SampleGap,
    SpatialObservation,
    VisualClaimKind,
    camera_from_capture,
)
from riftlens.domain.observation.common import ScreenRect
from riftlens.domain.timeline import GameStateTimeline
from riftlens.visual.color_sample import BarColorSample, sample_bar_color
from riftlens.visual.correlate import CorrelationStatus, correlate_subject
from riftlens.visual.detect import ViewportCoverage
from riftlens.visual.detect_v2 import confirm_temporal
from riftlens.visual.detect_v4 import detect_sample_entities_v4
from riftlens.visual.errors import ArtifactMissing, VisualSpikeError
from riftlens.visual.gst_align import DEATH_ALIGN_MS, GstAlignment, align_gst, disappearing_near
from riftlens.visual.metrics import measure_tracks
from riftlens.visual.sampling import (
    SampledFrame,
    expected_sample_count,
    iter_gap_offsets,
    resolve_clip_path,
    sample_clip,
)
from riftlens.visual.team_calibrate import (
    CALIBRATION_VERSION,
    SpectatorColorClass,
    TeamCalibration,
    TeamColorAnchor,
    TrackTeamLabel,
    apply_labels_to_tracks,
    build_calibration,
    label_track,
    majority_track_color,
)
from riftlens.visual.track import (
    CandidateKind,
    EntityTrack,
    TeamEstimate,
    derive_timeline_events,
    finalize_tracks,
    track_candidates,
)
from riftlens.visual.v1_analyze import (
    DEFAULT_V1_SAMPLE_FPS,
    IdFactory,
    V1Timing,
    _camera_note,
    _observations,
    _peak_stable,
    _sequence_confidence,
)
from riftlens.visual.v2_analyze import V2AnalysisResult

V4_ANALYZER_ID = "riftlens.visual.v4.teamcolor"
V4_ANALYZER_VERSION = "v4.0"
DEFAULT_V4_SAMPLE_FPS = DEFAULT_V1_SAMPLE_FPS


@dataclass(frozen=True)
class V4AnalysisResult(V2AnalysisResult):
    """V.4 research output with spectator team calibration."""

    calibration: TeamCalibration | None = None
    color_sample_ms: float = 0.0
    calibrate_ms: float = 0.0
    track_labels: dict[str, dict[str, object]] | None = None

    def to_dict(self) -> dict[str, Any]:
        payload = super().to_dict()
        payload["analyzer_id"] = V4_ANALYZER_ID
        payload["analyzer_version"] = V4_ANALYZER_VERSION
        payload["calibration"] = None if self.calibration is None else self.calibration.to_dict()
        payload["color_sample_ms"] = self.color_sample_ms
        payload["calibrate_ms"] = self.calibrate_ms
        payload["track_labels"] = self.track_labels
        payload["detector_source"] = "v4.spectator"
        payload["calibration_version"] = CALIBRATION_VERSION
        return payload


def analyze_capture_dir_v4(
    capture_dir: Path,
    *,
    fps: float = DEFAULT_V4_SAMPLE_FPS,
    max_frames: int | None = None,
    id_factory: IdFactory | None = None,
    gst: GameStateTimeline | None = None,
    subject_pid: int | None = None,
    subject_champion: str | None = None,
    capture_review_pid: int | None = None,
    subject_team: Team | None = None,
) -> V4AnalysisResult:
    """Load an R.10 capture directory and run V.4."""
    manifest_path = Path(capture_dir) / CAPTURE_MANIFEST_NAME
    if not manifest_path.is_file():
        raise ArtifactMissing(f"missing {CAPTURE_MANIFEST_NAME}")
    return analyze_manifest_v4(
        manifest_path,
        fps=fps,
        max_frames=max_frames,
        id_factory=id_factory,
        gst=gst,
        subject_pid=subject_pid,
        subject_champion=subject_champion,
        capture_review_pid=capture_review_pid,
        subject_team=subject_team,
    )


def analyze_manifest_v4(
    manifest_path: Path,
    *,
    fps: float = DEFAULT_V4_SAMPLE_FPS,
    max_frames: int | None = None,
    id_factory: IdFactory | None = None,
    gst: GameStateTimeline | None = None,
    subject_pid: int | None = None,
    subject_champion: str | None = None,
    capture_review_pid: int | None = None,
    subject_team: Team | None = None,
) -> V4AnalysisResult:
    """Analyze with V.4 spectator detection + team-color calibration."""
    if fps <= 0:
        raise VisualSpikeError("fps must be > 0")
    payload = json.loads(Path(manifest_path).read_text(encoding="utf-8"))
    manifest = CaptureManifest.from_dict(payload)
    capture_dir = Path(manifest_path).parent
    clip_path = resolve_clip_path(manifest, capture_dir)
    make_id = id_factory or new_ulid
    resolved_team = subject_team
    if resolved_team is None and gst is not None and subject_pid is not None:
        info = gst.participants.get(subject_pid)
        if info is not None:
            resolved_team = info.team
    total_started = time.perf_counter()
    started = time.perf_counter()
    samples = sample_clip(clip_path, manifest=manifest, fps=fps, max_frames=max_frames)
    extract_ms = (time.perf_counter() - started) * 1000.0
    detect_started = time.perf_counter()
    raw_frames = tuple(
        detect_sample_entities_v4(
            sample.pixels, frame_index=sample.index, game_t_ms=sample.game_t_ms
        )
        for sample in samples
    )
    raw_bar_count = sum(len(item.candidates) for item in raw_frames)
    detections = confirm_temporal(raw_frames)
    confirmed_count = sum(len(item.candidates) for item in detections)
    detect_ms = (time.perf_counter() - detect_started) * 1000.0
    track_started = time.perf_counter()
    raw_tracks = finalize_tracks(track_candidates(detections))
    track_ms = (time.perf_counter() - track_started) * 1000.0
    color_started = time.perf_counter()
    track_samples = _sample_track_colors(raw_tracks, samples)
    color_sample_ms = (time.perf_counter() - color_started) * 1000.0
    camera = camera_from_capture(camera_controlled=manifest.camera_controlled)
    align_started = time.perf_counter()
    alignment = align_gst(
        gst,
        start_game_ms=int(manifest.requested_start_game_ms),
        end_game_ms=int(manifest.requested_end_game_ms),
        subject_pid=subject_pid,
        tracks=raw_tracks,
    )
    # Death alignment first (does not depend on team color).
    preliminary = correlate_subject(
        raw_tracks,
        subject_pid=subject_pid,
        subject_champion=subject_champion,
        alignment=alignment,
        camera_control=camera.control,
        capture_review_pid=capture_review_pid,
    )
    calibrate_started = time.perf_counter()
    track_colors = {
        track_id: majority_track_color(samples_list)
        for track_id, samples_list in track_samples.items()
    }
    death_anchors = _death_team_anchors(
        raw_tracks,
        alignment=alignment,
        gst=gst,
        track_colors=track_colors,
        subject_pid=subject_pid,
    )
    calibration = build_calibration(
        subject_team=resolved_team,
        correlation=preliminary,
        track_colors=track_colors,
        extra_anchors=death_anchors,
    )
    labels = {
        track.track_id: label_track(
            track, track_samples.get(track.track_id, ()), calibration
        )
        for track in raw_tracks
    }
    tracks = apply_labels_to_tracks(raw_tracks, labels)
    events = derive_timeline_events(tracks)
    calibrate_ms = (time.perf_counter() - calibrate_started) * 1000.0
    # Team agreement alone never upgrades identity without controlled camera.
    correlation = correlate_subject(
        tracks,
        subject_pid=subject_pid,
        subject_champion=subject_champion,
        alignment=alignment,
        camera_control=camera.control,
        capture_review_pid=capture_review_pid,
        assume_subject_perspective_hud=False,
    )
    align_ms = (time.perf_counter() - align_started) * 1000.0
    frames, inferred = _observations(
        samples,
        detections=detections,
        tracks=tracks,
        manifest=manifest,
        camera=camera,
        correlation=correlation,
        make_id=make_id,
    )
    frames = [_stamp_v4_detector(item) for item in frames]
    inferred = [_stamp_v4_detector(item) for item in inferred]
    team_inferred = _team_label_inferred_frames(
        tracks=tracks,
        labels=labels,
        calibration=calibration,
        manifest=manifest,
        camera=camera,
        make_id=make_id,
        samples=samples,
    )
    inferred = [*inferred, *team_inferred]
    informative = sum(1 for item in detections if item.coverage is ViewportCoverage.USEFUL)
    uninformative = len(detections) - informative
    interval_ms = int(round(1000.0 / fps))
    gaps = tuple(
        SampleGap(after_game_t_ms=after, gap_ms=gap, reason="sample_skip")
        for after, gap in iter_gap_offsets(samples, interval_ms=interval_ms)
    )
    duration_ms = max(
        0, int(manifest.requested_end_game_ms) - int(manifest.requested_start_game_ms)
    )
    expected = expected_sample_count(duration_ms=duration_ms, fps=fps)
    if max_frames is not None:
        expected = min(expected, max(1, int(max_frames)))
    clip = manifest.artifacts[0]
    sequence = ObservationSequence(
        sequence_id=make_id(),
        capture_interval_id=manifest.capture_id,
        media_artifact_id=clip.id,
        match_id=manifest.match_id,
        gameplay_source_id=manifest.source_id,
        start_game_ms=int(manifest.requested_start_game_ms),
        end_game_ms=int(manifest.requested_end_game_ms),
        frames=tuple(frames),
        detector_id=V4_ANALYZER_ID,
        detector_version=V4_ANALYZER_VERSION,
        sample_count=len(frames),
        expected_sample_count=expected,
        gaps=gaps,
        sampling_interval_ms=interval_ms,
        clock_map_id=manifest.clock_map_id,
        confidence=_sequence_confidence(frames, informative=informative),
        artifact_relative_path=clip.relative_path,
        artifact_sha256=clip.sha256,
    )
    total_ms = (time.perf_counter() - total_started) * 1000.0
    subject_visibility = (
        KnowledgeState.KNOWN
        if correlation.status is not CorrelationStatus.UNKNOWN and correlation.track_id
        else KnowledgeState.UNKNOWN
    )
    metrics = measure_tracks(tracks, sample_count=len(frames), interval_ms=interval_ms)
    label_payload: dict[str, dict[str, object]] = {
        track_id: {
            "team_class": label.team_class.value,
            "riot_team": None if label.riot_team is None else int(label.riot_team),
            "color_class": label.color_class.value,
            "confidence": label.confidence,
            "evidence_count": label.evidence_count,
            "calibration_version": label.calibration_version,
        }
        for track_id, label in labels.items()
    }
    return V4AnalysisResult(
        sequence=sequence,
        inferred_frames=tuple(inferred),
        tracks=tracks,
        events=events,
        correlation=correlation,
        alignment=alignment,
        sample_fps=fps,
        timing=V1Timing(
            extract_ms=extract_ms,
            detect_ms=detect_ms,
            track_ms=track_ms,
            align_ms=align_ms,
            total_ms=total_ms,
            decoded_frames=len(samples),
            analyzed_frames=len(frames),
        ),
        informative_frames=informative,
        uninformative_frames=uninformative,
        peak_stable_tracks=_peak_stable(detections, tracks),
        subject_visibility=subject_visibility,
        camera_note=_camera_note(camera, informative=informative, total=len(frames)),
        clip_duration_ms=duration_ms,
        metrics=metrics,
        raw_bar_detections=raw_bar_count,
        confirmed_detections=confirmed_count,
        calibration=calibration,
        color_sample_ms=color_sample_ms,
        calibrate_ms=calibrate_ms,
        track_labels=label_payload,
    )


def _sample_track_colors(
    tracks: Sequence[EntityTrack],
    samples: Sequence[SampledFrame],
) -> dict[str, tuple[BarColorSample, ...]]:
    by_index = {item.index: item for item in samples}
    out: dict[str, list[BarColorSample]] = {}
    for track in tracks:
        collected: list[BarColorSample] = []
        for obs in track.observations:
            frame = by_index.get(obs.frame_index)
            if frame is None:
                continue
            # Health bar sits at the top of the V.2 body box.
            bar_h = max(4, min(12, obs.region.height // 5))
            bar = ScreenRect(
                x=obs.region.x,
                y=obs.region.y,
                width=obs.region.width,
                height=bar_h,
            )
            collected.append(sample_bar_color(frame.pixels, bar))
        out[track.track_id] = collected
    return {key: tuple(value) for key, value in out.items()}


def _death_team_anchors(
    tracks: Sequence[EntityTrack],
    *,
    alignment: GstAlignment,
    gst: GameStateTimeline | None,
    track_colors: dict[str, SpectatorColorClass],
    subject_pid: int | None,
) -> tuple[TeamColorAnchor, ...]:
    """Conservative GST death→color anchors. Ambiguous deaths are skipped."""
    if gst is None:
        return ()
    out: list[TeamColorAnchor] = []
    used_tracks: set[str] = set()
    for kill in alignment.kills:
        if kill.victim_id is None:
            continue
        victim_id = int(kill.victim_id)
        if subject_pid is not None and victim_id == subject_pid:
            continue  # subject handled via correlation anchor
        info = gst.participants.get(victim_id)
        if info is None:
            continue
        nearby = disappearing_near(tracks, int(kill.game_t_ms), window_ms=DEATH_ALIGN_MS)
        champ = [
            item
            for item in nearby
            if item.kind is CandidateKind.CHAMPION_LIKE and not item.ambiguous
        ]
        if len(champ) != 1:
            continue
        track = champ[0]
        if track.track_id in used_tracks:
            continue
        if track.observation_count < 2:
            continue
        color = track_colors.get(track.track_id, SpectatorColorClass.UNKNOWN)
        if color is SpectatorColorClass.UNKNOWN:
            continue
        used_tracks.add(track.track_id)
        conf = min(0.55, float(kill.confidence))
        out.append(
            TeamColorAnchor(
                track_id=track.track_id,
                riot_team=info.team,
                color=color,
                confidence=conf,
                reason=f"gst_death_victim_{victim_id}",
            )
        )
    return tuple(out)


def _stamp_v4_detector(frame: FrameObservation) -> FrameObservation:
    return replace(
        frame,
        detector_id=V4_ANALYZER_ID,
        detector_version=V4_ANALYZER_VERSION,
    )


def _team_label_inferred_frames(
    *,
    tracks: Sequence[EntityTrack],
    labels: dict[str, TrackTeamLabel],
    calibration: TeamCalibration,
    manifest: CaptureManifest,
    camera: CameraProvenance,
    make_id: IdFactory,
    samples: Sequence[SampledFrame],
) -> list[FrameObservation]:
    """Emit VISUAL_INFERRED team labels. Does not mutate GST."""
    clip = manifest.artifacts[0]
    width = samples[0].width if samples else None
    height = samples[0].height if samples else None
    stamped = CameraProvenance(
        control=camera.control,
        confidence=camera.confidence,
        target_participant_id=camera.target_participant_id,
        target_knowledge=camera.target_knowledge,
        viewport_width=width,
        viewport_height=height,
        mode=camera.mode,
    )
    out: list[FrameObservation] = []
    for track in tracks:
        if track.kind is not CandidateKind.CHAMPION_LIKE:
            continue
        label = labels.get(track.track_id)
        if label is None or label.team_class is TeamEstimate.UNKNOWN:
            continue
        last = track.observations[-1]
        out.append(
            FrameObservation(
                observation_id=make_id(),
                match_id=manifest.match_id,
                gameplay_source_id=manifest.source_id,
                capture_interval_id=manifest.capture_id,
                media_artifact_id=clip.id,
                game_t_ms=last.game_t_ms,
                clock_map_id=manifest.clock_map_id,
                observation_type="track_team_label",
                confidence=float(label.confidence),
                detector_id=V4_ANALYZER_ID,
                detector_version=V4_ANALYZER_VERSION,
                camera=stamped,
                claim_kind=VisualClaimKind.INFERRED,
                source_t_ms=None,
                artifact_relative_path=clip.relative_path,
                artifact_sha256=clip.sha256,
                entities=(),
                hud=HudObservation(hud_visible=KnowledgeState.UNKNOWN),
                spatial=SpatialObservation(
                    knowledge=KnowledgeState.UNKNOWN,
                    minimap_visible=KnowledgeState.UNKNOWN,
                    labels=("team_calibration",),
                ),
                payload={
                    "track_id": track.track_id,
                    "team_class": label.team_class.value,
                    "riot_team": None if label.riot_team is None else int(label.riot_team),
                    "color_class": label.color_class.value,
                    "team_evidence_count": int(label.evidence_count),
                    "calibration_version": CALIBRATION_VERSION,
                    "calibration_confidence": calibration.confidence.value,
                    "source": "VISUAL_INFERRED",
                },
            )
        )
    return out
