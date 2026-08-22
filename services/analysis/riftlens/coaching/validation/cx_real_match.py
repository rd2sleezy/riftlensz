"""Developer-only C.x real-match validation pipeline.

Not production review wiring. Does not mutate H.8/H.11 behavior.
HUMAN QUALITY VALIDATION has not been performed.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from riftlens.adapters.ddragon.patch_data import PatchDataProvider
from riftlens.coaching.concepts import synthesize_lesson_candidates
from riftlens.coaching.concepts.models import CapabilityStatus, SynthesisResult
from riftlens.coaching.context import build_coaching_episodes
from riftlens.coaching.context.models import CoachingEpisode, FindingAssociation
from riftlens.coaching.evaluation.adapters import normalize_cx_candidate
from riftlens.coaching.evaluation.hard_fails import run_automated_checks
from riftlens.coaching.evaluation.models import HardFailFinding
from riftlens.coaching.interpretation import interpret_coaching_episodes
from riftlens.coaching.interpretation.models import EpisodeInterpretation
from riftlens.coaching.longitudinal import (
    CoachingScope,
    ConceptGameObservation,
    HistoricalCoachingGame,
    OpportunityStatus,
    PatternStatus,
    ScopeLevel,
    build_player_coaching_state,
    build_pre_game_focus,
)
from riftlens.coaching.longitudinal.models import PlayerCoachingState
from riftlens.coaching.prioritization import prioritize_lesson_candidates
from riftlens.coaching.prioritization.models import PrioritizedLessonSet
from riftlens.coaching.teaching import build_teaching_lessons, render_teaching_lesson_set
from riftlens.coaching.teaching.models import TeachingLessonSet
from riftlens.coaching.validation.traceability import (
    ConceptReplayTrace,
    TraceIndex,
    build_trace_index,
    format_concept_trace_block,
    format_game_clock_ms,
    format_replay_moments,
    format_review_these_moments,
    trace_for_lesson_candidate,
    trace_for_prioritized,
    trace_for_teaching,
)
from riftlens.domain.finding import Finding
from riftlens.domain.ports import PatchData
from riftlens.domain.timeline import GameStateTimeline

SENSITIVE_TOKENS = (
    "puuid",
    "PUUID",
    "summoner",
    "riot_id",
    "gameName",
    "tagLine",
    "api_key",
    "Authorization",
    "Bearer ",
)


@dataclass(frozen=True)
class CxValidationResult:
    """Serializable developer result for one C.x pass over GST+findings."""

    match_id: str
    participant_id: int
    patch: str
    champion: str
    role: str
    finding_count: int
    patch_status: str
    notes: tuple[str, ...]
    findings: tuple[Finding, ...]
    episodes: tuple[CoachingEpisode, ...]
    interpretations: tuple[EpisodeInterpretation, ...]
    synthesis: SynthesisResult
    prioritized: PrioritizedLessonSet
    teaching: TeachingLessonSet
    teaching_render: str
    c6_state: PlayerCoachingState | None = None
    c6_notes: tuple[str, ...] = ()
    c7_hard_fails: tuple[HardFailFinding, ...] = ()
    c7_passed: bool | None = None
    c7_reminder: str = "HUMAN QUALITY VALIDATION = NOT PERFORMED"

    def to_dict(self) -> dict[str, Any]:
        index = build_trace_index(
            findings=self.findings,
            episodes=self.episodes,
            interpretations=self.interpretations,
            synthesis=self.synthesis,
        )
        traces = {
            lesson.concept_id: trace_for_lesson_candidate(lesson, index).to_dict()
            for lesson in self.synthesis.lessons
        }
        return {
            "metadata": {
                "match_id": self.match_id,
                "participant_id": self.participant_id,
                "patch": self.patch,
                "champion": self.champion,
                "role": self.role,
                "finding_count": self.finding_count,
                "patch_status": self.patch_status,
                "notes": list(self.notes),
                "experimental": True,
                "human_quality_validation": "NOT_PERFORMED",
            },
            "c1_episodes": [item.to_dict() for item in self.episodes],
            "c2_interpretations": [item.to_dict() for item in self.interpretations],
            "c3_synthesis": self.synthesis.to_dict(),
            "c4_prioritized": self.prioritized.to_dict(),
            "c5_teaching": self.teaching.to_dict(),
            "c5_render": self.teaching_render,
            "traceability": traces,
            "c6_state": self.c6_state.to_dict() if self.c6_state else None,
            "c6_notes": list(self.c6_notes),
            "c7": {
                "ran": self.c7_passed is not None,
                "passed": self.c7_passed,
                "hard_fails": [item.to_dict() for item in self.c7_hard_fails],
                "reminder": self.c7_reminder,
            },
        }


@dataclass
class _PipelineNotes:
    items: list[str] = field(default_factory=list)

    def add(self, note: str) -> None:
        self.items.append(note)


def validate_participant_id(pid: int) -> None:
    """Raise ValueError when participant id is outside 1..10."""
    if pid < 1 or pid > 10:
        raise ValueError(f"invalid participant id {pid}; expected 1..10")


def load_patch_data(gst: GameStateTimeline) -> tuple[PatchData | None, str]:
    """Load bundled patch tables for ``gst.patch``. Never fabricates."""
    try:
        provider = PatchDataProvider()
        provider.load_bundled(gst.patch)
        return provider, "LOADED"
    except Exception as exc:  # noqa: BLE001 — developer harness surfaces load failures
        return None, f"PATCH_DATA_UNAVAILABLE ({type(exc).__name__}: {exc})"


def run_cx_pipeline(
    gst: GameStateTimeline,
    findings: Sequence[Finding],
    participant_id: int,
    *,
    patch: PatchData | None = None,
    include_c6: bool = False,
    include_c7: bool = False,
) -> CxValidationResult:
    """Run C.1→C.5 (+ optional C.6/C.7) on in-memory GST+findings.

    Zero findings → empty C.x outputs (not an error).
    """
    validate_participant_id(participant_id)
    notes = _PipelineNotes()
    patch_status = "PROVIDED" if patch is not None else "NONE"
    if patch is None:
        loaded, patch_status = load_patch_data(gst)
        patch = loaded
        if loaded is None:
            notes.add(patch_status)

    info = gst.participants.get(participant_id)
    champion = info.champion if info is not None else ""
    role = info.role.value if info is not None and hasattr(info.role, "value") else str(
        getattr(info, "role", "") if info is not None else ""
    )

    episodes = build_coaching_episodes(
        gst, findings, participant_id, patch=patch
    )
    interpretations = interpret_coaching_episodes(
        gst, episodes, participant_id, patch=patch
    )
    synthesis = synthesize_lesson_candidates(episodes, interpretations, findings)
    prioritized = prioritize_lesson_candidates(
        synthesis.lessons,
        match_id=gst.match_id,
        participant_id=participant_id,
    )
    teaching = build_teaching_lessons(
        prioritized, candidates=list(synthesis.lessons)
    )
    teaching_render = render_teaching_lesson_set(teaching)

    c6_state: PlayerCoachingState | None = None
    c6_notes: list[str] = []
    if include_c6:
        c6_state, c6_notes = _build_single_game_c6(
            gst=gst,
            participant_id=participant_id,
            champion=champion,
            role=role,
            prioritized=prioritized,
            teaching=teaching,
            synthesis=synthesis,
        )

    c7_fails: tuple[HardFailFinding, ...] = ()
    c7_passed: bool | None = None
    if include_c7:
        c7_fails, c7_passed = _run_c7_checks(
            teaching=teaching,
            prioritized=prioritized,
            synthesis=synthesis,
            interpretations=interpretations,
        )

    return CxValidationResult(
        match_id=gst.match_id,
        participant_id=participant_id,
        patch=gst.patch,
        champion=champion,
        role=role,
        finding_count=len(findings),
        patch_status=patch_status,
        notes=tuple(notes.items),
        findings=tuple(findings),
        episodes=tuple(episodes),
        interpretations=tuple(interpretations),
        synthesis=synthesis,
        prioritized=prioritized,
        teaching=teaching,
        teaching_render=teaching_render,
        c6_state=c6_state,
        c6_notes=tuple(c6_notes),
        c7_hard_fails=c7_fails,
        c7_passed=c7_passed,
    )


def _banner_focus_lines(result: CxValidationResult) -> tuple[str, str]:
    """Presentation-only banner lines — does not change C.4/C.5 tiers."""
    major = result.prioritized.major
    if major:
        primary_major = f"Primary MAJOR lesson: {major[0].concept_id}"
    else:
        primary_major = "Primary MAJOR lesson: NONE"

    if not result.teaching.lessons:
        return primary_major, "Top teaching lesson: NONE"

    top = result.teaching.lessons[0]
    return primary_major, f"Top teaching lesson: {top.concept_id} ({top.tier})"


def format_human_report(result: CxValidationResult) -> str:
    """Build the developer-facing stdout report (no PII fields)."""
    lines: list[str] = []
    primary_major, top_teaching = _banner_focus_lines(result)
    c7_line = "NOT RUN"
    if result.c7_passed is not None:
        c7_line = (
            f"{'PASS' if result.c7_passed else 'FAIL'} "
            f"(hard_fails={len(result.c7_hard_fails)}) — "
            f"{result.c7_reminder}"
        )

    index = build_trace_index(
        findings=result.findings,
        episodes=result.episodes,
        interpretations=result.interpretations,
        synthesis=result.synthesis,
    )

    lines.extend(
        [
            "==================================================",
            "RIFTLENS C.x REAL MATCH VALIDATION",
            "==================================================",
            "",
            f"Match: {result.match_id}",
            f"Participant: {result.participant_id}",
            f"Champion: {result.champion}",
            f"Role: {result.role}",
            f"Patch: {result.patch}",
            f"Findings: {result.finding_count}",
            f"PatchData: {result.patch_status}",
            "",
            f"Episodes: {len(result.episodes)}",
            f"Interpretations: {len(result.interpretations)}",
            f"Lesson candidates: {len(result.synthesis.lessons)}",
            "",
            f"Major lessons: {len(result.prioritized.major)}",
            f"Secondary lessons: {len(result.prioritized.secondary)}",
            f"Strengths: {len(result.prioritized.strengths)}",
            f"Withheld: {len(result.prioritized.withheld)}",
            "",
            primary_major,
            top_teaching,
            f"C.7 hard failures: {c7_line}",
            "",
            "WARNING: C.x output is experimental.",
            "HUMAN QUALITY VALIDATION has NOT been performed.",
            "==================================================",
        ]
    )
    for note in result.notes:
        lines.append(f"NOTE: {note}")

    lines.extend(["", "## C.1 Episodes"])
    if not result.episodes:
        lines.append("(none)")
    for episode in result.episodes:
        anchors = [
            item.finding_id
            for item in episode.findings
            if item.association is FindingAssociation.ANCHOR
        ]
        associated = [
            item.finding_id
            for item in episode.findings
            if item.association is not FindingAssociation.ANCHOR
        ]
        resolutions = [
            f"{row.finding_id}:{row.status.value}" for row in episode.resolutions
        ]
        gap_fields = [gap.field for gap in episode.gaps]
        lines.append(
            f"- {episode.id} "
            f"{format_game_clock_ms(episode.start_ms)}–"
            f"{format_game_clock_ms(episode.end_ms)} "
            f"t=[{episode.start_ms},{episode.end_ms}] "
            f"anchors={anchors} associated={associated} "
            f"gaps={gap_fields} resolutions={resolutions}"
        )

    lines.extend(["", "## C.2 Interpretations"])
    if not result.interpretations:
        lines.append("(none)")
    for interp in result.interpretations:
        outcomes = [
            f"{item.kind.value}/{item.polarity.value}" for item in interp.outcomes
        ] or ["(none)"]
        pk_notes = [
            f"{claim.label}:{claim.player_knowledge.value}"
            for claim in interp.information_claims[:6]
        ]
        lines.append(
            f"- {interp.id}: outcomes={outcomes} "
            f"decision={interp.decision.state.value} "
            f"execution={interp.execution.state.value} "
            f"actionability={interp.actionability.state.value} "
            f"player_knowledge_claims={pk_notes} "
            f"unknowns={list(interp.unknowns)[:8]}"
        )

    lines.extend(["", "## C.3 Lesson Candidates"])
    if not result.synthesis.lessons:
        lines.append("(none)")
    for lesson in result.synthesis.lessons:
        lines.append(
            f"- {lesson.concept_id}: polarity={lesson.polarity.value} "
            f"support={lesson.support_level.value} "
            f"specificity={lesson.specificity.value} "
            f"occurrences={lesson.within_match_occurrences} "
            f"conflicts={len(lesson.conflicting_evidence)} "
            f"gaps={list(lesson.context_gaps)[:6]} "
            f"hypotheses={len(lesson.causal_hypothesis_ids)}"
        )
        concept_trace = trace_for_lesson_candidate(lesson, index)
        lines.extend(format_concept_trace_block(concept_trace))
    lines.append("### Capability readiness")
    for cap in result.synthesis.capabilities:
        mark = " << BLOCKED" if cap.readiness is CapabilityStatus.BLOCKED else ""
        lines.append(f"- {cap.id}: {cap.readiness.value}{mark}")

    lines.extend(["", "## C.4 Prioritization"])
    for title, rows in (
        ("MAJOR", result.prioritized.major),
        ("SECONDARY", result.prioritized.secondary),
        ("STRENGTHS", result.prioritized.strengths),
        ("WITHHELD", result.prioritized.withheld),
    ):
        lines.append(f"### {title}")
        if not rows:
            lines.append("(none)")
            continue
        for item in rows:
            reasons = [code.code for code in item.reason_codes]
            lines.append(
                f"- {item.concept_id} value={item.learning_value:.1f} "
                f"rank={item.rank} support={item.support_level} "
                f"capability={item.capability_status} "
                f"factors={item.factors.to_dict()} "
                f"reasons={reasons} "
                f"exclusion={item.exclusion_reason}"
            )
            concept_trace = trace_for_prioritized(item, index)
            lines.extend(format_replay_moments(concept_trace))

    lines.extend(["", "## C.5 Teaching"])
    if not result.teaching.lessons:
        lines.append(result.teaching_render)
    else:
        capability_by_concept = {
            row.concept_id: row.capability_status
            for row in (
                *result.prioritized.major,
                *result.prioritized.secondary,
                *result.prioritized.strengths,
                *result.prioritized.withheld,
            )
        }
        rendered_blocks = result.teaching_render.split("\n\n")
        for i, teaching_lesson in enumerate(result.teaching.lessons):
            concept_trace = trace_for_teaching(
                teaching_lesson,
                index,
                capability_status=capability_by_concept.get(
                    teaching_lesson.concept_id
                ),
            )
            lines.extend(format_review_these_moments(concept_trace))
            if i < len(rendered_blocks):
                lines.append(rendered_blocks[i])
            lines.append("")

    if result.c6_state is not None or result.c6_notes:
        lines.extend(["", "## C.6 Single-game longitudinal (optional)"])
        for note in result.c6_notes:
            lines.append(f"NOTE: {note}")
        if result.c6_state is not None:
            for hist in result.c6_state.concept_histories:
                lines.append(
                    f"- {hist.concept_id}: status={hist.status.value} "
                    f"trend={hist.trend.value} "
                    f"opp_games={hist.games_with_opportunity}"
                )
            focus = result.c6_state.active_focus
            if focus is None:
                lines.append("Active focus: NONE")
            else:
                lines.append(
                    f"Active focus: {focus.concept_id} status={focus.status.value}"
                )
            pre = build_pre_game_focus(focus)
            if pre is not None:
                lines.append(
                    f"PreGameFocus: {pre.concept_id} — {pre.objective_summary}"
                )

    if result.c7_passed is not None:
        lines.extend(["", "## C.7 Automated structural checks (optional)"])
        lines.append(result.c7_reminder)
        lines.append(
            f"Result: {'PASS' if result.c7_passed else 'FAIL'} "
            f"(hard_fails={len(result.c7_hard_fails)})"
        )
        lines.append(
            "Automated PASS does NOT mean coaching quality is validated."
        )
        for fail in result.c7_hard_fails:
            lines.append(
                f"- {fail.kind.value}/{fail.category.value}: {fail.detail}"
            )

    text = "\n".join(lines) + "\n"
    _assert_no_sensitive_leak(text)
    return text


# Re-export for tests / package surface
__trace_helpers__ = (
    ConceptReplayTrace,
    TraceIndex,
    format_game_clock_ms,
)


def assert_safe_output_path(path: Path, *, repo_root: Path) -> Path:
    """Refuse writing real-match artifacts into the tracked repository tree."""
    resolved = path.expanduser().resolve()
    root = repo_root.resolve()
    try:
        resolved.relative_to(root)
    except ValueError:
        return resolved
    raise ValueError(
        f"Refusing to write real-match C.x output under the repository ({resolved}). "
        "Use a path outside the repo (e.g. /tmp or ~/.riftlens/cx_validation/)."
    )


def _assert_no_sensitive_leak(text: str) -> None:
    lower = text.lower()
    for token in ("puuid", "api_key", "authorization", "bearer "):
        if token in lower:
            raise RuntimeError(f"Refusing to emit sensitive token in report: {token}")


def _build_single_game_c6(
    *,
    gst: GameStateTimeline,
    participant_id: int,
    champion: str,
    role: str,
    prioritized: PrioritizedLessonSet,
    teaching: TeachingLessonSet,
    synthesis: SynthesisResult,
) -> tuple[PlayerCoachingState, list[str]]:
    """Smallest safe single-game HistoricalCoachingGame adapter.

    Does not invent opportunity denominators. Marks adapter as PARTIAL.
    """
    notes = [
        "C6_SINGLE_GAME_ADAPTER_PARTIAL",
        "Opportunity status set conservatively from lesson presence; "
        "denominators are not invented.",
    ]
    scope = CoachingScope(level=ScopeLevel.ROLE, role=role or None)
    observations: list[ConceptGameObservation] = []
    learning: dict[str, float] = {}
    teaching_map: dict[str, dict[str, Any]] = {}

    by_concept = {item.concept_id: item for item in synthesis.lessons}
    for row in (
        *prioritized.major,
        *prioritized.secondary,
        *prioritized.strengths,
    ):
        learning[row.concept_id] = row.learning_value
        # Presence of a supported lesson ⇒ observed opportunity for that concept.
        # Missing lesson / withheld-only ⇒ do not claim success.
        opportunity = (
            OpportunityStatus.OBSERVED_OPPORTUNITY
            if row.occurrences > 0 or row.concept_id in by_concept
            else OpportunityStatus.UNKNOWN_OPPORTUNITY
        )
        cand = by_concept.get(row.concept_id)
        occurrences = row.occurrences
        if cand is not None:
            occurrences = max(occurrences, cand.within_match_occurrences)
        observations.append(
            ConceptGameObservation(
                match_id=gst.match_id,
                concept_id=row.concept_id,
                scope=scope,
                opportunity_status=opportunity,
                polarity=row.polarity,
                support_level=row.support_level,
                occurrence_count=occurrences,
                lesson_tier=row.tier.value,
                learning_value=row.learning_value,
                measurable_metric=float(occurrences)
                if opportunity is OpportunityStatus.OBSERVED_OPPORTUNITY
                else None,
                opportunity_denominator=None,
                gaps=row.gaps,
            )
        )

    for lesson in teaching.lessons:
        teaching_map[lesson.concept_id] = lesson.to_dict()

    won: bool | None = None
    game = HistoricalCoachingGame(
        match_id=gst.match_id,
        played_at_ms=0,
        patch=gst.patch,
        role=role or "UNKNOWN",
        champion=champion or "UNKNOWN",
        won=won,
        concept_observations=tuple(observations),
        major_concept_ids=tuple(item.concept_id for item in prioritized.major),
        secondary_concept_ids=tuple(
            item.concept_id for item in prioritized.secondary
        ),
        strength_concept_ids=tuple(
            item.concept_id for item in prioritized.strengths
        ),
        teaching_by_concept=teaching_map,
        learning_value_by_concept=learning,
    )
    state = build_player_coaching_state(
        [game],
        player_key=f"pid:{participant_id}",
        scope=scope,
    )
    for hist in state.concept_histories:
        if hist.status is PatternStatus.RECURRING:
            notes.append(
                f"UNEXPECTED_RECURRING:{hist.concept_id} "
                "(single-game must not be RECURRING)"
            )
    return state, notes


def _run_c7_checks(
    *,
    teaching: TeachingLessonSet,
    prioritized: PrioritizedLessonSet,
    synthesis: SynthesisResult,
    interpretations: Sequence[EpisodeInterpretation],
) -> tuple[tuple[HardFailFinding, ...], bool]:
    primary = teaching.lessons[0] if teaching.lessons else None
    caps = {item.id: item.readiness.value for item in synthesis.capabilities}
    decision = None
    if interpretations:
        decision = interpretations[0].decision.state.value
    payload: dict[str, Any] = {
        "lesson": primary.concept_id if primary else None,
        "why": primary.why_it_matters.text
        if primary and primary.why_it_matters
        else None,
        "alternative": primary.alternative.action
        if primary and primary.alternative
        else None,
        "cue": (
            f"{primary.recognition_cue.trigger} -> "
            f"{primary.recognition_cue.intended_check}"
            if primary and primary.recognition_cue
            else None
        ),
        "drill": primary.drill.instruction
        if primary and primary.drill
        else None,
        "objective": primary.objective.target_behavior
        if primary and primary.objective
        else None,
        "concept_ids": tuple(item.concept_id for item in prioritized.major),
        "major_count": len(prioritized.major),
        "decision_quality": decision,
        "capability_statuses": caps,
        "measurability": (
            primary.objective.measurability.value
            if primary and primary.objective
            else None
        ),
        "structural": {
            "asserts_definite_decision": False,
            "asserts_definite_causality": False,
            "gives_specific_blocked_advice": False,
        },
        "limitations": tuple(primary.limitations) if primary else (),
    }
    view = normalize_cx_candidate(payload)
    fails = run_automated_checks(view)
    return fails, len(fails) == 0
