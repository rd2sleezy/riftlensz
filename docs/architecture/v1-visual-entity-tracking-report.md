# V.1 — Visual entity tracking, subject correlation, GST alignment

**Status:** complete (local research spike, not production)  
**Date:** 2026-08-12  
**Branch:** `r1-gameplay-source-domain`  
**Does not change coaching, overlay, R.10 capture, R-012, or H.6/H.7/H.8.**

V.1 asks whether sampled R.10 frames can be turned into **temporally persistent champion-like tracks**, optionally bound to the reviewed player via GST, without claiming fog-of-war or rewriting R-012.

## Objective

Stop treating every frame as an independent occupancy count. For an **exact finding-window capture**:

exact coaching finding timestamp  
→ explicit R.10 capture window  
→ deterministic frame sampling  
→ champion-like candidates  
→ temporal tracking  
→ optional reviewed-player correlation  
→ GST event alignment  
→ R.11 `FrameObservation[]` + `ObservationSequence`  
→ research-only visual timeline

## Architecture

| Layer | Role |
|---|---|
| `riftlens.visual.window` | Finding timestamp → planned GAME window + R.10 `CaptureRequest`. No auto-capture. |
| `riftlens.visual.detect` | V.0 health-bar heuristic kept as baseline + `ViewportCoverage`. |
| `riftlens.visual.track` | Greedy 1:1 IoU/center tracker. False split > false merge. |
| `riftlens.visual.gst_align` | Read-only CHAMPION_KILL listing. Does not mutate GST. |
| `riftlens.visual.correlate` | UNKNOWN / LIKELY / CORRELATED. Capture ownership ignored. |
| `riftlens.visual.v1_analyze` | Orchestrates sample→detect→track→align→R.11. |
| `scripts/v1_finding_capture.py` | Explicit research capture + analysis. Env-gated. |
| H.6 / H.7 / H.8 / R.10.5 | untouched |

Import-linter: `visual spike isolation` still forbids analysis/coaching/pipeline/api/replay_host/gameplay and cloud SDKs.

`analyzer_id=riftlens.visual.v1.tracker` `analyzer_version=v1.0`. V.0 (`riftlens.visual.v0.healthbar`) remains callable.

No new production dependencies. No Torch/ONNX/OCR/cloud VLMs.

## Exact real finding used

Latest rebuilt Kaisa review, not the unrelated V.0 18:30 clip.

| Field | Value |
|---|---|
| Match | `NA1_5617764200` |
| Review | `01KZQ45RNRVBG5KYTF1WP2ZQEZ` |
| Finding | `01KZQ45QZ52C6CVMPHXZQ9VY24` |
| Rule | R-012 |
| Title | Fought into unaccounted-for enemies |
| Finding GAME t | **22:20.491** (`1340491` ms) |
| Finding t_end | 22:34.665 (`1354665` ms) — Kaisa's death |
| Subject | pid 9 Kaisa BOTTOM team 200 LOSS |
| Gameplay source | `01KZMXVW4153FVKNXYRJWFM6YV` |
| ClockMap | `01KZMY2BN0GGHK7T6BCGH8Q6XS` |

Planned capture (12 s before + 15 s after finding t, 27 s total):

| Bound | GAME | SOURCE (if same clock as V.0, +623 ms) |
|---|---|---|
| Start | 22:08.491 (`1328491`) | `1329114` once captured |
| End | 22:35.491 (`1355491`) | `1356114` once captured |

**No 22:20 MediaArtifact exists.** Existing captures are all 18:30–18:55. V.1 did **not** auto-capture. `scripts/v1_finding_capture.py` without `RIFTLENS_V1_T4=1` returns typed `CAPTURE_NOT_REQUESTED`.

A live R.10 capture attempt in this session (`RIFTLENS_R10_T4=1` still set in the shell) failed with `REPLAY_API_UNAVAILABLE`. League was not ready. V.1 therefore **does not invent** a 22:20 subject track.

