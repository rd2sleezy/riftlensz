"""Developer-only RP.1 real-replay validation helpers.

Discovers existing R.10 captures and plans short baseline windows.
Does not change detector thresholds or coaching logic.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from riftlens.config import default_captures_dir
from riftlens.domain.capture import CAPTURE_MANIFEST_NAME, CaptureManifest, CaptureStatus
from riftlens.perception.baseline import VLADIMIR_BASELINE_MANIFEST
from riftlens.perception.models import RichReplayState
from riftlens.visual.window import capture_covers_window

# Default ±2.5s around each baseline timestamp (within the ±2–3s guidance).
DEFAULT_BASELINE_HALF_WINDOW_MS = 2_500
DEFAULT_BASELINE_FPS = 2.0


@dataclass(frozen=True)
class BaselineStamp:
    """One anonymized baseline inspection timestamp."""

    clock: str
    t_ms: int
    subject: str


@dataclass(frozen=True)
class CaptureCoverage:
    """Whether an R.10 capture directory covers a planned GAME window."""

    capture_dir: Path
    capture_id: str
    match_id: str
    requested_start_game_ms: int
    requested_end_game_ms: int
    status: str


@dataclass(frozen=True)
class BaselineWindowPlan:
    """Planned short capture/inspect window for one baseline stamp."""

    stamp: BaselineStamp
    window_start_ms: int
    window_end_ms: int
    covering: CaptureCoverage | None

    @property
    def covered(self) -> bool:
        return self.covering is not None


def baseline_stamps(
    manifest: dict[str, Any] | None = None,
) -> tuple[BaselineStamp, ...]:
    """Return ordered Vladimir baseline stamps from the frozen manifest."""
    body = VLADIMIR_BASELINE_MANIFEST if manifest is None else manifest
    rows = body["timestamps"]
    return tuple(
        BaselineStamp(
            clock=str(row["clock"]),
            t_ms=int(row["t_ms"]),
            subject=str(row["subject"]),
        )
        for row in rows
    )


def baseline_timestamp_ms_list(manifest: dict[str, Any] | None = None) -> tuple[int, ...]:
    """Return the frozen baseline t_ms list (for tests / CLI docs)."""
    return tuple(item.t_ms for item in baseline_stamps(manifest))


def resolve_captures_root(captures_root: Path | None = None) -> Path:
    """Return the R.10 captures root (machine-local)."""
    if captures_root is not None:
        return Path(captures_root).expanduser()
    return default_captures_dir()


def load_complete_captures(
    match_id: str,
    *,
    captures_root: Path | None = None,
) -> tuple[CaptureCoverage, ...]:
    """List complete R.10 capture directories for a match under the captures root."""
    root = resolve_captures_root(captures_root) / match_id
    if not root.is_dir():
        return ()
    found: list[CaptureCoverage] = []
    for folder in sorted(root.iterdir()):
        if not folder.is_dir():
            continue
        manifest_path = folder / CAPTURE_MANIFEST_NAME
        if not manifest_path.is_file():
            continue
        try:
            payload = json.loads(manifest_path.read_text(encoding="utf-8"))
            manifest = CaptureManifest.from_dict(payload)
        except (OSError, ValueError, KeyError, TypeError, json.JSONDecodeError):
            continue
        if manifest.status is not CaptureStatus.COMPLETE:
            continue
        found.append(
            CaptureCoverage(
                capture_dir=folder,
                capture_id=manifest.capture_id,
                match_id=manifest.match_id,
                requested_start_game_ms=int(manifest.requested_start_game_ms),
                requested_end_game_ms=int(manifest.requested_end_game_ms),
                status=CaptureStatus.COMPLETE.value,
            )
        )
    return tuple(found)


def find_covering_capture(
    captures: tuple[CaptureCoverage, ...] | list[CaptureCoverage],
    *,
    window_start_ms: int,
    window_end_ms: int,
    slack_ms: int = 2_000,
    require_media_span: bool = True,
) -> CaptureCoverage | None:
    """Pick the tightest complete capture that covers the GAME window.

    When ``require_media_span`` is True, also require that decoded media
    reaches near ``window_end_ms`` (manifest ranges alone can overstate coverage).
    """
    matches: list[CaptureCoverage] = []
    for item in captures:
        if not capture_covers_window(
            capture_start_game_ms=item.requested_start_game_ms,
            capture_end_game_ms=item.requested_end_game_ms,
            window_start_game_ms=window_start_ms,
            window_end_game_ms=window_end_ms,
            slack_ms=slack_ms,
        ):
            continue
        if require_media_span and not _media_covers_window(
            item.capture_dir,
            window_start_ms=window_start_ms,
            window_end_ms=window_end_ms,
            slack_ms=slack_ms,
        ):
            continue
        matches.append(item)
    if not matches:
        return None
    # Prefer smallest covering span, then lexicographically latest capture_id.
    matches.sort(
        key=lambda item: (
            item.requested_end_game_ms - item.requested_start_game_ms,
            item.capture_id,
        )
    )
    return matches[0]


def _media_covers_window(
    capture_dir: Path,
    *,
    window_start_ms: int,
    window_end_ms: int,
    slack_ms: int,
) -> bool:
    """True when sampled media GAME span covers the window (best-effort)."""
    try:
        from riftlens.perception.capture import sample_capture_dir

        samples = sample_capture_dir(Path(capture_dir), fps=1.0, max_frames=None)
    except Exception:
        return False
    if not samples:
        return False
    media_start = int(samples[0].game_t_ms)
    media_end = int(samples[-1].game_t_ms)
    return capture_covers_window(
        capture_start_game_ms=media_start,
        capture_end_game_ms=media_end,
        window_start_game_ms=window_start_ms,
        window_end_game_ms=window_end_ms,
        slack_ms=slack_ms,
    )


def plan_baseline_windows(
    *,
    match_id: str | None = None,
    captures_root: Path | None = None,
    half_window_ms: int = DEFAULT_BASELINE_HALF_WINDOW_MS,
    manifest: dict[str, Any] | None = None,
    require_media_span: bool = True,
) -> tuple[BaselineWindowPlan, ...]:
    """Plan ±half_window inspect windows and attach covering captures when present."""
    body = VLADIMIR_BASELINE_MANIFEST if manifest is None else manifest
    resolved_match = str(match_id or body["match_id"])
    captures = load_complete_captures(resolved_match, captures_root=captures_root)
    half = max(0, int(half_window_ms))
    plans: list[BaselineWindowPlan] = []
    for stamp in baseline_stamps(body):
        start = max(0, stamp.t_ms - half)
        end = stamp.t_ms + half
        covering = find_covering_capture(
            captures,
            window_start_ms=start,
            window_end_ms=end,
            require_media_span=require_media_span,
        )
        plans.append(
            BaselineWindowPlan(
                stamp=stamp,
                window_start_ms=start,
                window_end_ms=end,
                covering=covering,
            )
        )
    return tuple(plans)


def validate_capture_dir(capture_dir: Path) -> CaptureManifest:
    """Require an R.10 directory with manifest.json. Raises FileNotFoundError/ValueError."""
    path = Path(capture_dir)
    if not path.is_dir():
        raise FileNotFoundError(f"capture directory not found: {path}")
    manifest_path = path / CAPTURE_MANIFEST_NAME
    if not manifest_path.is_file():
        raise FileNotFoundError(f"missing {CAPTURE_MANIFEST_NAME} in {path}")
    payload = json.loads(manifest_path.read_text(encoding="utf-8"))
    manifest = CaptureManifest.from_dict(payload)
    if manifest.status is not CaptureStatus.COMPLETE:
        raise ValueError(
            f"capture status is {manifest.status.value!r}, expected 'complete'"
        )
    if not manifest.artifacts:
        raise ValueError(f"capture {path} has no artifacts")
    return manifest


def render_baseline_human_check(
    state: RichReplayState,
    *,
    clock: str | None = None,
    subject: str | None = None,
    capture_dir: Path | None = None,
) -> str:
    """Stdout report shaped for human RP.1 validation of one baseline stamp."""
    # Prefer the frame nearest the requested timestamp for the summary block.
    frames = state.frames
    if not frames:
        return "RICH REPLAY PERCEPTION\n(no frames)\n"
    primary = min(
        frames,
        key=lambda item: abs(
            int(
                item.frame.actual_game_t_ms
                if item.frame.actual_game_t_ms is not None
                else item.frame.requested_game_t_ms
            )
            - state.requested_game_t_ms
        ),
    )
    meta = primary.frame
    lines = [
        "==================================================",
        "RP.1 BASELINE HUMAN CHECK",
        "==================================================",
        f"timestamp: {state.requested_game_t_ms}"
        + (f" ({clock})" if clock else "")
        + (f"  subject={subject}" if subject else ""),
        f"capture_dir: {capture_dir}" if capture_dir else "capture_dir: (n/a)",
        f"window: {state.window_start_ms}–{state.window_end_ms}  frames={len(frames)}",
        "",
        "capture timing:",
        f"  requested t: {meta.requested_game_t_ms}",
        f"  actual t:    {meta.actual_game_t_ms}",
        f"  timing error: {meta.timing_error_ms} ms",
        "",
        "HUD:",
        f"  usable: {_claim(primary.player_hud.usable)}",
        f"  HP fraction: {_claim(primary.player_hud.hp_fraction)}",
        f"  resource fraction: {_claim(primary.player_hud.resource_fraction)}",
        f"  confidence: hp={_conf(primary.player_hud.hp_fraction)} "
        f"resource={_conf(primary.player_hud.resource_fraction)}",
        "",
        f"champion candidates: count={len(primary.champion_candidates)}",
    ]
    for cand in primary.champion_candidates:
        cx = cand.region.x + cand.region.width // 2
        cy = cand.region.y + cand.region.height // 2
        lines.append(
            f"  - {cand.candidate_id} pos=({cx},{cy}) "
            f"hp={_claim(cand.health_fraction)} conf={cand.confidence:.2f} "
            f"team={cand.team_class.value} id=UNKNOWN"
        )
    lines.append(f"minion candidates: count={len(primary.minion_candidates)}")
    for cand in primary.minion_candidates:
        cx = cand.region.x + cand.region.width // 2
        cy = cand.region.y + cand.region.height // 2
        lines.append(
            f"  - {cand.candidate_id} approx=({cx},{cy}) "
            f"hp={_claim(cand.health_fraction)} conf={cand.confidence:.2f} "
            f"team/color={cand.team_class.value}"
        )
    mm = primary.minimap
    lines.extend(
        [
            "",
            "minimap:",
            f"  ROI usable: {mm.extracted}",
            f"  generic pip count: {len(mm.pip_candidates)}",
            "  identity/fog: not claimed",
            "",
            f"gaps / UNKNOWN: {', '.join(primary.gaps) or '(none)'}",
            "",
            "local tracks (window):",
        ]
    )
    if not state.tracks:
        lines.append("  (none)")
    for track in state.tracks:
        lines.append(
            f"  - {track.track_id} kind={track.kind.value} state={track.state.value} "
            f"n={track.observation_count} conf={track.confidence:.2f} "
            f"team={track.team_class.value} participant_id=None"
        )
    lines.append("")
    return "\n".join(lines)


def render_coverage_report(plans: tuple[BaselineWindowPlan, ...] | list[BaselineWindowPlan]) -> str:
    """Print which baseline windows already have covering R.10 captures."""
    lines = [
        "RP.1 BASELINE CAPTURE COVERAGE",
        f"match windows: {len(plans)}",
        "",
    ]
    missing = 0
    for plan in plans:
        if plan.covering is None:
            missing += 1
            lines.append(
                f"MISSING  {plan.stamp.clock:>5}  t={plan.stamp.t_ms}  "
                f"need [{plan.window_start_ms},{plan.window_end_ms}]  "
                f"({plan.stamp.subject})"
            )
        else:
            cov = plan.covering
            lines.append(
                f"OK       {plan.stamp.clock:>5}  t={plan.stamp.t_ms}  "
                f"capture={cov.capture_id}  "
                f"[{cov.requested_start_game_ms},{cov.requested_end_game_ms}]"
            )
    lines.extend(
        [
            "",
            f"covered={len(plans) - missing}  missing={missing}",
            "NOTE: capture via R.10 (League + .rofl + READY session); "
            "see `rp_perception.py baseline --help`.",
            "",
        ]
    )
    return "\n".join(lines)


def _claim(claim: Any) -> str:
    status = getattr(claim, "status", None)
    value = getattr(claim, "value", None)
    if status is None:
        status_s = "UNKNOWN"
    elif hasattr(status, "value"):
        status_s = str(status.value)
    else:
        status_s = str(status)
    if value is None:
        return status_s
    return f"{status_s}:{value}"


def _conf(claim: Any) -> str:
    conf = getattr(claim, "confidence", None)
    if conf is None:
        return "n/a"
    return f"{float(conf):.2f}"
