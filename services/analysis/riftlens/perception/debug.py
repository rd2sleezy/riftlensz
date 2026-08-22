"""Local-only debug artifact writers. Never commit these outputs."""

from __future__ import annotations

import json
import re
from pathlib import Path

import numpy as np
from numpy.typing import NDArray

from riftlens.domain.observation.common import ScreenRect
from riftlens.perception.capture import CapturedFrame
from riftlens.perception.models import RichReplayState

RgbImage = NDArray[np.uint8]

_SAFE_NAME = re.compile(r"[^A-Za-z0-9._-]+")


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
    """Write JSON + optional annotated PNGs under a safe local directory."""
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
        annotated = np.array(captured.pixels, copy=True)
        for cand in obs.champion_candidates:
            _draw_rect(annotated, cand.region, (40, 220, 50))
        for cand in obs.minion_candidates:
            _draw_rect(annotated, cand.region, (220, 180, 40))
        mm = obs.minimap.roi
        if obs.minimap.extracted and mm.width > 0:
            _draw_rect(annotated, mm, (80, 160, 255))
        bgr = cv2.cvtColor(annotated, cv2.COLOR_RGB2BGR)
        cv2.imwrite(str(dest / f"frame_{index:02d}.png"), bgr)
    return dest


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