## GST in the planned window (not visual truth)

Kills already in the local GST for 22:08–22:35:

| GAME | Killer | Victim | Subject role |
|---|---|---|---|
| 22:20.491 | 9 Kaisa | 5 Seraphine | **killer** (R-012 timestamp) |
| 22:24.699 | 4 Vayne | 10 Morgana | — |
| 22:25.768 | 7 Zac | 4 Vayne | **assist** |
| 22:32.527 | 3 Mel | 7 Zac | — |
| 22:34.665 | 3 Mel (+1 Quinn, +2 Lillia, +4 Vayne) | **9 Kaisa** | **victim** |

This GST sequence is compatible with “initial exchange succeeded, then more enemies participated, then Kaisa died.” It does **not** prove fog, unseen rotations, or a bad engage. V.1 must not relabel these as `Source.VISUAL`.

## Detector

V.0 HSV green/red health-bar geometry is kept as the candidate source.

V.1 additions:

- `ViewportCoverage`: `USEFUL` / `OBSTRUCTED` / `TRANSITION` / `UNKNOWN`
- HUD-strip static-bar suppression after tracking (glued pixels in y≤48 or x≤16)
- Noise gate still at >10 raw bars / frame
- Team estimate `ALLY` / `ENEMY` / `UNKNOWN` from bar color, confidence capped at 0.55
- Team color never implies participant or champion identity

## Tracker

Deterministic greedy 1:1 matching:

- Score = 0.55 IoU + 0.45 center proximity (72 px)
- Opposite team color penalized (avoid merge)
- Two similarly good matches → `AMBIGUOUS` and fragment (no identity swap)
- Miss grace = 2 frames (~500 ms at 4 fps)
- Long gap = 8 frames (~2 s) starts a new track
- `LEFT_VIEW` = ceased in the captured viewport, **not** died / recalled / fogged
- Track confidence may rise at most +0.06 per supporting detection; misses never raise it

Track ids are `trk_0001`… (deterministic). R.11 `entity_observation_id` remains a ULID.

## Sampling

**Chosen default: 4 fps** (250 ms).

| Rate | 27 s window | Why |
|---|---:|---|
| 2 fps | 55 | V.0 occupancy; too sparse for miss-grace tracking |
| **4 fps** | **109** | Lowest rate that gives a 2-frame grace of 500 ms |
| 5 fps | 136 | +25% detect cost; does not fix detector flicker |
| 30 fps | ~811 | Not justified; detect already dominates |

On the existing 25 s 18:30 clip (not the R-012 window):

| Metric | 4 fps V.1 |
|---|---|
| Decoded / analyzed | 101 / 101 |
| Extract (PyAV) | 9.2 s |
| Detect (OpenCV) | 14.0 s |
| Track | **37 ms** |
| GST align | 1 ms |
| Total | 23.3 s |
| CPU | local Windows, no GPU |

Tracking is cheap. Detection is the runtime. V.0 was ~6 s at 2 fps / 51 frames; V.1 at 4 fps is slower because it samples twice as often, not because the tracker is heavy.

## Subject correlation

| Signal | Used as identity? |
|---|---|
| Capture requested for Kaisa / pid 9 | **Never** |
| Team color alone | **Never** |
| Unique track disappearance within 2 s of GST subject death | Supports **LIKELY** (cap 0.55) |
| Death + subject-perspective team + `CONTROLLED_SUBJECT` camera | May reach **CORRELATED** (cap 0.75) |
| Multiple disappearing tracks / conflicts / weak evidence | **UNKNOWN** |

Real R.10 captures are `camera_controlled=false` → `UNCONTROLLED`. On the 18:30 clip, subject stayed **UNKNOWN** (correct: no GST death in that window, capture ownership ignored).

On the 22:20 window, GST **does** contain Kaisa's death at 22:34.665. Once a clip exists, death alignment can attempt LIKELY. It still cannot prove the track is Kaisa.

