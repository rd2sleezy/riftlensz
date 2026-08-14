"""V.6 pre-algorithm track-loss diagnostic (offline, no production changes).

Uses an existing framed R.10 capture. Does not weaken identity rules.
Does not modify tracker/detector defaults in riftlens.visual permanently.
"""

from __future__ import annotations

import json
import os
import time
from collections.abc import Mapping, Sequence
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any

import cv2
import numpy as np

from riftlens.domain.capture import CaptureManifest
from riftlens.domain.observation.common import ScreenRect
from riftlens.visual.detect import ViewportCoverage, classify_viewport
from riftlens.visual.detect_v2 import confirm_temporal
from riftlens.visual.detect_v4 import detect_sample_entities_v4
from riftlens.visual.gst_align import DEATH_ALIGN_MS, disappearing_near
from riftlens.visual.sampling import resolve_clip_path, sample_clip
from riftlens.visual.track import (
    LONG_GAP_FRAMES,
    MATCH_CENTER_PX,
    MATCH_IOU,
    MISS_GRACE_FRAMES,
    CandidateKind,
    EntityTrack,
    FrameCandidate,
    FrameDetections,
    finalize_tracks,
    track_candidates,
)

SPIKE_ROOT = Path(__file__).resolve().parent
ARTIFACTS = SPIKE_ROOT / "artifacts"
DEFAULT_CAPTURE = Path.home() / (
    ".riftlens/captures/NA1_5620410094/01KZZCQ1C9W831FNC40H2R8MS2"
)
DEATH_T_MS = 839_881
FOCUS_START_MS = 832_000
FOCUS_END_MS = 841_000
LOSS_BAND_START_MS = 833_500
LOSS_BAND_END_MS = 835_500
DEFAULT_FPS = 4.0
HIGHER_FPS = 8.0


@dataclass(frozen=True)
class TrackerParams:
    name: str
    miss_grace: int
    long_gap: int


def main() -> int:
    capture_dir = Path(os.environ.get("RIFTLENS_V6_CAPTURE_DIR", str(DEFAULT_CAPTURE)))
    if not capture_dir.is_dir():
        raise SystemExit(f"capture missing: {capture_dir}")
    manifest = CaptureManifest.from_dict(
        json.loads((capture_dir / "manifest.json").read_text(encoding="utf-8"))
    )
    clip = resolve_clip_path(manifest, capture_dir)
    ARTIFACTS.mkdir(parents=True, exist_ok=True)
    (ARTIFACTS / "frames").mkdir(parents=True, exist_ok=True)

    report: dict[str, Any] = {
        "match_id": manifest.match_id,
        "capture_id": manifest.capture_id,
        "capture_dir": str(capture_dir),
        "clip": str(clip),
        "death_t_ms": DEATH_T_MS,
        "camera_controlled": manifest.camera_controlled,
        "requested_interval": [
            manifest.requested_start_game_ms,
            manifest.requested_end_game_ms,
        ],
        "tracker_defaults": {
            "MISS_GRACE_FRAMES": MISS_GRACE_FRAMES,
            "LONG_GAP_FRAMES": LONG_GAP_FRAMES,
            "MATCH_CENTER_PX": MATCH_CENTER_PX,
            "MATCH_IOU": MATCH_IOU,
            "DEATH_ALIGN_MS": DEATH_ALIGN_MS,
        },
    }

    print("=== media duration ===")
    report["media"] = _media_stats(clip, start_game_ms=manifest.requested_start_game_ms)
    print(
        "decoded_frames",
        report["media"]["decoded_frames"],
        "duration_s",
        report["media"]["duration_s"],
        "implied_end_game_ms",
        report["media"]["implied_end_game_ms"],
        "death_in_file",
        report["media"]["death_in_file"],
    )

    print("=== sample @", DEFAULT_FPS, "fps ===")
    baseline, baseline_tracks = _analyze_fps(
        clip, manifest, fps=DEFAULT_FPS, save_frames=True
    )
    report["baseline_4fps"] = baseline

    print("=== sample @", HIGHER_FPS, "fps ===")
    higher, _ = _analyze_fps(clip, manifest, fps=HIGHER_FPS, save_frames=False)
    report["higher_8fps"] = higher

    print("=== tracker counterfactuals on baseline detections ===")
    counterfactuals = _tracker_counterfactuals(baseline["confirmed_frames"])
    report["tracker_counterfactuals"] = counterfactuals

    print("=== duplicate track analysis ===")
    report["duplicate_tracks"] = _duplicate_analysis(baseline_tracks)

    print("=== case classification ===")
    report["case_classification"] = _classify_cases(baseline, baseline_tracks)

    report["death_alignment_feasibility"] = _feasibility(
        baseline=baseline,
        higher=higher,
        counterfactuals=counterfactuals,
        media=report["media"],
        case=report["case_classification"],
    )
    report["verdict"] = report["death_alignment_feasibility"]["verdict"]
    report["recommended_next"] = report["death_alignment_feasibility"]["recommended_next"]

    out = ARTIFACTS / "track_loss_diagnostic.json"
    out.write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
    print("wrote", out)
    print("VERDICT", report["verdict"])
    print(
        "baseline end→death",
        baseline["summary"]["min_end_to_death_ms"],
        "best counterfactual",
        report["death_alignment_feasibility"]["best_legitimate_end_to_death_ms"],
    )
    return 0


