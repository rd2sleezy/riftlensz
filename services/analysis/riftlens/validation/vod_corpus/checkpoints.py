"""Independent video_t_ms → visible game-clock labels. Never derived from H.10."""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import cv2
import yaml

from riftlens.pipeline.ingest_video.reader import SampledVideoFrame, decode_at
from riftlens.validation.vod_corpus.kinds import GamePhase
from riftlens.vision.detectors.clock import parse_clock_text
from riftlens.vision.layout.detect_layout import detect_layout

FORBIDDEN_LABEL_SOURCES = frozenset({"h10_syncmap", "h10_predicted", "auto_sync"})


@dataclass(frozen=True)
class Checkpoint:
    """One human (or otherwise independent) HUD-clock observation."""

    video_t_ms: int
    visible_clock: str
    game_t_ms: int
    phase: GamePhase = GamePhase.UNKNOWN
    label_basis: str = "manual_visual"
    notes: str = ""


@dataclass(frozen=True)
class CheckpointSet:
    """Labels for one corpus id."""

    corpus_id: str
    label_basis: str
    checkpoints: tuple[Checkpoint, ...]
    notes: str = ""

    def __post_init__(self) -> None:
        if self.label_basis.lower() in FORBIDDEN_LABEL_SOURCES:
            raise ValueError("checkpoint labels must not come from H.10 predictions")


@dataclass(frozen=True)
class CheckpointError:
    """Signed error of a SyncMap against one independent label."""

    video_t_ms: int
    labelled_game_ms: int
    predicted_game_ms: int | None
    abs_error_ms: int | None
    uncovered: bool


def load_checkpoints(path: Path) -> CheckpointSet:
    """Load a YAML checkpoint file. ``game_t_ms`` may be omitted when clock text parses."""
    raw = yaml.safe_load(path.read_text(encoding="utf-8"))
    if not isinstance(raw, dict):
        raise ValueError(f"checkpoint YAML must be a mapping: {path}")
    return checkpoint_set_from_mapping(raw)


def checkpoint_set_from_mapping(raw: dict[str, Any]) -> CheckpointSet:
    """Parse a checkpoint mapping. Assumes ``checkpoints`` is a list."""
    rows = raw.get("checkpoints")
    if not isinstance(rows, list):
        raise ValueError("checkpoints must be a list")
    return CheckpointSet(
        corpus_id=str(raw["corpus_id"]),
        label_basis=str(raw.get("label_basis") or "manual_visual"),
        checkpoints=tuple(_checkpoint_from_mapping(item) for item in rows),
        notes=str(raw.get("notes") or ""),
    )


def errors_against_map(
    checkpoints: Sequence[Checkpoint],
    *,
    video_to_game: Any,
) -> list[CheckpointError]:
    """Compare labels to ``video_to_game(t_video_ms) -> int | None``."""
    out: list[CheckpointError] = []
    for item in checkpoints:
        predicted = video_to_game(item.video_t_ms)
        if predicted is None:
            out.append(
                CheckpointError(
                    video_t_ms=item.video_t_ms,
                    labelled_game_ms=item.game_t_ms,
                    predicted_game_ms=None,
                    abs_error_ms=None,
                    uncovered=True,
                )
            )
            continue
        predicted_i = int(predicted)
        out.append(
            CheckpointError(
                video_t_ms=item.video_t_ms,
                labelled_game_ms=item.game_t_ms,
                predicted_game_ms=predicted_i,
                abs_error_ms=abs(predicted_i - item.game_t_ms),
                uncovered=False,
            )
        )
    return out


def error_stats(rows: Sequence[CheckpointError]) -> dict[str, float | int | None]:
    """Return p50/p95/max over covered checkpoints. Uncovered rows are counted separately."""
    covered = [int(row.abs_error_ms) for row in rows if row.abs_error_ms is not None]
    return {
        "n": len(rows),
        "n_covered": len(covered),
        "n_uncovered": sum(1 for row in rows if row.uncovered),
        "p50_ms": _percentile(covered, 50) if covered else None,
        "p95_ms": _percentile(covered, 95) if covered else None,
        "max_ms": max(covered) if covered else None,
    }


