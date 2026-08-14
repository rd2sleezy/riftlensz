"""H.9.1 orchestration: video → samples → layout → clock readings.

Does not fit SyncMaps (H.10). VIDEO path only.
"""

from __future__ import annotations

from collections.abc import Sequence
from pathlib import Path

import numpy as np
from numpy.typing import NDArray

from riftlens.domain.clock_reading import ClockReading
from riftlens.domain.layout_profile import LayoutProfile
from riftlens.pipeline.ingest_video.reader import SampledVideoFrame, iter_samples
from riftlens.vision.detectors.clock import is_in_game, read_clock
from riftlens.vision.layout.detect_layout import detect_layout

BgrImage = NDArray[np.uint8]


def collect_clock_readings(
    path: str | Path,
    *,
    hz: float = 1.0,
    max_samples: int | None = None,
    layout: LayoutProfile | None = None,
    layout_sample_count: int = 5,
) -> tuple[LayoutProfile, list[ClockReading]]:
    """Sample a VOD and produce ``ClockReading`` rows for H.10.

    Failed/non-game samples yield ``t_game_ms=None`` with low confidence.
    """
    samples = list(iter_samples(path, hz=hz, max_samples=max_samples))
    if not samples:
        raise ValueError("no video samples decoded")
    profile = layout or _layout_from_samples(samples, count=layout_sample_count)
    readings: list[ClockReading] = []
    previous: int | None = None
    for sample in samples:
        readings.append(_reading_for_sample(sample, profile, previous_game_ms=previous))
        if readings[-1].t_game_ms is not None and readings[-1].confidence > 0:
            previous = readings[-1].t_game_ms
    return profile, readings


def reading_from_frame(
    frame: BgrImage,
    layout: LayoutProfile,
    *,
    t_video_ms: int,
    previous_game_ms: int | None = None,
) -> ClockReading:
    """Single-frame clock read used by tests and the CLI."""
    return _reading_for_sample(
        SampledVideoFrame(t_video_ms=t_video_ms, frame=frame),
        layout,
        previous_game_ms=previous_game_ms,
    )


def _layout_from_samples(
    samples: Sequence[SampledVideoFrame], *, count: int
) -> LayoutProfile:
    mid = len(samples) // 2
    start = max(0, mid - count // 2)
    window = samples[start : start + count] or samples[:1]
    return detect_layout([item.frame for item in window])


def _reading_for_sample(
    sample: SampledVideoFrame,
    layout: LayoutProfile,
    *,
    previous_game_ms: int | None,
) -> ClockReading:
    in_game = is_in_game(sample.frame, layout)
    if not in_game:
        return ClockReading(
            t_video_ms=sample.t_video_ms,
            t_game_ms=None,
            confidence=0.0,
            in_game=False,
            reason="not_in_game",
        )
    estimate = read_clock(sample.frame, layout, previous_game_ms=previous_game_ms)
    if estimate.confidence <= 0.0:
        return ClockReading(
            t_video_ms=sample.t_video_ms,
            t_game_ms=None,
            confidence=0.0,
            in_game=True,
            reason=estimate.basis or "unreadable",
        )
    return ClockReading(
        t_video_ms=sample.t_video_ms,
        t_game_ms=int(estimate.value),
        confidence=float(estimate.confidence),
        in_game=True,
        raw_text="",
        reason=estimate.basis,
    )
