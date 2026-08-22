"""Human-readable RP.1 perception reports."""

from __future__ import annotations

from riftlens.perception.models import PERCEPTION_SCHEMA_VERSION, RichReplayState, VisualClaim


def render_rich_state(state: RichReplayState) -> str:
    """Developer stdout report for one RichReplayState."""
    lines = [
        "==================================================",
        "RICH REPLAY PERCEPTION",
        f"schema={PERCEPTION_SCHEMA_VERSION}",
        "==================================================",
        f"requested_t_ms: {state.requested_game_t_ms}",
        f"window: {state.window_start_ms}–{state.window_end_ms}",
        f"frames: {len(state.frames)}",
        "",
    ]
    for frame in state.frames:
        meta = frame.frame
        lines.extend(
            [
                f"## frame {meta.frame_id}",
                f"capture error: {meta.timing_error_ms} ms "
                f"(requested={meta.requested_game_t_ms} actual={meta.actual_game_t_ms})",
                f"size: {meta.width}x{meta.height} provenance={meta.provenance}",
                "HUD:",
                f"  usable={frame.player_hud.usable.status.value} "
                f"value={frame.player_hud.usable.value}",
                f"  hp_fraction={_claim(frame.player_hud.hp_fraction)}",
                f"  resource_fraction={_claim(frame.player_hud.resource_fraction)}",
                f"champion candidates: {len(frame.champion_candidates)}",
            ]
        )
        for cand in frame.champion_candidates[:12]:
            lines.append(
                f"  - {cand.candidate_id} conf={cand.confidence:.2f} "
                f"team={cand.team_class.value} "
                f"hp={_claim(cand.health_fraction)} "
                f"id=UNKNOWN"
            )
        lines.append(f"minion candidates: {len(frame.minion_candidates)}")
        for cand in frame.minion_candidates[:16]:
            lines.append(
                f"  - {cand.candidate_id} conf={cand.confidence:.2f} "
                f"team={cand.team_class.value} "
                f"hp={_claim(cand.health_fraction)}"
            )
        lines.append(
            f"minimap: extracted={frame.minimap.extracted} "
            f"pips={len(frame.minimap.pip_candidates)}"
        )
        lines.append(f"gaps: {', '.join(frame.gaps) or '(none)'}")
        lines.append("")
    lines.append("## tracks")
    if not state.tracks:
        lines.append("(none)")
    for track in state.tracks:
        lines.append(
            f"- {track.track_id} {track.kind.value} state={track.state.value} "
            f"n={track.observation_count} team={track.team_class.value} "
            f"participant_id=None"
        )
    lines.extend(["", "## capability status"])
    for cap in state.capability_status:
        lines.append(f"- {cap.capability_id}: {cap.status.value} — {cap.evidence}")
    lines.extend(["", f"notes: {'; '.join(state.notes)}", ""])
    return "\n".join(lines)


def _claim(claim: VisualClaim) -> str:
    if claim.value is None:
        return f"{claim.status.value}"
    return f"{claim.status.value}:{claim.value}"