Inferred identity uses `VisualClaimKind.INFERRED` → `Source.VISUAL_INFERRED`, emitted as a separate `subject_track_correlation` frame, not mixed into pixel `OBSERVED` entities.

## R.11 mapping

Visual frames:

- `observation_type=champion_like_track`
- `claim_kind=OBSERVED` / `Source.VISUAL`
- entities: visibility + screen region; **no** pid / champion
- payload: `tracks[]` with `track_id`, lifecycle, team estimate, ambiguity
- camera: `UNCONTROLLED` unless capture says otherwise
- HUD / minimap: `UNKNOWN`

Inferred frames (only when correlation is LIKELY/CORRELATED):

- `observation_type=subject_track_correlation`
- `claim_kind=INFERRED` / `Source.VISUAL_INFERRED`

Sequence preserves match / source / capture / artifact / ClockMap / GAME / SOURCE / analyzer / schema `r11.1`.

## Camera coverage

R.10 `camera_controlled=false` → `CameraControl.UNCONTROLLED`.

Per frame: `USEFUL` / `OBSTRUCTED` / `TRANSITION` / `UNKNOWN` from viewport texture. Empty viewport ≠ player lacked vision. Off-camera ≠ fog.

## No fog-of-war claims

V.1 does not claim: enemy missing, fogged, player should have known, unseen rotation, blind engage. Minimap is not analyzed.

## 22:20 visual timeline

**Not produced from pixels** — no capture artifact for this window.

GST-only research timeline (aligned, not visual):

1. 22:20 Kaisa (with Zac + Morgana) kills Seraphine — R-012 fires here.
2. 22:24 Vayne (enemy ADC) kills Morgana.
3. 22:25 Zac (with Kaisa assist) kills Vayne.
4. 22:32 Mel (+ Quinn, Lillia, Vayne) kills Zac.
5. 22:34 Mel (+ Quinn, Lillia, Vayne) kills Kaisa.

What V.1 **would** look for in a future clip, without coaching labels:

- Did a likely-subject track remain visible from 22:20 through 22:34?
- Did additional champion-like tracks **enter the viewport** after 22:20?
- Did tracks leave the viewport before Kaisa's death?

That would help a future A vs B distinction. It still would not prove fog.

## R-012 diagnostic (research only)

Finding not mutated.

| Layer | Result |
|---|---|
| A. GST / R-012 | R-012 at 22:20 on a fight that includes a Kaisa kill and, 14 s later, Kaisa's death to Mel with three assists from other enemies. |
| B. Direct visual | **INSUFFICIENT_VISUAL_EVIDENCE** for the 22:20 window (no artifact). |
| C. VISUAL_INFERRED | None for 22:20 (no tracks). |
| D. UNKNOWN | Subject track, occupancy over time, camera usefulness, enemy identity, vision/fog, disengage window. |
| E. Wording nuance | GST **suggests** R-012's "fought into unaccounted-for enemies" at the **successful** first kill may lack the later-collapse nuance (Case B). Visual has not confirmed that. Do not rewrite R-012. |

On the unrelated 18:30 clip, V.1 diagnostic was `PARTIALLY_SUPPORTED` (tracks enter later) — same limitation as V.0: occupancy change ≠ fog.

## Case A vs Case B (not classified)

V.1 does not label A (bad engage into unaccounted enemies) vs B (reasonable first fight, later arrivals, failed disengage).

GST kill order is **necessary but not sufficient** for B. Still missing: minimap/vision, enemy identity, subject trajectory, disengage opportunity, fight phase, reinforcement timing.

## V.0 comparison

