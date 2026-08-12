from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from enum import StrEnum
from typing import Any

from riftlens.domain.observation import KnowledgeState
from riftlens.visual.analyze import VisualAnalysisResult


class VisualRuleDiagnostic(StrEnum):
    """Research-only comparison of visual observations against a structured claim."""

    SUPPORTED = "SUPPORTED"
    CONTRADICTED = "CONTRADICTED"
    INSUFFICIENT_VISUAL_EVIDENCE = "INSUFFICIENT_VISUAL_EVIDENCE"
    PARTIALLY_SUPPORTED = "PARTIALLY_SUPPORTED"


@dataclass(frozen=True)
class StructuredClaim:
    """A coaching finding summarized for V.0 comparison. Not loaded from RuleEngine."""

    rule_id: str
    t_ms: int | None
    summary: str


def format_mmss(game_t_ms: int) -> str:
    """Format integer GAME ms as m:ss for the spike timeline."""
    seconds = max(0, int(game_t_ms)) // 1000
    return f"{seconds // 60}:{seconds % 60:02d}"


def format_timeline(result: VisualAnalysisResult) -> str:
    """Return a human-readable observation timeline. Not coaching advice."""
    lines = [
        f"V.0 timeline ({result.sequence.detector_id} {result.sequence.detector_version})",
        f"match={result.sequence.match_id} capture={result.sequence.capture_interval_id}",
        (
            f"GAME {format_mmss(result.sequence.start_game_ms)}–"
            f"{format_mmss(result.sequence.end_game_ms)} @ {result.sample_fps:g} fps"
        ),
        f"camera: {result.camera_note}",
        f"subject visibility: {result.subject_visibility.value}",
        f"subject correlation: {result.subject_correlation}",
        "",
    ]
    for frame in result.sequence.frames:
        payload: Mapping[str, Any] = frame.payload
        raw = payload.get("champion_like_count", 0)
        count = int(raw) if isinstance(raw, int) else 0
        ally = payload.get("ally_like_count")
        enemy = payload.get("enemy_like_count")
        useful = payload.get("viewport_informative")
        offset = payload.get("offset_ms")
        lines.append(
            f"{format_mmss(frame.game_t_ms)} / offset {offset}ms"
            f" — champion-like={count}"
            f" ally_like={ally} enemy_like={enemy}"
            f" informative={useful} conf={frame.confidence:.2f}"
        )
    if result.sequence.gaps:
        lines.append("")
        lines.append("gaps:")
        for gap in result.sequence.gaps:
            stamp = format_mmss(gap.after_game_t_ms)
            lines.append(f"  after {stamp} gap={gap.gap_ms}ms ({gap.reason})")
    return "\n".join(lines) + "\n"


def classify_against_claim(
    result: VisualAnalysisResult, claim: StructuredClaim
) -> VisualRuleDiagnostic:
    """Classify visual coverage of a structured claim. Does not mutate the finding.

    Viewport entity counts cannot prove fog-of-war. A rising count can only
    partially support a 'later arrivals' story; it cannot confirm unseen enemies.
    """
    if result.informative_frames == 0:
        return VisualRuleDiagnostic.INSUFFICIENT_VISUAL_EVIDENCE
    if claim.t_ms is not None:
        start = result.sequence.start_game_ms
        end = result.sequence.end_game_ms
        if claim.t_ms < start - 5_000 or claim.t_ms > end + 5_000:
            return VisualRuleDiagnostic.INSUFFICIENT_VISUAL_EVIDENCE
    counts = [count for _, count in result.entity_count_timeline]
    if not counts:
        return VisualRuleDiagnostic.INSUFFICIENT_VISUAL_EVIDENCE
    if result.subject_visibility is KnowledgeState.UNKNOWN and result.peak_entity_count == 0:
        return VisualRuleDiagnostic.INSUFFICIENT_VISUAL_EVIDENCE
    rising = any(later > earlier for earlier, later in zip(counts, counts[1:], strict=False))
    if rising and result.peak_entity_count >= 2:
        return VisualRuleDiagnostic.PARTIALLY_SUPPORTED
    if result.peak_entity_count >= 1:
        return VisualRuleDiagnostic.PARTIALLY_SUPPORTED
    return VisualRuleDiagnostic.INSUFFICIENT_VISUAL_EVIDENCE


def temporal_change_notes(result: VisualAnalysisResult) -> tuple[str, ...]:
    """Describe count changes without coaching language."""
    notes: list[str] = []
    previous: int | None = None
    for game_t_ms, count in result.entity_count_timeline:
        if previous is None:
            notes.append(
                f"{format_mmss(game_t_ms)}: {count} champion-like entit"
                f"{'y' if count == 1 else 'ies'} visible in viewport"
            )
        elif count > previous:
            notes.append(
                f"{format_mmss(game_t_ms)}: count rose {previous} → {count} "
                "(additional viewport entries)"
            )
        elif count < previous:
            notes.append(
                f"{format_mmss(game_t_ms)}: count fell {previous} → {count} "
                "(left viewport or lost bars)"
            )
        previous = count
    if not notes:
        notes.append("no sampled frames")
    return tuple(notes)