def _media_stats(clip: Path, *, start_game_ms: int) -> dict[str, Any]:
    import av

    container = av.open(str(clip))
    decoded = 0
    last_t = 0.0
    for frame in container.decode(video=0):
        decoded += 1
        if frame.time is not None:
            last_t = float(frame.time)
    container.close()
    implied_end = int(start_game_ms) + int(round(last_t * 1000.0))
    return {
        "path": str(clip),
        "bytes": clip.stat().st_size,
        "decoded_frames": decoded,
        "duration_s": round(last_t, 3),
        "implied_end_game_ms": implied_end,
        "requested_end_game_ms_delta": implied_end - (start_game_ms + 17_000),
        "death_in_file": implied_end >= DEATH_T_MS,
        "shortfall_to_death_ms": max(0, DEATH_T_MS - implied_end),
    }


def _analyze_fps(
    clip: Path,
    manifest: CaptureManifest,
    *,
    fps: float,
    save_frames: bool,
) -> tuple[dict[str, Any], tuple[EntityTrack, ...]]:
    t0 = time.perf_counter()
    samples = sample_clip(clip, manifest=manifest, fps=fps)
    extract_ms = (time.perf_counter() - t0) * 1000.0
    t0 = time.perf_counter()
    raw_frames = [
        detect_sample_entities_v4(
            sample.pixels, frame_index=sample.index, game_t_ms=sample.game_t_ms
        )
        for sample in samples
    ]
    detect_ms = (time.perf_counter() - t0) * 1000.0
    confirmed = confirm_temporal(raw_frames)
    t0 = time.perf_counter()
    tracks = finalize_tracks(track_candidates(confirmed))
    track_ms = (time.perf_counter() - t0) * 1000.0

    timeline = _build_timeline(
        samples=samples,
        raw_frames=raw_frames,
        confirmed=confirmed,
        save_frames=save_frames,
        fps_tag=f"{fps:g}",
    )
    champ = tuple(t for t in tracks if t.kind is CandidateKind.CHAMPION_LIKE)
    nearest = sorted(champ, key=lambda t: abs(t.last_seen_game_t_ms - DEATH_T_MS))
    min_gap = None if not nearest else DEATH_T_MS - nearest[0].last_seen_game_t_ms
    near_death = disappearing_near(champ, DEATH_T_MS, window_ms=DEATH_ALIGN_MS)
    loss_t = max((t.last_seen_game_t_ms for t in champ), default=None)
    after_loss_all: list[dict[str, Any]] = []
    if loss_t is not None:
        for raw, conf in zip(raw_frames, confirmed, strict=True):
            if conf.game_t_ms <= loss_t:
                continue
            after_loss_all.append(
                {
                    "game_t_ms": conf.game_t_ms,
                    "raw_det_count": len(raw.candidates),
                    "confirmed_det_count": len(conf.candidates),
                    "coverage_confirmed": conf.coverage.value,
                    "raw_boxes": [_cand_dict(c) for c in raw.candidates],
                    "confirmed_boxes": [_cand_dict(c) for c in conf.candidates],
                }
            )
    summary = {
        "fps": fps,
        "sample_count": len(samples),
        "first_sample_ms": None if not samples else samples[0].game_t_ms,
        "last_sample_ms": None if not samples else samples[-1].game_t_ms,
        "extract_ms": round(extract_ms, 1),
        "detect_ms": round(detect_ms, 1),
        "track_ms": round(track_ms, 1),
        "raw_detection_total": sum(len(f.candidates) for f in raw_frames),
        "confirmed_detection_total": sum(len(f.candidates) for f in confirmed),
        "track_count": len(champ),
        "longest_duration_ms": max(
            (t.last_seen_game_t_ms - t.first_seen_game_t_ms for t in champ), default=0
        ),
        "latest_last_seen_ms": max((t.last_seen_game_t_ms for t in champ), default=None),
        "min_end_to_death_ms": min_gap,
        "disappearing_near_death": [t.track_id for t in near_death],
        "tracks": [_track_summary(t) for t in champ],
        "frames_after_latest_last_seen": len(after_loss_all),
        "detections_after_latest_last_seen": after_loss_all[:50],
    }
    payload = {
        "summary": summary,
        "timeline_focus": [
            row for row in timeline if FOCUS_START_MS <= int(row["game_t_ms"]) <= FOCUS_END_MS
        ],
        "timeline_loss_band": [
            row
            for row in timeline
            if LOSS_BAND_START_MS <= int(row["game_t_ms"]) <= LOSS_BAND_END_MS
        ],
        "confirmed_frames": [
            {
                "frame_index": f.frame_index,
                "game_t_ms": f.game_t_ms,
                "coverage": f.coverage.value,
                "candidates": [_cand_dict(c) for c in f.candidates],
            }
            for f in confirmed
        ],
    }
    return payload, champ


