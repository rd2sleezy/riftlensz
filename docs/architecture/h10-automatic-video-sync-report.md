# H.10 — Automatic VIDEO Synchronization

**Date:** 2026-08-16  
**Branch:** `integrate/ui-r1`  
**Does not implement:** H.11, R.12, V.7, LLM narration, overlay, ReplayHost, native ROFL clock calibration, coaching, GST/metrics/rules.

Companion to [`h9-1-clock-ocr-layout-report.md`](./h9-1-clock-ocr-layout-report.md) and [`h9-1-real-clock-corpus-validation-report.md`](./h9-1-real-clock-corpus-validation-report.md).

---

## 1. Architecture implemented

```
VideoGameplaySource / VOD path
        ↓
H.9.1 ClockReading[]   (or caller-supplied readings)
        ↓
filter (confidence ≥ 0.8, integer ms, no OCR repair)
        ↓
pause detect  →  cut/offset segmentation  →  multi-game guard
        ↓
constrained RANSAC (|a−1| ≤ 0.02, ±400 ms inliers)
        ↓
final pieces: slope = 1.0, offset only  →  SyncMap
        ↓
independent verify (held-out OCR, monotonicity, pauses vs PAUSE_END)
        ↓
ClockMap.from_sync_map  +  persist/cache (content_hash, match_id, algo_version)
```

Native `.rofl` stays on Replay API / `CalibratedReplayClockMap`. Auto-sync rejects ROFL `gameplay_source_id`. Manual `POST /sync/manual` is unchanged.

## 2. Files added/changed

**Added (sidecar)**

| Path | Role |
|---|---|
| `riftlens/pipeline/sync/errors.py` | Typed auto-sync failures |
| `riftlens/pipeline/sync/filter.py` | Confidence / plausibility filter |
| `riftlens/pipeline/sync/segments.py` | Pause, cut, multi-game |
| `riftlens/pipeline/sync/fitter.py` | Constrained RANSAC + slope-1 fit |
| `riftlens/pipeline/sync/verify.py` | Independent verification |
| `riftlens/pipeline/sync/quality.py` | EXCELLENT/GOOD/DEGRADED/FAILED |
| `riftlens/pipeline/sync/manual.py` | Re-export of existing manual builder |
| `riftlens/pipeline/sync/cache.py` | Persist + algo-version cache |
| `riftlens/pipeline/sync/service.py` | VIDEO orchestration |
| `tests/unit/test_auto_sync_h10.py` | Scenarios A–D + unit coverage |
| `tests/unit/test_sync_api_h10.py` | API, cache, ROFL reject, manual safety |

**Changed (sidecar)**

| Path | Role |
|---|---|
| `riftlens/api/sync.py` | `POST /sync/auto`, `GET /sync/{id}` |
| `riftlens/domain/ports.py` | `MediaRepository.get_by_content_hash` |
| `riftlens/adapters/db/repositories/media.py` | Hash lookup |

**Desktop (thin VIDEO UI, no fitting math)**

IPC `runAutoSync` → sidecar; review `AutoSyncBar`; uncovered timestamps disabled/grey; gameplay bar shows auto-sync quality.

No Alembic migration: existing `sync_map` + `media_asset.content_hash` + quality JSON `algo_version` are sufficient.

## 3. ClockReading input handling

Before fit:

- drop `t_game_ms is None`
- drop `confidence < 0.8`
- reject negative times and `>90` minutes
- reject decreasing video timestamps (counted, not repaired)
- **keep** repeated `t_game_ms` (pause evidence)

Filter accepted/rejected counts and reason labels are returned on the API (`filter.reasons`).

## 4. RANSAC implementation

`constrained_ransac` in `fitter.py`:

- model `t_game ≈ a * t_video + b`
- reject hypotheses with `|a - 1.0| > 0.02`
- inlier band ±400 ms
- `random.Random(seed=10)`, 200 iterations (deterministic)
- fallback: slope-1 median offset inliers if no constrained pair succeeds

This is gross structure only. Final segments always use slope **exactly 1.0**.

## 5. Segmentation model

1. Detect pauses (≥3 identical `t_game_ms` while video advances).
2. Remove pause samples from linear fitting.
3. Split remaining points on **sustained** offset jumps (~2 s, confirmed over 3 samples) so isolated OCR outliers do not fragment the timeline.
4. RANSAC + median offset per group.
5. Segment coverage is the inlier video span (end exclusive). Pause video is **not** mapped, so freeze cannot drift the offset.

## 6. Pause handling

OCR freeze → `PauseInterval` on the `SyncMap`. GST `PAUSE_END` events (timeline rows or request field) cross-check within ±5 s. Missing GST does not invent a pause, but blocks EXCELLENT (`pause_without_gst`).

## 7. Cut handling

A ~40 s game-time discontinuity appears as a persistent offset jump after pause removal. Each side is its own slope-1 segment. One global offset is never forced across the cut.

## 8. Multi-game handling

`MultipleGamesDetected` when:

- the HUD clock resets toward 00:00 after a ≥5 minute drop, confirmed on ≥3 samples, or
- fitted segments’ game ranges overlap

API returns `code=MULTIPLE_GAMES` and `boundaries_video_ms`. No silent single-match SyncMap. Desktop shows the boundaries and keeps manual sync.

## 9. SyncMap / ClockMap representation

Unchanged domain types. Auto method is `clock_ocr`. `ClockMap.from_sync_map` wraps the piecewise map. Uncovered `game_to_video` / `video_to_game` stay `None`. Manual maps still use `method=manual`.

