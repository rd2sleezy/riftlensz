"""Harness-only replay traceability helpers.

Uses existing C.x structured links (signals/lessons → findings/episodes).
Does not invent timestamps or alter C.1–C.7 algorithms.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from typing import Any

from riftlens.coaching.concepts.models import (
    ConceptSignal,
    LessonCandidate,
    SynthesisResult,
)
from riftlens.coaching.context.models import CoachingEpisode
from riftlens.coaching.interpretation.models import EpisodeInterpretation
from riftlens.coaching.prioritization.models import PrioritizedLesson
from riftlens.coaching.teaching.models import TeachingLesson
from riftlens.domain.finding import Finding


def format_game_clock_ms(t_ms: int) -> str:
    """Format game-clock milliseconds for human replay review.

    < 1 hour: ``M:SS`` / ``MM:SS`` (same convention as ``format_mmss``).
    ≥ 1 hour: ``H:MM:SS``.
    Floor division only — does not change upstream integer ``t_ms``.
    """
    total_s = max(0, int(t_ms)) // 1000
    if total_s >= 3600:
        hours, rem = divmod(total_s, 3600)
        minutes, seconds = divmod(rem, 60)
        return f"{hours}:{minutes:02d}:{seconds:02d}"
    minutes, seconds = divmod(total_s, 60)
    return f"{minutes}:{seconds:02d}"


@dataclass(frozen=True)
class OccurrenceTrace:
    """One linked finding/episode occurrence for a coaching concept."""

    occurrence_index: int
    concept_id: str
    rule_id: str | None
    finding_id: str | None
    finding_title: str | None
    anchor_t_ms: int | None
    episode_id: str | None
    episode_start_ms: int | None
    episode_end_ms: int | None
    interpretation_id: str | None
    support: str | None
    capability_status: str | None
    evidence_labels: tuple[str, ...]
    unavailable_reason: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "occurrence_index": self.occurrence_index,
            "concept_id": self.concept_id,
            "rule_id": self.rule_id,
            "finding_id": self.finding_id,
            "finding_title": self.finding_title,
            "anchor_t_ms": self.anchor_t_ms,
            "anchor_clock": (
                format_game_clock_ms(self.anchor_t_ms)
                if self.anchor_t_ms is not None
                else None
            ),
            "episode_id": self.episode_id,
            "episode_start_ms": self.episode_start_ms,
            "episode_end_ms": self.episode_end_ms,
            "episode_range_clock": (
                f"{format_game_clock_ms(self.episode_start_ms)}–"
                f"{format_game_clock_ms(self.episode_end_ms)}"
                if self.episode_start_ms is not None
                and self.episode_end_ms is not None
                else None
            ),
            "interpretation_id": self.interpretation_id,
            "support": self.support,
            "capability_status": self.capability_status,
            "evidence_labels": list(self.evidence_labels),
            "unavailable_reason": self.unavailable_reason,
        }


@dataclass(frozen=True)
class ConceptReplayTrace:
    concept_id: str
    support: str | None
    capability_status: str | None
    occurrences: tuple[OccurrenceTrace, ...]
    unavailable_reason: str | None = None

    def distinct_anchor_times_ms(self) -> tuple[int, ...]:
        times = sorted(
            {
                item.anchor_t_ms
                for item in self.occurrences
                if item.anchor_t_ms is not None
            }
        )
        return tuple(times)

    def to_dict(self) -> dict[str, Any]:
        return {
            "concept_id": self.concept_id,
            "support": self.support,
            "capability_status": self.capability_status,
            "occurrences": [item.to_dict() for item in self.occurrences],
            "unavailable_reason": self.unavailable_reason,
            "replay_moments_clock": [
                format_game_clock_ms(t) for t in self.distinct_anchor_times_ms()
            ],
        }


@dataclass(frozen=True)
class TraceIndex:
    """Lookup tables over one validation run's structured outputs."""

    findings_by_id: dict[str, Finding]
    episodes_by_id: dict[str, CoachingEpisode]
    interps_by_id: dict[str, EpisodeInterpretation]
    interps_by_episode: dict[str, EpisodeInterpretation]
    signals_by_concept: dict[str, list[ConceptSignal]]
    lessons_by_id: dict[str, LessonCandidate]
    lessons_by_concept: dict[str, LessonCandidate]
    capability_by_id: dict[str, str]


