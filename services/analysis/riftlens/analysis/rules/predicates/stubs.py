from __future__ import annotations

from riftlens.analysis.features.fights import segment_fights
from riftlens.analysis.rules.context import RuleContext, evidence_fact
from riftlens.analysis.rules.registry import register_rule, register_segmenter
from riftlens.domain.finding import Finding
from riftlens.domain.timeline import GameStateTimeline


@register_rule("rules.stubs.never")
def never(ctx: RuleContext) -> Finding | None:
    """Return None always. Assumes the R-000 stub must not emit findings."""
    del ctx
    return None


@register_rule("rules.test.always_fires")
def always_fires(ctx: RuleContext) -> Finding | None:
    """Return a finding at every candidate time. Assumes GST facts exist."""
    return ctx.finding(
        confidence=1.0,
        evidence=[
            evidence_fact(
                "candidate time",
                {"t_ms": ctx.t_ms, "pid": ctx.subject_pid, "match_id": ctx.gst.match_id},
                t_ms=ctx.t_ms,
            )
        ],
    )


@register_rule("rules.test.role_gated_never_fires")
def role_gated_never_fires(ctx: RuleContext) -> Finding | None:
    """Return a finding if evaluated. Applicability should prevent evaluation."""
    return ctx.finding(
        confidence=1.0,
        evidence=[
            evidence_fact(
                "unexpected evaluation",
                {"pid": ctx.subject_pid, "role": ctx.gst.role_of(ctx.subject_pid).value},
                t_ms=ctx.t_ms,
            )
        ],
    )


@register_rule("rules.test.weak_finding")
def weak_finding(ctx: RuleContext) -> Finding | None:
    """Return a weaker finding used by the suppression-pair test."""
    return ctx.finding(
        confidence=0.8,
        evidence=[
            evidence_fact(
                "weak signal",
                {"t_ms": ctx.t_ms, "pid": ctx.subject_pid},
                t_ms=ctx.t_ms,
            )
        ],
    )


@register_rule("rules.test.strong_finding")
def strong_finding(ctx: RuleContext) -> Finding | None:
    """Return a stronger finding that suppresses the weak pair member."""
    return ctx.finding(
        confidence=0.9,
        evidence=[
            evidence_fact(
                "strong signal",
                {"t_ms": ctx.t_ms, "pid": ctx.subject_pid},
                t_ms=ctx.t_ms,
            )
        ],
    )


@register_segmenter("fights.segment_fights")
def fight_boundaries(gst: GameStateTimeline, subject_pid: int) -> list[int]:
    """Return fight start/end times involving ``subject_pid`` when known."""
    del subject_pid
    times: list[int] = []
    for fight in segment_fights(gst):
        times.append(fight.t_start)
        times.append(fight.t_end)
    return sorted(set(times))