def _build_timeline(
    *,
    samples: Sequence[Any],
    raw_frames: Sequence[FrameDetections],
    confirmed: Sequence[FrameDetections],
    save_frames: bool,
    fps_tag: str,
) -> list[dict[str, Any]]:
    live_state = _simulate_live(confirmed)
    rows: list[dict[str, Any]] = []
    by_index_sample = {s.index: s for s in samples}
    for raw, conf in zip(raw_frames, confirmed, strict=True):
        sample = by_index_sample[raw.frame_index]
        live = live_state.get(conf.game_t_ms, {})
        row: dict[str, Any] = {
            "game_t_ms": conf.game_t_ms,
            "frame_index": conf.frame_index,
            "coverage_raw": raw.coverage.value,
            "coverage_confirmed": conf.coverage.value,
            "raw_det_count": len(raw.candidates),
            "confirmed_det_count": len(conf.candidates),
            "raw_boxes": [_cand_dict(c) for c in raw.candidates],
            "confirmed_boxes": [_cand_dict(c) for c in conf.candidates],
            "active_track_ids": list(live.get("active_ids", [])),
            "assignments": live.get("assignments", []),
            "lifecycle_events": live.get("events", []),
            "in_loss_band": LOSS_BAND_START_MS <= conf.game_t_ms <= LOSS_BAND_END_MS,
            "in_focus": FOCUS_START_MS <= conf.game_t_ms <= FOCUS_END_MS,
        }
        if save_frames and row["in_focus"]:
            path = _save_annotated_frame(
                sample.pixels,
                game_t_ms=conf.game_t_ms,
                raw=raw,
                confirmed=conf,
                fps_tag=fps_tag,
            )
            row["frame_jpeg"] = str(path.relative_to(SPIKE_ROOT))
            row["viewport_stats"] = _viewport_stats(sample.pixels)
        rows.append(row)
    return rows


def _simulate_live(frames: Sequence[FrameDetections]) -> dict[int, dict[str, Any]]:
    tracks = finalize_tracks(track_candidates(frames))
    by_t: dict[int, dict[str, Any]] = {}
    for frame in frames:
        by_t[frame.game_t_ms] = {"active_ids": [], "assignments": [], "events": []}
    for track in tracks:
        for obs in track.observations:
            slot = by_t.setdefault(
                obs.game_t_ms, {"active_ids": [], "assignments": [], "events": []}
            )
            slot["active_ids"].append(track.track_id)
            slot["assignments"].append(
                {
                    "track_id": track.track_id,
                    "region": _rect_dict(obs.region),
                    "lifecycle": obs.lifecycle.value,
                    "team": obs.team_estimate.value,
                    "conf": obs.confidence,
                }
            )
        for event in track.events:
            slot = by_t.setdefault(
                event.game_t_ms, {"active_ids": [], "assignments": [], "events": []}
            )
            slot["events"].append({"track_id": event.track_id, "kind": event.kind.value})
    return by_t