| | V.0 | V.1 |
|---|---|---|
| Finding selection | Unrelated 18:30 clip | Exact R-012 22:20 timestamp resolved |
| 22:20 capture | No | Planned + typed; artifact not yet recorded |
| Candidates | Per-frame bar counts | Same detector + kind CHAMPION_LIKE/NOISE/UNKNOWN |
| Temporal | Independent frames | Tracks with enter/leave/lost/ambiguous |
| Subject | UNKNOWN | UNKNOWN unless GST death uniquely aligns |
| GST | Unused | Read-only kill alignment |
| Provenance | VISUAL | VISUAL + optional VISUAL_INFERRED |
| 18:30 runtime | ~6 s @ 2 fps / 51 frames | 23 s @ 4 fps / 101 frames |
| Usefulness | Occupancy wiggle | Track lifecycle + GST join; still detector-limited |

V.1 is **meaningfully better as architecture** (correct window, tracks, GST join, honest UNKNOWN). On real League pixels the health-bar tracker **fragments heavily** (38 champion-like track ids on the 18:30 clip). That is not fake success: temporal state exists, but identity continuity is not yet trustworthy enough for coaching.

## Performance envelope

Practical for short research clips on this Windows PC. Not instant. Detector, not tracker, is the cost. Memory: one RGB frame at a time plus a handful of track records.

## Tests

`tests/unit/test_visual_v1.py`:

- Finding → GAME window, match-bound clipping, ClockMap/source preserved, no auto-capture, typed `CAPTURE_NOT_REQUESTED` / `CAPTURE_RECORDING_FAILED`, no hardcoded `.rofl` in `window.py`
- One moving candidate; two separate; same-team crossing fragments; opposite-team no swap; miss grace; long gap new id; static UI noise; empty; transition frames
- Confidence does not jump on a miss
- Team color synthetic green/red
- Correlation: ownership/team-only/weak → UNKNOWN; unique death → LIKELY; two deaths → UNKNOWN; strong synthetic → CORRELATED
- R.11 round-trip; VISUAL vs VISUAL_INFERRED; HUD UNKNOWN; coaching engine unchanged

V.0 tests still pass. R.11 observation tests pass.

## Full regression (this session)

`pytest` in `services/analysis`: **501 passed**, 6 skipped, **2 failed** (pre-existing / environmental; not modified):

1. `test_r10_real_25s_capture_and_cancel` — ran because `RIFTLENS_R10_T4=1` is set in the shell; `REPLAY_API_UNAVAILABLE`.
2. `test_engine_fixture_a_under_500ms` — engine 696 ms vs 500 ms budget. Timing flake; not touched.

- `ruff check` on V.1 files: pass  
- `mypy --strict riftlens/visual`: pass  
- `lint-imports`: 9 contracts kept  

## Recommendation for V.2 (do not implement)

Smallest sensible next step: **a better local champion-like detector**, not a cloud VLM and not minimap-first.

Evidence: tracker is 37 ms; 38 fragmented tracks come from flickering health bars. Until detections persist, subject correlation and A/B fight-phase work will stay UNKNOWN.

Possible V.2 slices, in order:

1. Local learned detector (or template/champion-bar model) with still-no-cloud constraint  
2. Champion identity on a detected box (only after 1)  
3. Subject trajectory + GST death join on the **actual** 22:20 clip once League can capture  
4. Minimap / vision — only after tracks are stable enough to be worth joining  

Do not start H.10 or R.12 from this spike.

## Limitations

- 22:20 clip not captured this session  
- Health-bar heuristic still false-positives and flicker-splits  
- No champion recognition  
- Team color is HUD-relative and unused for identity in uncontrolled replay  
- No HUD OCR (left UNKNOWN; not required)  
- No fog / minimap  
- LEFT_VIEW is not death  

## Files

Created: `riftlens/visual/{window,track,gst_align,correlate,v1_analyze}.py`, `scripts/v1_finding_capture.py`, `tests/unit/test_visual_v1.py`, this report.

Modified: `riftlens/visual/{detect,errors,report,__init__,__main__}.py`.

V.0 `analyze.py` unchanged.