def extract_checkpoint_stub(
    video_path: Path,
    times_ms: Sequence[int],
    out_dir: Path,
    *,
    corpus_id: str,
) -> Path:
    """Write clock-crop PNGs and a YAML stub for a human to fill ``visible_clock``."""
    out_dir.mkdir(parents=True, exist_ok=True)
    crops: list[dict[str, Any]] = []
    layout = None
    for t_ms in times_ms:
        sample = decode_at(video_path, int(t_ms))
        if sample is None:
            crops.append({"video_t_ms": int(t_ms), "file": None, "notes": "decode_failed"})
            continue
        if layout is None:
            layout = detect_layout([sample.frame])
        crop_path = out_dir / f"{corpus_id}_{sample.t_video_ms:08d}.png"
        _write_clock_crop(sample, layout.clock_rect, crop_path)
        strip_path = out_dir / f"{corpus_id}_{sample.t_video_ms:08d}_strip.png"
        _write_top_strip(sample, strip_path)
        crops.append(
            {
                "video_t_ms": sample.t_video_ms,
                "visible_clock": "",
                "phase": GamePhase.UNKNOWN.value,
                "label_basis": "manual_visual",
                "crop_file": crop_path.name,
                "strip_file": strip_path.name,
                "notes": (
                    "Fill visible_clock from the HUD clock on the strip, not the kill "
                    "score. H.10 SyncMap must not be copied here."
                ),
            }
        )
    stub = {
        "corpus_id": corpus_id,
        "label_basis": "manual_visual",
        "notes": "Independent HUD labels. H.10 SyncMap must not be copied here.",
        "checkpoints": crops,
    }
    yaml_path = out_dir / f"{corpus_id}.stub.yaml"
    yaml_path.write_text(yaml.safe_dump(stub, sort_keys=False), encoding="utf-8")
    return yaml_path


def _write_top_strip(sample: SampledVideoFrame, path: Path) -> None:
    height, width = sample.frame.shape[:2]
    y1 = max(1, int(0.16 * height))
    x0 = max(0, int(0.32 * width))
    x1 = min(width, int(0.68 * width))
    strip = sample.frame[0:y1, x0:x1]
    cv2.imwrite(str(path), strip if strip.size else sample.frame)


def _write_clock_crop(sample: SampledVideoFrame, rect: Any, path: Path) -> None:
    x, y, w, h = int(rect.x), int(rect.y), int(rect.width), int(rect.height)
    frame = sample.frame
    crop = frame[y : y + h, x : x + w]
    if crop.size == 0:
        crop = frame
    cv2.imwrite(str(path), crop)


def _checkpoint_from_mapping(raw: object) -> Checkpoint:
    if not isinstance(raw, dict):
        raise ValueError("checkpoint must be a mapping")
    clock = str(raw.get("visible_clock") or "").strip()
    parsed = parse_clock_text(clock) if clock else None
    game_raw = raw.get("game_t_ms")
    if game_raw is None:
        if parsed is None:
            raise ValueError("checkpoint needs visible_clock or game_t_ms")
        game_ms = parsed
    else:
        game_ms = int(game_raw)
        if parsed is not None and parsed != game_ms:
            raise ValueError(f"visible_clock {clock} is {parsed} ms but game_t_ms={game_ms}")
    basis = str(raw.get("label_basis") or "manual_visual")
    if basis.lower() in FORBIDDEN_LABEL_SOURCES:
        raise ValueError("checkpoint labels must not come from H.10 predictions")
    return Checkpoint(
        video_t_ms=int(raw["video_t_ms"]),
        visible_clock=clock or _format_clock(game_ms),
        game_t_ms=game_ms,
        phase=GamePhase(str(raw.get("phase") or GamePhase.UNKNOWN)),
        label_basis=basis,
        notes=str(raw.get("notes") or ""),
    )


def _format_clock(game_ms: int) -> str:
    total_s = max(0, int(game_ms) // 1000)
    minutes, seconds = divmod(total_s, 60)
    return f"{minutes}:{seconds:02d}"


def _percentile(values: Sequence[int], p: int) -> float:
    ordered = sorted(int(v) for v in values)
    if len(ordered) == 1:
        return float(ordered[0])
    rank = (p / 100.0) * (len(ordered) - 1)
    lo = int(rank)
    hi = min(lo + 1, len(ordered) - 1)
    frac = rank - lo
    return float(ordered[lo]) * (1.0 - frac) + float(ordered[hi]) * frac