def _tracker_counterfactuals(
    confirmed_payload: Sequence[Mapping[str, Any]],
) -> list[dict[str, Any]]:
    frames = tuple(
        FrameDetections(
            frame_index=int(item["frame_index"]),
            game_t_ms=int(item["game_t_ms"]),
            coverage=ViewportCoverage(str(item["coverage"])),
            candidates=tuple(
                FrameCandidate(
                    region=_rect_from_dict(c["region"]),
                    confidence=float(c["confidence"]),
                    ally_like=c.get("ally_like"),
                    kind=CandidateKind(str(c.get("kind", "CHAMPION_LIKE"))),
                )
                for c in item["candidates"]
            ),
        )
        for item in confirmed_payload
    )
    variants = [
        TrackerParams("default", MISS_GRACE_FRAMES, LONG_GAP_FRAMES),
        TrackerParams("miss_grace_4", 4, LONG_GAP_FRAMES),
        TrackerParams("miss_grace_6", 6, LONG_GAP_FRAMES),
        TrackerParams("long_gap_16", MISS_GRACE_FRAMES, 16),
        TrackerParams("miss_grace_4_long_16", 4, 16),
        TrackerParams("miss_grace_8_long_24", 8, 24),
    ]
    assoc_variants: list[tuple[str, float, float]] = [
        ("assoc_center_96_iou_0.08", 96.0, 0.08),
        ("assoc_center_120_iou_0.05", 120.0, 0.05),
        ("assoc_center_160_iou_0.03", 160.0, 0.03),
    ]
    out: list[dict[str, Any]] = []
    for params in variants:
        tracks = finalize_tracks(
            track_candidates(frames, miss_grace=params.miss_grace, long_gap=params.long_gap)
        )
        out.append(_counterfactual_summary(params.name, tracks, params=asdict(params)))
    import riftlens.visual.track as track_mod

    for name, center, iou in assoc_variants:
        old_c, old_i = track_mod.MATCH_CENTER_PX, track_mod.MATCH_IOU
        track_mod.MATCH_CENTER_PX = center
        track_mod.MATCH_IOU = iou
        try:
            tracks = finalize_tracks(track_candidates(frames))
            out.append(
                _counterfactual_summary(
                    name,
                    tracks,
                    params={"match_center_px": center, "match_iou": iou},
                )
            )
        finally:
            track_mod.MATCH_CENTER_PX = old_c
            track_mod.MATCH_IOU = old_i
    return out


def _counterfactual_summary(
    name: str, tracks: Sequence[EntityTrack], *, params: Mapping[str, Any]
) -> dict[str, Any]:
    champ = [t for t in tracks if t.kind is CandidateKind.CHAMPION_LIKE]
    near = disappearing_near(champ, DEATH_T_MS, window_ms=DEATH_ALIGN_MS)
    latest = max((t.last_seen_game_t_ms for t in champ), default=None)
    gap = None if latest is None else DEATH_T_MS - latest
    return {
        "name": name,
        "params": dict(params),
        "track_count": len(champ),
        "longest_duration_ms": max(
            (t.last_seen_game_t_ms - t.first_seen_game_t_ms for t in champ), default=0
        ),
        "latest_last_seen_ms": latest,
        "end_to_death_ms": gap,
        "disappearing_near_death": [t.track_id for t in near],
        "unique_near_death": len(near) == 1,
        "tracks": [_track_summary(t) for t in champ],
        "reaches_death_window": bool(near),
    }


