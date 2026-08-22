"""Champion and minion health-bar candidates for RP.1."""

from __future__ import annotations

from collections.abc import Sequence

import numpy as np
from numpy.typing import NDArray

from riftlens.domain.enums import Source
from riftlens.domain.observation.common import ScreenRect
from riftlens.perception.geometry import ScreenGeometry
from riftlens.perception.models import (
    BarCandidate,
    CandidateKind,
    ObservationStatus,
    TeamClass,
    VisualClaim,
    unknown_claim,
)
from riftlens.visual.detect import DetectedBar, detect_champion_like_bars
from riftlens.visual.detect_v2 import detect_champion_like_entities
from riftlens.visual.hud_mask import apply_hud_mask, center_in_hud

RgbImage = NDArray[np.uint8]

_GREEN_LOW = np.array([40, 140, 140], dtype=np.uint8)
_GREEN_HIGH = np.array([80, 255, 255], dtype=np.uint8)
_RED_LOW_A = np.array([0, 140, 140], dtype=np.uint8)
_RED_HIGH_A = np.array([10, 255, 255], dtype=np.uint8)
_RED_LOW_B = np.array([170, 140, 140], dtype=np.uint8)
_RED_HIGH_B = np.array([180, 255, 255], dtype=np.uint8)


def _team(ally_like: bool | None) -> TeamClass:
    if ally_like is True:
        return TeamClass.ALLY_LIKE
    if ally_like is False:
        return TeamClass.ENEMY_LIKE
    return TeamClass.UNKNOWN


def _health_fraction(pixels: RgbImage, region: ScreenRect) -> VisualClaim:
    """Estimate fill from saturated green/red pixels along the bar."""
    import cv2

    if region.width < 4 or region.height < 1:
        return unknown_claim(notes="bar too small for fraction")
    y0 = max(0, region.y)
    y1 = min(pixels.shape[0], region.y + region.height)
    x0 = max(0, region.x)
    x1 = min(pixels.shape[1], region.x + region.width)
    crop = pixels[y0:y1, x0:x1]
    if crop.size == 0:
        return unknown_claim(notes="empty crop")
    hsv = cv2.cvtColor(crop, cv2.COLOR_RGB2HSV)
    green = cv2.inRange(hsv, _GREEN_LOW, _GREEN_HIGH)
    red = cv2.bitwise_or(
        cv2.inRange(hsv, _RED_LOW_A, _RED_HIGH_A),
        cv2.inRange(hsv, _RED_LOW_B, _RED_HIGH_B),
    )
    colored = cv2.bitwise_or(green, red)
    # Column is "filled" when any saturated pixel remains.
    cols = colored.max(axis=0) > 0
    if cols.size == 0:
        return unknown_claim(notes="no columns")
    filled = int(np.count_nonzero(cols))
    fraction = round(filled / float(cols.size), 3)
    return VisualClaim(
        status=ObservationStatus.OBSERVED,
        value=fraction,
        confidence=0.55,
        source=Source.VISUAL,
        notes="column_fill_of_saturated_bar_pixels",
    )


def detect_champion_candidates(
    pixels: RgbImage,
    geometry: ScreenGeometry,
) -> tuple[BarCandidate, ...]:
    """Reuse V.2 champion-like entities. Never sets participant/champion identity."""
    entities = detect_champion_like_entities(pixels)
    out: list[BarCandidate] = []
    for index, entity in enumerate(entities):
        out.append(
            BarCandidate(
                candidate_id=f"champ_{index:03d}",
                kind=CandidateKind.CHAMPION_CANDIDATE,
                region=entity.region,
                region_norm=geometry.normalize_rect(entity.region),
                confidence=float(entity.confidence),
                team_class=_team(entity.ally_like),
                health_fraction=_health_fraction(pixels, entity.bar_region),
                notes="v2.hybrid champion-like; identity UNKNOWN",
            )
        )
    return tuple(out)


def detect_minion_candidates(
    pixels: RgbImage,
    geometry: ScreenGeometry,
) -> tuple[BarCandidate, ...]:
    """Detect short health-bar-like candidates that V.2 rejects as champion noise.

    High precision over recall: require HUD-masked gameplay location and
    champion-incompatible width. Does not claim wave state.
    """
    if geometry.layout_support.value == "UNSUPPORTED":
        return ()
    if pixels.ndim != 3 or pixels.shape[2] != 3:
        return ()
    height, width = int(pixels.shape[0]), int(pixels.shape[1])
    masked = apply_hud_mask(pixels)
    bars = detect_champion_like_bars(masked)
    champ_min_width = max(28, int(round(width * 0.035)))
    out: list[BarCandidate] = []
    for index, bar in enumerate(bars):
        if center_in_hud(bar.region, width=width, height=height):
            continue
        if not _plausible_minion_bar(bar, champ_min_width=champ_min_width):
            continue
        # Prefer precision: drop very low confidence fragments.
        if bar.confidence < 0.35:
            continue
        out.append(
            BarCandidate(
                candidate_id=f"minion_{index:03d}",
                kind=CandidateKind.MINION_CANDIDATE,
                region=bar.region,
                region_norm=geometry.normalize_rect(bar.region),
                confidence=min(0.7, float(bar.confidence)),
                team_class=_team(bar.ally_like),
                health_fraction=_health_fraction(pixels, bar.region),
                notes="minion_candidate; not wave classification",
            )
        )
    # Cap to avoid FX spam; prefer higher confidence.
    ordered = sorted(out, key=lambda item: item.confidence, reverse=True)[:24]
    return tuple(sorted(ordered, key=lambda item: (item.region.y, item.region.x)))


def _plausible_minion_bar(bar: DetectedBar, *, champ_min_width: int) -> bool:
    """True for short bars below champion width gate, above chrome noise."""
    region = bar.region
    if region.height < 2 or region.height > 8:
        return False
    if region.width < 12 or region.width >= champ_min_width:
        return False
    aspect = region.width / float(max(region.height, 1))
    return 3.0 <= aspect <= 10.0


def filter_ambiguous_minions(
    candidates: Sequence[BarCandidate],
    *,
    champions: Sequence[BarCandidate],
) -> tuple[BarCandidate, ...]:
    """Drop minion candidates that heavily overlap a champion bar."""
    kept: list[BarCandidate] = []
    for candidate in candidates:
        if any(_iou(candidate.region, champ.region) >= 0.25 for champ in champions):
            continue
        kept.append(candidate)
    return tuple(kept)


def _iou(left: ScreenRect, right: ScreenRect) -> float:
    x0 = max(left.x, right.x)
    y0 = max(left.y, right.y)
    x1 = min(left.x + left.width, right.x + right.width)
    y1 = min(left.y + left.height, right.y + right.height)
    inter = max(0, x1 - x0) * max(0, y1 - y0)
    union = left.width * left.height + right.width * right.height - inter
    if union <= 0:
        return 0.0
    return inter / float(union)
