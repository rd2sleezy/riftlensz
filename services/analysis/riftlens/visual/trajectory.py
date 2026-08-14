"""V.5 classical screen-space trajectory cues from track observations.

Does not infer map coordinates. Does not identify champions.
Camera pans and detector dropout remain confounders — treat large coherent
jumps as UNCERTAIN, not identity proof.
"""

from __future__ import annotations

import math
from collections.abc import Sequence
from dataclasses import dataclass
from enum import StrEnum

from riftlens.visual.track import EntityTrack, TrackObservation

# Consecutive-sample center displacement (px) beyond which motion is "jumpy".
JUMP_PX = 220.0
# Below this mean step size → stationary (screen space).
STATIONARY_MEAN_PX = 12.0
# Camera-like: large coherent steps that should not be over-read as subject motion.
CAMERA_LIKE_MEAN_PX = 90.0
# Direction consistency: fraction of steps sharing dominant quadrant.
DIRECTION_CONSISTENCY_MIN = 0.65


class MotionClass(StrEnum):
    STATIONARY = "STATIONARY"
    SMOOTH_MOVING = "SMOOTH_MOVING"
    JUMPY = "JUMPY"
    CAMERA_LIKE = "CAMERA_LIKE"
    UNCERTAIN = "UNCERTAIN"
    SPARSE = "SPARSE"


@dataclass(frozen=True)
class TrajectoryCue:
    """Measured screen-space motion for one track. VISUAL geometry → raw values."""

    track_id: str
    game_t_ms: int
    cue_type: str
    motion_class: MotionClass
    observation_count: int
    mean_step_px: float
    max_step_px: float
    total_path_px: float
    direction_consistency: float
    confidence: float
    claim_kind: str  # OBSERVED for geometry; interpretations use INFERRED upstream
    raw: dict[str, float | int | str | bool]

    def to_dict(self) -> dict[str, object]:
        return {
            "track_id": self.track_id,
            "game_t_ms": self.game_t_ms,
            "cue_type": self.cue_type,
            "motion_class": self.motion_class.value,
            "observation_count": self.observation_count,
            "mean_step_px": self.mean_step_px,
            "max_step_px": self.max_step_px,
            "total_path_px": self.total_path_px,
            "direction_consistency": self.direction_consistency,
            "confidence": self.confidence,
            "claim_kind": self.claim_kind,
            "raw": dict(self.raw),
        }


def center_of(obs: TrackObservation) -> tuple[float, float]:
    """Return the observation rectangle center in screen pixels."""
    return (
        float(obs.region.x) + float(obs.region.width) * 0.5,
        float(obs.region.y) + float(obs.region.height) * 0.5,
    )


def step_displacements(observations: Sequence[TrackObservation]) -> tuple[float, ...]:
    """Euclidean center-to-center steps between consecutive observations."""
    if len(observations) < 2:
        return ()
    out: list[float] = []
    prev = center_of(observations[0])
    for obs in observations[1:]:
        cur = center_of(obs)
        out.append(math.hypot(cur[0] - prev[0], cur[1] - prev[1]))
        prev = cur
    return tuple(out)


def direction_consistency(observations: Sequence[TrackObservation]) -> float:
    """Fraction of steps whose quadrant matches the modal quadrant. 0 if sparse."""
    if len(observations) < 3:
        return 0.0
    quads: list[int] = []
    prev = center_of(observations[0])
    for obs in observations[1:]:
        cur = center_of(obs)
        dx = cur[0] - prev[0]
        dy = cur[1] - prev[1]
        if abs(dx) < 1.0 and abs(dy) < 1.0:
            prev = cur
            continue
        # 0..3: NE, NW, SW, SE
        quad = (0 if dy <= 0 else 2) + (0 if dx >= 0 else 1)
        quads.append(quad)
        prev = cur
    if not quads:
        return 1.0
    counts = [quads.count(i) for i in range(4)]
    return max(counts) / float(len(quads))


def classify_motion(observations: Sequence[TrackObservation]) -> MotionClass:
    """Classical motion label from screen centers. Fail soft to UNCERTAIN/SPARSE."""
    steps = step_displacements(observations)
    if len(observations) < 2:
        return MotionClass.SPARSE
    if not steps:
        return MotionClass.SPARSE
    mean_step = sum(steps) / float(len(steps))
    max_step = max(steps)
    if max_step >= JUMP_PX:
        return MotionClass.JUMPY
    if mean_step <= STATIONARY_MEAN_PX:
        return MotionClass.STATIONARY
    consistency = direction_consistency(observations)
    if mean_step >= CAMERA_LIKE_MEAN_PX and consistency >= DIRECTION_CONSISTENCY_MIN:
        return MotionClass.CAMERA_LIKE
    if consistency >= DIRECTION_CONSISTENCY_MIN and max_step < JUMP_PX:
        return MotionClass.SMOOTH_MOVING
    if mean_step < CAMERA_LIKE_MEAN_PX:
        return MotionClass.UNCERTAIN
    return MotionClass.UNCERTAIN


def measure_trajectory(track: EntityTrack) -> TrajectoryCue:
    """Build a MOTION_CONTINUITY cue for ``track`` from its observations."""
    observations = track.observations
    steps = step_displacements(observations)
    mean_step = 0.0 if not steps else sum(steps) / float(len(steps))
    max_step = 0.0 if not steps else max(steps)
    total_path = 0.0 if not steps else float(sum(steps))
    consistency = direction_consistency(observations)
    motion = classify_motion(observations)
    # Geometry confidence: denser, non-jumpy tracks score higher.
    if motion is MotionClass.SPARSE:
        conf = 0.2
    elif motion is MotionClass.JUMPY:
        conf = 0.25
    elif motion is MotionClass.CAMERA_LIKE:
        conf = 0.35
    elif motion is MotionClass.UNCERTAIN:
        conf = 0.4
    elif motion is MotionClass.STATIONARY:
        conf = min(0.7, 0.35 + 0.05 * len(observations))
    else:  # SMOOTH_MOVING
        conf = min(0.75, 0.4 + 0.04 * len(observations) + 0.15 * consistency)
    stamp = observations[-1].game_t_ms if observations else track.last_seen_game_t_ms
    return TrajectoryCue(
        track_id=track.track_id,
        game_t_ms=int(stamp),
        cue_type="MOTION_CONTINUITY",
        motion_class=motion,
        observation_count=len(observations),
        mean_step_px=round(mean_step, 3),
        max_step_px=round(max_step, 3),
        total_path_px=round(total_path, 3),
        direction_consistency=round(consistency, 3),
        confidence=round(conf, 3),
        claim_kind="OBSERVED",
        raw={
            "step_count": len(steps),
            "jump_threshold_px": JUMP_PX,
            "stationary_mean_px": STATIONARY_MEAN_PX,
            "camera_like_mean_px": CAMERA_LIKE_MEAN_PX,
        },
    )
