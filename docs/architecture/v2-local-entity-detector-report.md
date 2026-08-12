# V.2 — Robust local champion-like entity detection

**Status:** complete (local research spike, not production)  
**Date:** 2026-08-12  
**Branch:** `r1-gameplay-source-domain`  
**Does not change coaching, overlay, R.10 capture, R-012, or H.6/H.7/H.8.**

V.2 asks whether a **local** detector can produce cleaner champion-like candidates than V.0 health bars, so the unchanged V.1 tracker fragments less — without cloud vision, champion naming, fog, or coaching.

## Objective

V.1 established that tracking is cheap (~37 ms) and that 38 champion-like tracks on the unrelated 18:30 clip were dominated by unreliable V.0 bars. Participant/champion identity stayed UNKNOWN. The actual R-012 Kaisa window (~22:20) had no visual artifact.

V.2 therefore:

1. Replaces per-frame bar-as-entity with a hybrid classical detector (HUD mask, geometry filter, stacked-bar clustering, body box, temporal confirmation).
2. Feeds those detections into the **existing** V.1 tracker.
3. Measures fragmentation explicitly against V.1.
4. Attempts the exact Kaisa 22:20 capture if Replay API / League is available; otherwise stops T4 rather than substituting 18:30 as the target.

V.2 does **not** understand fog-of-war, tactics, or coaching.

## Detector candidates evaluated

| Approach | Verdict |
|---|---|
| **A. Improved classical** (HUD mask, bar geometry, body expand, temporal confirm) | **Chosen.** No new dependency. Deterministic. CPU. License-clean. |
| **B. Lightweight learned (YOLO / ONNX)** | **Rejected.** Ultralytics YOLO is AGPL-3.0. No redistributable League-champion weights with a clear license. COCO person/object weights will not detect League champions. Runtime download of unpinned “latest” weights is forbidden. A hundreds-of-MB model is not justified when the failure mode is HUD chrome + short bars, which classical filters address. |
| **C. Hybrid classical + learned verifier** | **Not shipped.** Same license/weight problem as B. Classical proposal + V.1 tracker continuity is the hybrid that *was* shipped (no learned verifier). |

If a future V.3 learned detector is considered: it must be local, CPU-capable, pinned SHA256, and have a clear redistribution license. Do not ship an unlicensed LoL-trained weight as a “spike” in the repo.

### Chosen detector (A / classical hybrid)

No new packages. No model file. No GPU.

| Item | Value |
|---|---|
| Dependency | existing `opencv-python-headless`, `numpy`, `av` |
| Package / model size | 0 extra |
| CPU | required (already) |
| GPU | not used / not required |
| License | same as V.0/V.1 (OpenCV/numpy/PyAV) |
| Redistribution | unchanged |
| Startup | no model load |
| Runtime | detect still dominates; similar to V.1 at 4 fps |

`analyzer_id=riftlens.visual.v2.entity` `analyzer_version=v2.0` `detector_source=v2.hybrid`.

## Pipeline

```
R.10 clip
  → sample @ 4 fps (V.1 default)
  → HUD/UI mask (resolution-relative)
  → V.0 HSV bar proposals on the masked frame
  → reject HUD-centered + non-champion geometry
  → cluster stacked/duplicate bars
  → expand to a body box under the bar
  → temporal confirm (±2 samples or conf ≥ 0.72)
  → V.1 tracker (unchanged)
  → GST align + subject correlate (unchanged conservative rules)
  → R.11 FrameObservation / ObservationSequence
```

### Preprocessing

- Copy frame; zero resolution-relative HUD bands: header (top 8%), bottom HUD (y≥84%), minimap (left 18% × bottom 32%), kill-feed (right 22% × 8–30% height), replay controls (right 30% × bottom 12%), thin left/right chrome (3.5% width).
- Does not analyze the minimap. Masking it is exclusion, not vision reconstruction.
- Gameplay entities whose **center** sits outside those bands are kept.

### Inference

Classical only. Reuses `detect_champion_like_bars` (HSV green/red, existing OpenCV). No ONNX/Torch.

Champion-bar geometry (measured on the 1904×992 18:30 capture):