## 10. Quality policy

| Verdict | Gate (transparent) |
|---|---|
| EXCELLENT | ≥30 accepted, inlier ratio ≥0.9, p95 <200 ms, coverage ≥0.8, verified, not sparse, pause GST cross-checked |
| GOOD | ≥10 accepted, inlier ≥0.8, p95 <400 ms, coverage ≥0.4, verified-or-ok, not sparse |
| DEGRADED | Model exists but weaker / sparse / unverified pause |
| FAILED | Raised as typed error rather than a usable FAILED map |

EXCELLENT is not claimed on sparse or unverified evidence.

## 11. Independent verification

`verify.py` does **not** re-run RANSAC. It:

- scores a deterministic held-out stride of linear points against the fitted map
- requires most hold-out samples to land within ±400 ms (allows ~15% OCR outliers)
- checks non-overlapping video segments and non-decreasing game mapping
- optionally matches pauses to `PAUSE_END`

Failure raises `VerificationFailed` (downgrade/fail). Kill-feed / V-series identity is not used.

## 12. Persistence / cache

Key: `(media_asset.content_hash, match_id)` plus `quality.algo_version = h10.clock_ocr.v1`.

- same media + match + version → cache hit
- different hash → miss
- same video, different match → miss
- version bump → miss

Failed auto-sync **does not upsert**, so an existing manual `sync_map` row is preserved. Successful auto may replace the row for that media+match (user asked for auto).

## 13. API

- `POST /sync/auto` — readings and/or `video_path` (triggers H.9.1), VIDEO only
- `GET /sync/{id}` — persisted map
- `POST /sync/manual` — unchanged
- `POST /sync/seek` — unchanged; uncovered stays null

Typed `ok: false` bodies: `INSUFFICIENT_READINGS`, `NO_STABLE_MODEL`, `MULTIPLE_GAMES`, `INCONSISTENT_OCR`, `INSUFFICIENT_COVERAGE`, `VERIFICATION_FAILED`, `UNSUPPORTED_SOURCE`, `MEDIA_UNAVAILABLE`.

## 14. Desktop behavior

VIDEO attached and native replay not preferred:

- **Auto-sync from clock** (progress: “Reading clock…”)
- quality badge GOOD / DEGRADED / …
- finding timestamps seekable only where covered; uncovered stay grey/disabled
- failure message + existing manual anchor bar
- `MultipleGamesDetected` surfaces boundary times; does not pick a game
- no auto-sync controls when a native replay session is the active path
- no RANSAC in React

## 15. Synthetic acceptance metrics

| Scenario | Result |
|---|---|
| A — 15% outliers, 90 s pause, 40 s cut | Offsets within 100 ms of 60000 / −30000 / 10000; pause ~90 s; 3 slope-1 segments; pause video uncovered |
| B — two 10-minute games concatenated | `MultipleGamesDetected`, boundary ~600 s |
| C — mid-game start (offset +10 min) | Mapping on covered interval; `game_to_video(0)` is None |
| D — sparse / abstentions | Succeeds DEGRADED/GOOD when ≥3 confident reads remain; 2 reads → `INSUFFICIENT_READINGS` |

## 16. Real recordings actually tested

**None in this work order.** No OBS 1080p60, 1440p, ShadowPlay, or five-VOD suite was run through auto-sync.

H.9.1 real OCR remains **PARTIAL** (41 clean crops, one 1520×982 match, mid-game only). That is not a substitute for H.10’s ≥5 diverse recordings.

## 17. Real sync error metrics

Not measured. Do not treat synthetic p95 as VOD p95.

## 18. Performance

| Case | Observation |
|---|---|
| 40 min @ 1 Hz (2400 readings) | Fit ~30 ms on this Mac (test bound <5 s) |
| Verification | Sub-millisecond on that set |
| Cache hit | DB lookup only; no RANSAC |

Fitting is cheap vs H.9.1 OCR/video sampling. Production `POST /sync/auto` with `video_path` is dominated by OCR.

## 19. Known limitations

- Real League OCR atlas/corpus still too narrow for production VOD auto-sync
- EXCELLENT almost never without GST pause cross-check
- Multi-game UX is boundary display only (no match picker)
- Auto-sync overwrites a prior manual row on **success** only
- Hold-out verification is OCR-vs-map, not independent kill timestamps

## 20. H10_ENGINEERING verdict

**H10_ENGINEERING = PASS**

Fitter, segmentation, verification, cache, APIs, ClockMap wrap, synthetic A–D, unit/API tests, sidecar verify (pytest / ruff / mypy --strict / import-linter), desktop typecheck / lint / vitest / electron-vite build.

## 21. H10_REAL_VOD_ACCEPTANCE verdict

**H10_REAL_VOD_ACCEPTANCE = BLOCKED_INSUFFICIENT_CORPUS**

Original ≥5 diverse real recordings with p95 ≤500 ms were not available/tested. H.9.1 OCR is still PARTIAL.

**Update 2026-08-16:** still blocked. See [`h9-1-h10-real-vod-validation-report.md`](./h9-1-h10-real-vod-validation-report.md). Local REAL VOD count remains 0.

## 22. Whether H.11 is genuinely unblocked

**Engineering of VIDEO SyncMap consumption:** yes — review seek can use an auto `SyncMap` when OCR is good enough.

**H.11 as the next product work order:** **no.** Do not start H.11 from this report. Production auto-sync on arbitrary League VODs remains gated on OCR corpus breadth.

Stop here.