def build_trace_index(
    *,
    findings: Sequence[Finding],
    episodes: Sequence[CoachingEpisode],
    interpretations: Sequence[EpisodeInterpretation],
    synthesis: SynthesisResult,
) -> TraceIndex:
    findings_by_id = {item.id: item for item in findings}
    episodes_by_id = {item.id: item for item in episodes}
    interps_by_id = {item.id: item for item in interpretations}
    interps_by_episode = {item.episode_id: item for item in interpretations}
    signals_by_concept: dict[str, list[ConceptSignal]] = {}
    for signal in synthesis.signals:
        signals_by_concept.setdefault(signal.concept_id, []).append(signal)
    for rows in signals_by_concept.values():
        rows.sort(key=lambda item: (item.t_ms, item.finding_id))
    lessons_by_id = {item.id: item for item in synthesis.lessons}
    lessons_by_concept = {item.concept_id: item for item in synthesis.lessons}
    capability_by_id = {
        item.id: item.readiness.value for item in synthesis.capabilities
    }
    return TraceIndex(
        findings_by_id=findings_by_id,
        episodes_by_id=episodes_by_id,
        interps_by_id=interps_by_id,
        interps_by_episode=interps_by_episode,
        signals_by_concept=signals_by_concept,
        lessons_by_id=lessons_by_id,
        lessons_by_concept=lessons_by_concept,
        capability_by_id=capability_by_id,
    )


def _evidence_labels(finding: Finding | None) -> tuple[str, ...]:
    if finding is None:
        return ()
    labels: list[str] = []
    for item in finding.evidence[:6]:
        label = str(item.label or "").strip()
        if label:
            labels.append(label)
    return tuple(labels)


def _occurrence_from_signal(
    *,
    index: int,
    signal: ConceptSignal,
    trace: TraceIndex,
    support: str | None,
    capability_status: str | None,
) -> OccurrenceTrace:
    finding = trace.findings_by_id.get(signal.finding_id)
    episode = trace.episodes_by_id.get(signal.episode_id)
    interp = trace.interps_by_id.get(signal.interpretation_id) or (
        trace.interps_by_episode.get(signal.episode_id)
    )
    return OccurrenceTrace(
        occurrence_index=index,
        concept_id=signal.concept_id,
        rule_id=signal.rule_id or (finding.rule_id if finding else None),
        finding_id=signal.finding_id,
        finding_title=finding.title if finding else None,
        anchor_t_ms=signal.t_ms if signal.t_ms is not None else (
            finding.t_ms if finding else None
        ),
        episode_id=signal.episode_id,
        episode_start_ms=episode.start_ms if episode else None,
        episode_end_ms=episode.end_ms if episode else None,
        interpretation_id=interp.id if interp else signal.interpretation_id or None,
        support=support,
        capability_status=capability_status,
        evidence_labels=_evidence_labels(finding),
    )


def _occurrence_from_finding_id(
    *,
    index: int,
    concept_id: str,
    finding_id: str,
    episode_id: str | None,
    interpretation_id: str | None,
    trace: TraceIndex,
    support: str | None,
    capability_status: str | None,
) -> OccurrenceTrace:
    finding = trace.findings_by_id.get(finding_id)
    episode = trace.episodes_by_id.get(episode_id) if episode_id else None
    if episode is None and finding is not None:
        # Best-effort: find episode that lists this finding
        for candidate in trace.episodes_by_id.values():
            if any(ref.finding_id == finding_id for ref in candidate.findings):
                episode = candidate
                break
    interp = None
    if interpretation_id:
        interp = trace.interps_by_id.get(interpretation_id)
    if interp is None and episode is not None:
        interp = trace.interps_by_episode.get(episode.id)
    if finding is None:
        return OccurrenceTrace(
            occurrence_index=index,
            concept_id=concept_id,
            rule_id=None,
            finding_id=finding_id,
            finding_title=None,
            anchor_t_ms=None,
            episode_id=episode.id if episode else episode_id,
            episode_start_ms=episode.start_ms if episode else None,
            episode_end_ms=episode.end_ms if episode else None,
            interpretation_id=interp.id if interp else interpretation_id,
            support=support,
            capability_status=capability_status,
            evidence_labels=(),
            unavailable_reason=(
                f"Finding id {finding_id!r} not present in validation finding set"
            ),
        )
    return OccurrenceTrace(
        occurrence_index=index,
        concept_id=concept_id,
        rule_id=finding.rule_id,
        finding_id=finding.id,
        finding_title=finding.title,
        anchor_t_ms=finding.t_ms,
        episode_id=episode.id if episode else None,
        episode_start_ms=episode.start_ms if episode else None,
        episode_end_ms=episode.end_ms if episode else None,
        interpretation_id=interp.id if interp else None,
        support=support,
        capability_status=capability_status,
        evidence_labels=_evidence_labels(finding),
        unavailable_reason=(
            None
            if episode is not None
            else "Episode link unavailable for this finding"
        ),
    )