- Real champion-like bars ≈ **104×9–10** px
- Persistent edge chrome / fragments ≈ **24–28** px wide

V.2 keeps bars with `width ≥ max(28, 3.5% of frame width)`, `height ≤ 12`, aspect 5.5–14.

### Postprocessing

- Cluster bars within 28×18 px (or IoU ≥ 0.25) so stacked HP/mana do not become two entities.
- Body box: bar union, padded x, height = clamp(`2.2 × bar width`, 28, 96), clamped to frame.
- Team from bar-color votes: all ally → ally; all enemy → enemy; mix → UNKNOWN.
- Temporal: keep if a neighbor exists within 80 px in ±2 samples, **or** confidence ≥ 0.72. One-frame flashes drop; two-sample entries/exits stay.
- Cap: if >10 gameplay bars remain after HUD filter, the frame is treated as noise (same V.0 `MAX_PLAUSIBLE_CHAMPIONS`).

### Team classification

ALLY / ENEMY / UNKNOWN from health-bar color, same V.1 semantics. Confidence still capped by the tracker. Team **never** implies participant or champion id. On the 18:30 clip, surviving V.2 entities were predominantly **enemy-like** (the 104 px red bars); many V.1 “ally-like” counts were left-edge chrome.

## V.1 tracker compatibility

Tracker code is unchanged: IoU+center greedy match, miss grace 2, long gap 8, AMBIGUOUS rather than identity swap.

V.2 detections are `FrameCandidate` with `kind=CHAMPION_LIKE` and a body `ScreenRect` instead of a thin bar. That is the only integration change.

## Fragmentation metrics

`riftlens.visual.metrics.TrackMetrics`:

- total detections / tracks
- stable tracks (V.1 `stable_track_count`)
- tracks lasting ≥1 s / ≥3 s
- one-frame tracks
- fragmented/ambiguous tracks
- average observations per track
- median track duration
- mean detections per frame

## Exact Kaisa 22:20 capture — STOPPED

Finding `01KZQ45QZ52C6CVMPHXZQ9VY24` R-012 at **22:20.491** (`1340491` ms). Planned GAME window **1328491–1355491** (22:08–22:35). Source `01KZMXVW4153FVKNXYRJWFM6YV`, ClockMap `01KZMY2BN0GGHK7T6BCGH8Q6XS`, review `01KZQ45RNRVBG5KYTF1WP2ZQEZ`.

`scripts/v2_finding_capture.py` without `RIFTLENS_V2_T4=1` returns typed `CAPTURE_NOT_REQUESTED`. League / Riot Client / Replay API were **not running** this session. No process matched League/Riot.

All local complete captures for `NA1_5617764200` are **18:30–18:55** (`1110000–1135000`). None cover 22:08–22:35.

**Real T4 was not run.** The 18:30 clip is **not** treated as the R-012 target. No 22:20 `capture_id` / `media_artifact_id` exists to report.

## GST in the planned 22:20 window (read-only, not visual)

Verified from the local GST (not hardcoded into detector logic):

| GAME | Killer | Victim | Subject (pid 9 Kaisa) |
|---|---|---|---|
| 22:20.491 | 9 Kaisa | 5 Seraphine | killer |
| 22:24.699 | 4 Vayne | 10 Morgana | — |
| 22:25.768 | 7 Zac (+ Kaisa assist) | 4 Vayne | assist |
| 22:32.527 | 3 Mel (+ Quinn/Lillia/Vayne) | 7 Zac | — |
| 22:34.665 | 3 Mel (+ Quinn/Lillia/Vayne) | **9 Kaisa** | victim |

These remain GST facts. They are not `Source.VISUAL`.

## 18:30 benchmark (not the R-012 window)

Same artifact as V.0/V.1, used only to compare detectors.

| Field | Value |
|---|---|
| Capture | `01KZQPZFMMZDR9DB4Y3NQ2ADSV` |
| Artifact | `01KZQQ09M8NHP1N06CCXAEJDAD` |
| Source | `01KZMXVW4153FVKNXYRJWFM6YV` |
| ClockMap | `01KZMY2BN0GGHK7T6BCGH8Q6XS` |
| GAME | 18:30–18:55 (`1110000`–`1135000`) |
| SOURCE | `1110623`–`1135623` |
| Frame size | 1904×992 |
| Sample rate | 4 fps |
| Decoded / analyzed | 101 / 101 |
| Camera | `UNCONTROLLED` |