def _duplicate_analysis(tracks: Sequence[EntityTrack]) -> dict[str, Any]:
    champ = [t for t in tracks if t.kind is CandidateKind.CHAMPION_LIKE]
    pairs: list[dict[str, Any]] = []
    for i, a in enumerate(champ):
        for b in champ[i + 1 :]:
            overlap_start = max(a.first_seen_game_t_ms, b.first_seen_game_t_ms)
            overlap_end = min(a.last_seen_game_t_ms, b.last_seen_game_t_ms)
            if overlap_end < overlap_start:
                continue
            ious: list[float] = []
            dists: list[float] = []
            for oa in a.observations:
                ob = min(b.observations, key=lambda x: abs(x.game_t_ms - oa.game_t_ms))
                if abs(ob.game_t_ms - oa.game_t_ms) > 300:
                    continue
                ious.append(_iou(oa.region, ob.region))
                dists.append(_center_dist(oa.region, ob.region))
            pairs.append(
                {
                    "a": a.track_id,
                    "b": b.track_id,
                    "overlap_ms": overlap_end - overlap_start,
                    "a_team": a.team_estimate.value,
                    "b_team": b.team_estimate.value,
                    "mean_iou": None if not ious else round(float(np.mean(ious)), 3),
                    "mean_center_dist_px": None if not dists else round(float(np.mean(dists)), 1),
                    "max_iou": None if not ious else round(float(max(ious)), 3),
                    "min_center_dist_px": None if not dists else round(float(min(dists)), 1),
                    "likely_same_region": bool(ious) and float(np.mean(ious)) >= 0.35,
                    "likely_distinct_side_by_side": bool(dists)
                    and float(np.mean(dists)) >= 40.0
                    and (not ious or float(np.mean(ious)) < 0.2),
                }
            )
    focus = [p for p in pairs if {p["a"], p["b"]} == {"trk_0003", "trk_0004"}]
    return {"pairs": pairs, "trk_0003_0004": focus[0] if focus else None}


def _classify_cases(
    baseline: Mapping[str, Any], tracks: Sequence[EntityTrack]
) -> dict[str, Any]:
    timeline = list(baseline["timeline_focus"])
    after_all = list(baseline["summary"].get("detections_after_latest_last_seen") or [])
    champ = list(tracks)
    if not champ:
        return {"primary_case": "Case D", "detail": "no champion-like tracks"}
    longest = max(champ, key=lambda t: t.last_seen_game_t_ms - t.first_seen_game_t_ms)
    loss_t = longest.last_seen_game_t_ms
    after = [row for row in after_all if int(row["game_t_ms"]) > loss_t]
    cases_per_track: list[dict[str, Any]] = []
    for track in sorted(champ, key=lambda t: t.track_id):
        t_loss = track.last_seen_game_t_ms
        following = [r for r in after_all if int(r["game_t_ms"]) > t_loss][:8]
        focus_following = [r for r in timeline if int(r["game_t_ms"]) > t_loss][:8]
        confirmed_next = sum(int(r["confirmed_det_count"]) for r in following)
        raw_next = sum(int(r["raw_det_count"]) for r in following)
        if not following:
            # Distinguish EOF of media (track ends on last sample) vs mid-stream loss.
            last_sample = baseline["summary"].get("last_sample_ms")
            if last_sample is not None and int(t_loss) >= int(last_sample):
                case = "Case D"
                why = (
                    "track ends on final sampled frame; media/clip ends before GST death "
                    f"(last_sample_ms={last_sample}, death={DEATH_T_MS})"
                )
            else:
                case = "Case D"
                why = "no later sampled frames after last_seen"
        elif any(r["coverage_confirmed"] != "USEFUL" for r in following[:3]):
            case = "Case D"
            why = "viewport coverage not USEFUL after loss"
        elif confirmed_next == 0 and raw_next == 0:
            stats = [
                r.get("viewport_stats")
                for r in focus_following
                if isinstance(r.get("viewport_stats"), dict)
            ]
            center_activity = (
                float(np.mean([float(s["center_sat_mean"]) for s in stats])) if stats else None
            )
            if center_activity is not None and center_activity < 25.0:
                case = "Case C"
                why = "no detections + low center saturation after loss"
            else:
                case = "Case B_or_C"
                why = (
                    "no raw/confirmed detections after last observation; "
                    f"center_sat_mean={center_activity}"
                )
        elif confirmed_next == 0 and raw_next > 0:
            case = "Case B"
            why = "raw detections exist but temporal confirmation dropped them"
        else:
            case = "Case A"
            why = "confirmed detections continue after track last_seen"
        cases_per_track.append(
            {
                "track_id": track.track_id,
                "last_seen_ms": t_loss,
                "end_to_death_ms": DEATH_T_MS - t_loss,
                "case": case,
                "why": why,
                "next_confirmed_dets": confirmed_next,
                "next_raw_dets": raw_next,
                "next_frames": [
                    {
                        "t": r["game_t_ms"],
                        "raw": r["raw_det_count"],
                        "confirmed": r["confirmed_det_count"],
                        "coverage": r["coverage_confirmed"],
                    }
                    for r in following
                ],
            }
        )
    primary = "UNKNOWN"
    for item in cases_per_track:
        if item["track_id"] == longest.track_id:
            primary = str(item["case"])
            break
    return {
        "primary_track": longest.track_id,
        "primary_case": primary,
        "loss_t_ms": loss_t,
        "det_counts_after_loss": [int(r["confirmed_det_count"]) for r in after[:20]],
        "raw_counts_after_loss": [int(r["raw_det_count"]) for r in after[:20]],
        "useful_frames_after_loss": sum(1 for r in after if r["coverage_confirmed"] == "USEFUL"),
        "per_track": cases_per_track,
    }