def trace_for_lesson_candidate(
    lesson: LessonCandidate,
    trace: TraceIndex,
    *,
    capability_status: str | None = None,
) -> ConceptReplayTrace:
    """Build occurrence traces for one C.3 lesson using signals/finding refs."""
    support = lesson.support_level.value
    signals = trace.signals_by_concept.get(lesson.concept_id, [])
    occurrences: list[OccurrenceTrace] = []
    if signals:
        for i, signal in enumerate(signals, start=1):
            occurrences.append(
                _occurrence_from_signal(
                    index=i,
                    signal=signal,
                    trace=trace,
                    support=support,
                    capability_status=capability_status,
                )
            )
    elif lesson.finding_ids:
        for i, finding_id in enumerate(lesson.finding_ids, start=1):
            episode_id = (
                lesson.episode_ids[i - 1]
                if i - 1 < len(lesson.episode_ids)
                else (lesson.episode_ids[0] if lesson.episode_ids else None)
            )
            interp_id = (
                lesson.interpretation_ids[i - 1]
                if i - 1 < len(lesson.interpretation_ids)
                else (
                    lesson.interpretation_ids[0]
                    if lesson.interpretation_ids
                    else None
                )
            )
            occurrences.append(
                _occurrence_from_finding_id(
                    index=i,
                    concept_id=lesson.concept_id,
                    finding_id=finding_id,
                    episode_id=episode_id,
                    interpretation_id=interp_id,
                    trace=trace,
                    support=support,
                    capability_status=capability_status,
                )
            )
    else:
        return ConceptReplayTrace(
            concept_id=lesson.concept_id,
            support=support,
            capability_status=capability_status,
            occurrences=(),
            unavailable_reason=(
                "TRACE_UNAVAILABLE: lesson has no concept signals or finding_ids"
            ),
        )
    return ConceptReplayTrace(
        concept_id=lesson.concept_id,
        support=support,
        capability_status=capability_status,
        occurrences=tuple(occurrences),
    )


def trace_for_prioritized(
    item: PrioritizedLesson,
    trace: TraceIndex,
) -> ConceptReplayTrace:
    lesson = trace.lessons_by_id.get(item.lesson_candidate_id) or trace.lessons_by_concept.get(
        item.concept_id
    )
    if lesson is None:
        return ConceptReplayTrace(
            concept_id=item.concept_id,
            support=item.support_level,
            capability_status=item.capability_status,
            occurrences=(),
            unavailable_reason=(
                "TRACE_UNAVAILABLE: no LessonCandidate linked to prioritized lesson"
            ),
        )
    return trace_for_lesson_candidate(
        lesson,
        trace,
        capability_status=item.capability_status,
    )


def trace_for_teaching(
    lesson: TeachingLesson,
    trace: TraceIndex,
    *,
    capability_status: str | None = None,
) -> ConceptReplayTrace:
    cand = trace.lessons_by_id.get(lesson.lesson_candidate_id) or trace.lessons_by_concept.get(
        lesson.concept_id
    )
    if cand is None:
        return ConceptReplayTrace(
            concept_id=lesson.concept_id,
            support=None,
            capability_status=capability_status,
            occurrences=(),
            unavailable_reason=(
                "TRACE_UNAVAILABLE: no LessonCandidate linked to teaching lesson"
            ),
        )
    return trace_for_lesson_candidate(
        cand,
        trace,
        capability_status=capability_status,
    )