### Detection + track comparison

| Metric | V.1 (baseline bars) | V.2 (hybrid) |
|---|---:|---:|
| Total detections | 664 | **91** |
| Mean detections / frame | 6.574 | **0.901** |
| Total tracks | 38 | **14** |
| Stable tracks | 25 | 7 |
| Tracks ≥1 s | 17 | 5 |
| Tracks ≥3 s | 10 | 2 |
| One-frame tracks | 13 | **7** |
| Fragmented/ambiguous | 0 | 0 |
| Avg observations / track | 17.474 | 6.5 |
| Median duration (ms) | 616.5 | 116.5 |
| Peak stable in one frame | 10 | **2** |
| Subject correlation | UNKNOWN | UNKNOWN |
| Extract (ms) | 3289 | 2997 |
| Detect (ms) | 8012 | 6635 |
| Track (ms) | 26 | 2.5 |
| Align (ms) | 0.2 | 0.0 |
| Total (ms) | 11347 | 9643 |

V.1’s high “stable” and “≥3 s” counts were largely **persistent 24–28 px edge chrome** (left x≈38 and right x≈1838), misread as ally-like champions. Those bars survive for the whole clip, so they look “stable.” V.2 drops them.

Temporal confirmation dropped **0** of 91 remaining detections on this clip (raw=confirmed=91): after geometry/HUD filters, survivors already persist. The synthetic suite still proves one-frame flash rejection and entry/exit preservation.

### Honest reading

- **Precision:** clearly better. Occupancy ~7/frame → ~1/frame matches the 104 px champion-like bars actually present early in the clip (typically 0–1 enemy-like).
- **Fragmentation of true entities:** reduced track *count*, but remaining champion-like tracks still split (trk_0001/0002/0003 around 18:30; a burst of five ids at 18:46). Body boxes + clustering did not give one long identity per champion.
- **Recall:** V.2 may miss small/distant/partial bars (width below 3.5% of frame). That is preferred to V.1’s overcount, and is reported rather than hidden.
- **Subject:** still UNKNOWN. Correct: no GST subject death in this window; capture ownership ignored.

Do not treat 18:30 occupancy as R-012 evidence.

## 22:20 visual questions

**Not answered from pixels.** No artifact.

What V.2 would measure on a future 22:08–22:35 clip, without coaching labels:

1. How many stable champion-like tracks exist early
2. Whether additional stable tracks appear later
3. Ally/enemy track counts where color is reliable
4. Whether a likely subject track exists
5. Whether that track remains visible across the sequence
6. Whether additional tracks appear before subject death
7. Whether track timing aligns with the GST kills above
8. Whether camera coverage is `USEFUL`

Until that clip exists, all eight are UNKNOWN.

## R-012 research diagnostic (finding not mutated)

| Layer | Result |
|---|---|
| A. GST | Unchanged from V.1: Kaisa kills Seraphine at 22:20, dies to Mel at 22:34 with additional enemy participation in between. |
| B. Direct VISUAL | **INSUFFICIENT_VISUAL_EVIDENCE** for 22:20 (no capture). |
| C. VISUAL_INFERRED | None for 22:20. |
| D. UNKNOWN | Subject track, viewport occupancy, ally/enemy counts, camera usefulness, vision/fog, champion ids. |

18:30 V.2 diagnostic is irrelevant to R-012 (wrong window). Do not rewrite the finding.

## Subject correlation

V.1 `correlate_subject` reused unchanged:

- Capture ownership → ignored
- Team color alone → UNKNOWN
- Unique disappearance near GST subject death → LIKELY (cap 0.55)
- Death + subject-perspective team + `CONTROLLED_SUBJECT` → CORRELATED (cap 0.75)
- Conflicts / weak support → UNKNOWN

18:30 result: **UNKNOWN**. 22:20: not attempted (no clip). R.10 captures remain `camera_controlled=false`.

## R.11 output

Unchanged contract:

- Direct detections: `Source.VISUAL`, `claim_kind=OBSERVED`, `observation_type=champion_like_track`
- Correlation (only if LIKELY/CORRELATED): `Source.VISUAL_INFERRED`, `subject_track_correlation`
- Sequence records `detector_id` / `detector_version` (`riftlens.visual.v2.entity` / `v2.0`)
- Payload tracks include `track_id`, lifecycle, team estimate
- No participant_id / champion_id on observed entities
- HUD / minimap / vision: UNKNOWN
- GAME + SOURCE timestamps from the R.10 manifest

## Performance

Local Windows CPU, no GPU. One RGB frame at a time (~1904×992×3 ≈ 5.7 MB) plus a handful of track records.

| | V.0 | V.1 | V.2 |
|---|---|---|---|
| Rate | 2 fps / 51 frames | 4 fps / 101 | 4 fps / 101 |
| 25 s 18:30 clip | ~6 s | ~11.3 s (this session; V.1 report had 23.3 s) | **~9.6 s** |
| Detect share | most | most | most |
| Track | n/a | 26 ms | 2.5 ms |

V.1’s earlier 23.3 s was the same pipeline on a colder disk/CPU; this session’s 11.3 s is the paired A/B. Relative to that pair, V.2 is slightly faster (fewer candidates). Still plausible for research clips. Not instant.

## Tests

`tests/unit/test_visual_v2.py`:

- Valid champion-like detection; empty frame; noisy background
- HUD header / kill-feed rejection; replay-resolution 104×10 kept vs 28 px edge chrome dropped
- Stacked bars cluster to one entity; partial bar rejected
- Ally vs enemy color; team does not imply identity
- Temporal: one-frame noise dropped; entering/leaving preserved; strong standalone kept
- Two moving entities → two tracks; crossing does not invent identity
- V.2 → V.1 tracker; synthetic fragmentation not worse
- Subject: strong → CORRELATED; unique death → LIKELY; conflict/weak → UNKNOWN
- R.11 schema + VISUAL provenance + detector version
- No ONNX/ultralytics/openai in `detect_v2.py`
- Coaching RuleEngine unchanged

V.0 and V.1 tests remain the regression suite.

## Files

Created:

- `riftlens/visual/hud_mask.py`
- `riftlens/visual/detect_v2.py`
- `riftlens/visual/metrics.py`
- `riftlens/visual/v2_analyze.py`
- `scripts/v2_finding_capture.py`
- `tests/unit/test_visual_v2.py`
- this report

Modified:

- `riftlens/visual/{report,__init__,__main__}.py`

Unchanged: V.0 `analyze.py`, V.1 tracker / correlate / gst_align / window, coaching, overlay, R-012, H.6/H.7/H.8.

## Recommendation for V.3 (do not implement)

Smallest next visual phase, based on V.2 evidence:

1. **Capture and analyze the actual 22:08–22:35 Kaisa window** with this detector. R-012 still has INSUFFICIENT_VISUAL_EVIDENCE. A better detector cannot answer the eight visual questions without that clip.
2. If that fight still fragments true champions, add **short-term motion/body-texture persistence** on the existing body box — still classical, still local — before buying a learned model.
3. Only then consider a **licensed, pinned, CPU ONNX** champion-like detector. Do not start with COCO-YOLO or an unlicensed LoL weight.
4. Champion identity, subject trajectory, fight-phase, and minimap/fog remain later. V.2 did not show that minimap is the next bottleneck; the missing 22:20 pixels are.

Do not start H.10 or R.12 from this spike.

## Limitations

- 22:20 clip not captured (Replay API / League unavailable)
- Still health-bar based; occluded / unbarred champions are missed
- True-entity fragmentation remains (new track ids after flicker beyond miss grace)
- No champion recognition
- Team color is HUD-relative and unused for identity
- Temporal confirmation barely fires on real clips once chrome is gone
- LEFT_VIEW is not death; off-camera is not fog
- 18:30 improvement is precision, not a solved identity tracker
- No learned model; if classical stalls on 22:20, that is a measured next decision, not a hidden failure

## UNKNOWN safety

Preserved: weak detection omitted; weak correlation UNKNOWN; off-camera ≠ absent; minimap not analyzed → vision UNKNOWN; ambiguous team UNKNOWN.