def _feasibility(
    *,
    baseline: Mapping[str, Any],
    higher: Mapping[str, Any],
    counterfactuals: Sequence[Mapping[str, Any]],
    media: Mapping[str, Any],
    case: Mapping[str, Any],
) -> dict[str, Any]:
    base_gap = baseline["summary"]["min_end_to_death_ms"]
    high_gap = higher["summary"]["min_end_to_death_ms"]
    scored = [c for c in counterfactuals if c.get("end_to_death_ms") is not None]
    best = min(scored, key=lambda c: int(c["end_to_death_ms"]), default=None)
    best_gap = None if best is None else best["end_to_death_ms"]
    any_reach = any(bool(c.get("reaches_death_window")) for c in counterfactuals)
    higher_reach = bool(higher["summary"]["disappearing_near_death"])
    unique_ok = any(
        bool(c.get("reaches_death_window")) and bool(c.get("unique_near_death"))
        for c in counterfactuals
    ) or (higher_reach and len(higher["summary"]["disappearing_near_death"]) == 1)

    if not bool(media.get("death_in_file")):
        verdict = "TRACK_CONTINUITY_NOT_FIXABLE"
        rec = (
            "Primary failure is Case D: encoded clip ends before GST death "
            f"(~{media.get('duration_s')}s media, shortfall_to_death_ms="
            f"{media.get('shortfall_to_death_ms')}). Tracker/detector parameter "
            "tweaks cannot invent frames past EOF. Fix R.10 Mac encode duration / "
            "finalize so the requested interval actually reaches death, then re-run "
            "continuity diagnosis — do not widen DEATH_ALIGN_MS or start V.6 ranking."
        )
    elif (any_reach or higher_reach) and unique_ok:
        verdict = "TRACK_CONTINUITY_FIXABLE"
        rec = (
            "Small classical tracker miss-grace/association tuning on existing detections "
            "can uniquely reach ±2s of GST death — next step is an isolated continuity fix."
        )
    elif any_reach or higher_reach:
        verdict = "TRACK_CONTINUITY_PARTIAL"
        rec = (
            "Some counterfactuals reach the death window but not uniquely. Continuity may "
            "help, but uniqueness/fragmentation still blocks safe LIKELY."
        )
    elif best_gap is not None and base_gap is not None and best_gap < base_gap and best_gap <= 3500:
        verdict = "TRACK_CONTINUITY_PARTIAL"
        rec = (
            "Parameter tweaks shorten end→death gap but do not enter ±2000 ms. "
            "Detector dropout / on-screen bar loss is the next place to look."
        )
    else:
        verdict = "TRACK_CONTINUITY_NOT_FIXABLE"
        rec = (
            "Offline tracker/sampling counterfactuals do not produce a death-aligned track."
        )
    return {
        "verdict": verdict,
        "primary_case": case.get("primary_case"),
        "baseline_end_to_death_ms": base_gap,
        "higher_fps_end_to_death_ms": high_gap,
        "best_legitimate_end_to_death_ms": best_gap,
        "best_counterfactual": None if best is None else best["name"],
        "any_counterfactual_reaches_death_window": any_reach,
        "higher_fps_reaches_death_window": higher_reach,
        "death_in_media": bool(media.get("death_in_file")),
        "can_existing_classical_stack_hit_pm_2000_without_unsafe_identity": False
        if not media.get("death_in_file")
        else bool((any_reach or higher_reach) and unique_ok),
        "recommended_next": rec,
    }