def format_occurrence_block(occ: OccurrenceTrace, *, indent: str = "  ") -> list[str]:
    """Render one occurrence for the human report."""
    if occ.unavailable_reason and occ.anchor_t_ms is None and occ.finding_id is None:
        return [f"{indent}TRACE_UNAVAILABLE: {occ.unavailable_reason}"]
    lines = [f"{indent}occurrence {occ.occurrence_index}:"]
    if occ.rule_id:
        lines.append(f"{indent}  rule={occ.rule_id}")
    if occ.finding_id:
        title = f" ({occ.finding_title})" if occ.finding_title else ""
        lines.append(f"{indent}  finding={occ.finding_id}{title}")
    if occ.anchor_t_ms is not None:
        lines.append(
            f"{indent}  anchor={format_game_clock_ms(occ.anchor_t_ms)} "
            f"({occ.anchor_t_ms} ms)"
        )
    else:
        lines.append(f"{indent}  anchor=TRACE_UNAVAILABLE")
    if (
        occ.episode_id
        and occ.episode_start_ms is not None
        and occ.episode_end_ms is not None
    ):
        lines.append(
            f"{indent}  episode={occ.episode_id} "
            f"{format_game_clock_ms(occ.episode_start_ms)}–"
            f"{format_game_clock_ms(occ.episode_end_ms)}"
        )
    elif occ.episode_id:
        lines.append(f"{indent}  episode={occ.episode_id}")
    else:
        lines.append(f"{indent}  episode=TRACE_UNAVAILABLE")
    if occ.interpretation_id:
        lines.append(f"{indent}  interpretation={occ.interpretation_id}")
    if occ.support:
        lines.append(f"{indent}  support={occ.support}")
    if occ.capability_status:
        lines.append(f"{indent}  capability={occ.capability_status}")
    if occ.evidence_labels:
        lines.append(
            f"{indent}  evidence_labels={list(occ.evidence_labels)}"
        )
    if occ.unavailable_reason:
        lines.append(f"{indent}  note={occ.unavailable_reason}")
    return lines


def format_concept_trace_block(concept_trace: ConceptReplayTrace) -> list[str]:
    if concept_trace.unavailable_reason and not concept_trace.occurrences:
        return [f"  TRACE_UNAVAILABLE: {concept_trace.unavailable_reason}"]
    lines: list[str] = []
    for occ in concept_trace.occurrences:
        lines.extend(format_occurrence_block(occ))
    return lines


def format_replay_moments(concept_trace: ConceptReplayTrace) -> list[str]:
    times = concept_trace.distinct_anchor_times_ms()
    if not times:
        return ["Replay moments:", "  TRACE_UNAVAILABLE"]
    lines = ["Replay moments:"]
    for t_ms in times:
        lines.append(f"  - {format_game_clock_ms(t_ms)}")
    return lines


def format_review_these_moments(concept_trace: ConceptReplayTrace) -> list[str]:
    if not concept_trace.occurrences:
        return [
            "REVIEW THESE MOMENTS:",
            f"  TRACE_UNAVAILABLE: {concept_trace.unavailable_reason or 'no linked findings'}",
        ]
    lines = ["REVIEW THESE MOMENTS:"]
    seen: set[tuple[int, str]] = set()
    for occ in concept_trace.occurrences:
        if occ.anchor_t_ms is None:
            reason = (
                occ.unavailable_reason
                or occ.finding_id
                or "missing timestamp"
            )
            lines.append(f"  TRACE_UNAVAILABLE — {reason}")
            continue
        label = occ.rule_id or occ.concept_id
        if occ.finding_title:
            label = f"{label} / {occ.finding_title}"
        key = (occ.anchor_t_ms, label)
        if key in seen:
            continue
        seen.add(key)
        lines.append(f"  - {format_game_clock_ms(occ.anchor_t_ms)} — {label}")
    return lines
