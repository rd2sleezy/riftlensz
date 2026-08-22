"""Local-only debug artifact writers. Never commit these outputs."""

from __future__ import annotations

import json
import re
from pathlib import Path

import numpy as np
from numpy.typing import NDArray

from riftlens.domain.observation.common import ScreenRect
from riftlens.perception.capture import CapturedFrame
from riftlens.perception.geometry import LayoutSupport, ScreenGeometry
from riftlens.perception.models import RichReplayState, VisualTrack

RgbImage = NDArray[np.uint8]

_SAFE_NAME = re.compile(r"[^A-Za-z0-9._-]+")

# Distinct BGR-friendly RGB labels (drawn on RGB buffers).
_CHAMPION_RGB = (40, 220, 50)
_MINION_RGB = (220, 180, 40)
_MINIMAP_RGB = (80, 160, 255)
_HUD_RGB = (255, 80, 200)
_HP_FILL_RGB = (40, 255, 120)
_RESOURCE_FILL_RGB = (80, 140, 255)


def default_debug_root() -> Path:
    """Return ~/.riftlens/rp/perception (outside the git repo)."""
    return Path.home() / ".riftlens" / "rp" / "perception"


def assert_debug_path_safe(path: Path, *, repo_root: Path | None = None) -> Path:
    """Refuse writing debug artifacts under the git repository."""
    resolved = path.expanduser().resolve()
    if repo_root is not None:
        root = repo_root.resolve()
        try:
            resolved.relative_to(root)
        except ValueError:
            pass
        else:
            raise ValueError(
                f"debug path {resolved} is inside the repository; "
                "use ~/.riftlens/rp/perception or /tmp"
            )
    # Soft privacy: reject filenames that look like summoner/puuid dumps.
    name = resolved.name.lower()
    for token in ("puuid", "summoner_name", "apikey", "api_key"):
        if token in name:
            raise ValueError(f"debug path rejects privacy token {token!r}")
    return resolved