def _save_annotated_frame(
    pixels: np.ndarray,
    *,
    game_t_ms: int,
    raw: FrameDetections,
    confirmed: FrameDetections,
    fps_tag: str,
) -> Path:
    bgr = cv2.cvtColor(pixels, cv2.COLOR_RGB2BGR)
    for cand in raw.candidates:
        r = cand.region
        cv2.rectangle(
            bgr, (int(r.x), int(r.y)), (int(r.x + r.width), int(r.y + r.height)), (255, 128, 0), 1
        )
    for cand in confirmed.candidates:
        r = cand.region
        cv2.rectangle(
            bgr, (int(r.x), int(r.y)), (int(r.x + r.width), int(r.y + r.height)), (0, 255, 0), 2
        )
    label = (
        f"t={game_t_ms} raw={len(raw.candidates)} conf={len(confirmed.candidates)} "
        f"cov={confirmed.coverage.value}"
    )
    cv2.putText(bgr, label, (12, 28), cv2.FONT_HERSHEY_SIMPLEX, 0.7, (255, 255, 255), 2)
    path = ARTIFACTS / "frames" / f"f{fps_tag}_{game_t_ms}.jpg"
    cv2.imwrite(str(path), bgr, [int(cv2.IMWRITE_JPEG_QUALITY), 75])
    return path


def _viewport_stats(pixels: np.ndarray) -> dict[str, float | str]:
    h, w = pixels.shape[:2]
    center = pixels[h // 3 : 2 * h // 3, w // 3 : 2 * w // 3]
    hsv = cv2.cvtColor(center, cv2.COLOR_RGB2HSV)
    gray = cv2.cvtColor(center, cv2.COLOR_RGB2GRAY)
    return {
        "center_sat_mean": float(np.mean(hsv[:, :, 1])),
        "center_val_mean": float(np.mean(hsv[:, :, 2])),
        "center_gray_std": float(np.std(gray)),
        "coverage": classify_viewport(pixels).value,
    }


def _track_summary(track: EntityTrack) -> dict[str, Any]:
    return {
        "track_id": track.track_id,
        "kind": track.kind.value,
        "team": track.team_estimate.value,
        "obs": track.observation_count,
        "first_ms": track.first_seen_game_t_ms,
        "last_ms": track.last_seen_game_t_ms,
        "duration_ms": track.last_seen_game_t_ms - track.first_seen_game_t_ms,
        "confidence": track.confidence,
        "closed_reason": None if track.closed_reason is None else track.closed_reason.value,
        "ambiguous": track.ambiguous,
        "fragmented": track.fragmented,
        "end_to_death_ms": DEATH_T_MS - track.last_seen_game_t_ms,
    }


def _cand_dict(c: FrameCandidate) -> dict[str, Any]:
    return {
        "region": _rect_dict(c.region),
        "confidence": c.confidence,
        "ally_like": c.ally_like,
        "kind": c.kind.value,
    }


def _rect_dict(r: ScreenRect) -> dict[str, int]:
    return {"x": int(r.x), "y": int(r.y), "width": int(r.width), "height": int(r.height)}


def _rect_from_dict(payload: Mapping[str, Any]) -> ScreenRect:
    return ScreenRect(
        x=int(payload["x"]),
        y=int(payload["y"]),
        width=int(payload["width"] if "width" in payload else payload["w"]),
        height=int(payload["height"] if "height" in payload else payload["h"]),
    )


def _iou(a: ScreenRect, b: ScreenRect) -> float:
    ax2, ay2 = a.x + a.width, a.y + a.height
    bx2, by2 = b.x + b.width, b.y + b.height
    ix1, iy1 = max(a.x, b.x), max(a.y, b.y)
    ix2, iy2 = min(ax2, bx2), min(ay2, by2)
    iw, ih = max(0, ix2 - ix1), max(0, iy2 - iy1)
    inter = iw * ih
    if inter <= 0:
        return 0.0
    union = a.width * a.height + b.width * b.height - inter
    return float(inter / union) if union else 0.0


def _center_dist(a: ScreenRect, b: ScreenRect) -> float:
    ax, ay = a.x + a.width / 2.0, a.y + a.height / 2.0
    bx, by = b.x + b.width / 2.0, b.y + b.height / 2.0
    return float(((ax - bx) ** 2 + (ay - by) ** 2) ** 0.5)


if __name__ == "__main__":
    raise SystemExit(main())