def write_debug_bundle(
    state: RichReplayState,
    frames: tuple[CapturedFrame, ...] | list[CapturedFrame],
    *,
    out_dir: Path,
    repo_root: Path | None = None,
    label: str = "inspect",
) -> Path:
    """Write JSON + annotated PNGs under a safe local directory.

    Annotations are for human verification only — they do not change detectors.
    Labels never invent participant/champion identities.
    """
    import cv2

    root = assert_debug_path_safe(out_dir, repo_root=repo_root)
    stamp = state.requested_game_t_ms
    dest = root / _SAFE_NAME.sub("_", f"{label}_t{stamp}")
    dest.mkdir(parents=True, exist_ok=True)
    (dest / "rich_replay_state.json").write_text(
        json.dumps(state.to_dict(), indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    for index, captured in enumerate(frames):
        if index >= len(state.frames):
            break
        obs = state.frames[index]
        annotated = annotate_observation_frame(
            np.array(captured.pixels, copy=True),
            obs,
            tracks=state.tracks,
        )
        bgr = cv2.cvtColor(annotated, cv2.COLOR_RGB2BGR)
        cv2.imwrite(str(dest / f"frame_{index:02d}.png"), bgr)
    return dest


def annotate_observation_frame(
    pixels: RgbImage,
    observation: object,
    *,
    tracks: tuple[VisualTrack, ...] | list[VisualTrack] = (),
) -> RgbImage:
    """Draw champion/minion boxes, HUD/minimap ROIs, fill hints, and local track ids."""
    from riftlens.perception.models import RichFrameObservation

    if not isinstance(observation, RichFrameObservation):
        return pixels
    out = np.asarray(pixels, dtype=np.uint8)
    geometry = ScreenGeometry.from_frame(observation.frame.width, observation.frame.height)

    if geometry.layout_support is not LayoutSupport.UNSUPPORTED:
        hud = geometry.roi("player_hud")
        hp = geometry.roi("resource_hp_area")
        if hud is not None:
            _draw_rect(out, hud, _HUD_RGB)
            _draw_label(out, hud.x, max(0, hud.y - 12), "HUD", _HUD_RGB)
        if hp is not None:
            _draw_rect(out, hp, _HP_FILL_RGB)
            _draw_label(out, hp.x, max(0, hp.y - 12), "HP", _HP_FILL_RGB)
            resource_roi = ScreenRect(
                x=hp.x,
                y=min(geometry.height - 1, hp.y + hp.height + 2),
                width=hp.width,
                height=max(2, int(round(hp.height * 0.7))),
            )
            _draw_rect(out, resource_roi, _RESOURCE_FILL_RGB)
            _draw_label(
                out,
                resource_roi.x,
                min(geometry.height - 1, resource_roi.y + resource_roi.height + 2),
                "RES",
                _RESOURCE_FILL_RGB,
            )
            _draw_fraction_marker(out, hp, observation.player_hud.hp_fraction, _HP_FILL_RGB)
            _draw_fraction_marker(
                out,
                resource_roi,
                observation.player_hud.resource_fraction,
                _RESOURCE_FILL_RGB,
            )

    for cand in observation.champion_candidates:
        # Candidate ids only on boxes — track ids are window-level (legend), not forced onto boxes.
        label = f"C:{cand.candidate_id}"
        _draw_rect(out, cand.region, _CHAMPION_RGB)
        _draw_label(out, cand.region.x, max(0, cand.region.y - 12), label, _CHAMPION_RGB)

    for cand in observation.minion_candidates:
        label = f"M:{cand.candidate_id}"
        _draw_rect(out, cand.region, _MINION_RGB)
        _draw_label(out, cand.region.x, max(0, cand.region.y - 12), label, _MINION_RGB)

    mm = observation.minimap.roi
    if observation.minimap.extracted and mm.width > 0:
        _draw_rect(out, mm, _MINIMAP_RGB)
        _draw_label(out, mm.x, max(0, mm.y - 12), "MINIMAP", _MINIMAP_RGB)

    # Legend of local visual track ids (not participant identities).
    if tracks:
        y = 14
        _draw_label(out, 8, y, "TRACKS:", (220, 220, 220))
        y += 14
        for track in list(tracks)[:12]:
            _draw_label(
                out,
                8,
                y,
                f"{track.track_id} {track.kind.value} n={track.observation_count}",
                (200, 200, 200),
            )
            y += 12
    return out


def _draw_fraction_marker(
    pixels: RgbImage,
    region: ScreenRect,
    claim: object,
    color: tuple[int, int, int],
) -> None:
    value = getattr(claim, "value", None)
    if not isinstance(value, (int, float)):
        return
    frac = max(0.0, min(1.0, float(value)))
    x = region.x + int(round(region.width * frac))
    y0 = region.y
    y1 = region.y + region.height
    h, w = pixels.shape[0], pixels.shape[1]
    if x < 0 or x >= w:
        return
    y0, y1 = max(0, y0), min(h, y1)
    if y1 <= y0:
        return
    pixels[y0:y1, x] = color


def _draw_label(
    pixels: RgbImage,
    x: int,
    y: int,
    text: str,
    color: tuple[int, int, int],
) -> None:
    import cv2

    # OpenCV draws on BGR views; convert temporarily for text only.
    bgr = cv2.cvtColor(pixels, cv2.COLOR_RGB2BGR)
    bgr_color = (int(color[2]), int(color[1]), int(color[0]))
    cv2.putText(
        bgr,
        text,
        (max(0, int(x)), max(12, int(y))),
        cv2.FONT_HERSHEY_SIMPLEX,
        0.35,
        bgr_color,
        1,
        cv2.LINE_AA,
    )
    pixels[:] = cv2.cvtColor(bgr, cv2.COLOR_BGR2RGB)


def _draw_rect(
    pixels: RgbImage,
    region: ScreenRect,
    color: tuple[int, int, int],
) -> None:
    x0, y0 = region.x, region.y
    x1, y1 = region.x + region.width, region.y + region.height
    h, w = pixels.shape[0], pixels.shape[1]
    x0, y0 = max(0, x0), max(0, y0)
    x1, y1 = min(w - 1, x1), min(h - 1, y1)
    if x1 <= x0 or y1 <= y0:
        return
    pixels[y0:y1, x0] = color
    pixels[y0:y1, x1] = color
    pixels[y0, x0:x1] = color
    pixels[y1, x0:x1] = color
