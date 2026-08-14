# V.5 — Subject trajectory / continuity cues (identity refinement)

**Status:** complete (local research spike + real Mac capture validation; not production)  
**Date:** 2026-08-14  
**Branch:** `integrate/ui-r1`  
**Does not change coaching, overlay, R/P rules, or H.6/H.8.** (R.10 Mac recording harden only as needed for capture.)

V.5 asks whether **trajectory / motion continuity around GST death** (plus one optional independent cue) can strengthen or honestly weaken an existing V.4/V.1 **LIKELY** subject track — without champion recognition, without forcing **CORRELATED**, and without mutating GST.

## Hypothesis

On free-spectator captures (`UNCONTROLLED` camera), death-time alignment already yields **LIKELY** (cap 0.55). Additional classical cues on the *same* track — pre-death continuity, death proximity, screen-space motion class, post-death absence, and calibrated team agreement — should:

1. **SUPPORT** a coherent LIKELY track (optional small bump still ≤ 0.55), or  
2. leave confidence **unchanged** when evidence is weak, or  
3. **fail closed to UNKNOWN** when continuity conflicts (jumps, competing disappearances, alive-after-death, team mismatch).

Trajectory alone must never invent CORRELATED under uncontrolled camera.

## Implementation

Additive modules on the existing V.4 path:

```
V.4 detect_v4 → V.1 track → V.4 calibrate → correlate_subject
                                              ↓
                                    V.5 continuity cues
                                              ↓
                                 refine_subject_correlation
                                              ↓
                                      R.11 cue frames
```

| Module | Role |
|---|---|
| `trajectory.py` | Screen-center steps → `MotionClass` (STATIONARY / SMOOTH_MOVING / JUMPY / CAMERA_LIKE / UNCERTAIN / SPARSE) |
| `continuity.py` | Pre-death, death proximity, motion, post-death, optional team cue |
| `correlate_v5.py` | Combine cues with base correlation; fail closed |
| `v5_analyze.py` | `analyze_*_v5` / `refine_v4_result` — no detector rewrite |

`analyzer_id=riftlens.visual.v5.trajectory` `analyzer_version=v5.0`.

## Cue definitions

| Cue | Provenance | SUPPORT when | CONFLICT when |
|---|---|---|---|
| `PRE_DEATH_CONTINUITY` | VISUAL_INFERRED | ≥2 obs in 3 s pre-death, longest gap ≤500 ms, span ≥500 ms | longest gap >2 s |
| `DEATH_TIME_PROXIMITY` | VISUAL_INFERRED | last seen within 2 s of GST death; unique disappearance | competing disappearances, or far from death |
| `MOTION_CONTINUITY` | geometry VISUAL; verdict INFERRED | STATIONARY or SMOOTH_MOVING | JUMPY |
| `POST_DEATH_ABSENCE` | VISUAL_INFERRED | disappears near death, no reappear | still observed >1.5 s after death |
| `TEAM_LABEL_AGREES` | VISUAL_INFERRED | calibrated track label == expected ALLY | ENEMY vs expected ALLY |

**Independence of team cue:** color→Riot-team calibration (hue clusters) vs temporal death alignment. Not two derivations of the same signal.

**Camera-like displacement** (large coherent screen steps) → **NEUTRAL** (not overinterpreted as subject locomotion).

## Confidence policy

| Rule | Behavior |
|---|---|
| Base UNKNOWN | Trajectory **cannot** invent LIKELY |
| Base LIKELY + ≥1 CONFLICT | → **UNKNOWN** (cleared) |
| Base LIKELY + ≥2 SUPPORT, no conflict | confidence `min(0.55, base + 0.05)` |
| Base LIKELY + 0–1 SUPPORT | confidence unchanged |
| Base CORRELATED | unchanged unless continuity CONFLICT → cleared |
| Uncontrolled camera | remains a hard CORRELATED block |
| Claim kind | always `VISUAL_INFERRED` for identity; geometry cue `OBSERVED` |

No silent promotion of inferred → fact. GST untouched.

## Synthetic tests

`tests/unit/test_visual_v5.py` covers: smooth into death, stationary, small/large gaps, impossible jump, competing tracks, disappear near death, alive after death, sparse motion, camera-like, team agree/conflict, LIKELY≠CORRELATED, conflict clears without identity swap, sparse no crash, UNKNOWN base stays UNKNOWN.

V.3 contract updated: V.3 deferred continuity; V.5 owns `continuity.py` (still no `v3_track` fork).

## Real validation A — Vladimir `NA1_5614479225`

### Frozen V.4 baseline (from V.4 report; live pixel re-run)

| Field | Value |
|---|---|
| Subject track | `trk_0003` |
| Status | **LIKELY** |
| Confidence | **0.55** |
| Death `t_ms` | **903411** |
| Track window (report) | ~15:01–15:03 (ends ~734 ms before death) |
| Team calibration | **WEAK** (subject RED→200 + blue prior) |
| Subject team label | ALLY after calibration |

**Live capture status on this Mac host:**  
`CAPTURE_UNAVAILABLE` — `~/.riftlens/captures/NA1_5614479225/01KZT2ZK13TPZP72070CEC9DEF` not present (Windows V.3 artifact). Live V.4/V.5 pixel re-run skipped.

### Expected V.5 behavior on that baseline (from cue rules + report timeline)

| Cue | Expected |
|---|---|
| Pre-death continuity | SUPPORT (short continuous `trk_0003` into death) |
| Death proximity | SUPPORT (unique disappearance ~734 ms before death) |
| Motion | SUPPORT or NEUTRAL (short track; not JUMPY in report) |
| Post-death absence | SUPPORT (`trk_0003` ends before death; later `trk_0004` is a *new* id) |
| Team label | SUPPORT (ALLY) if calibration applied |
| Status after V.5 | **LIKELY** (stronger or unchanged; still ≤0.55) |
| CORRELATED | **No** (UNCONTROLLED) |

Synthetic analogs of this profile pass in unit tests.

## Real macOS validation — `NA1_5620410094`

Fresh R.10 capture on this Mac (identity ClockMap from live playback length; full multi-seek calibrate avoided). Subject **Vladimir pid 6**, team 200. Replay `NA1-5620410094.rofl`.

### 1. Death timestamp selected

| | |
|---|---|
| GST subject deaths (pid 6) | `839881, 1062798, 1160030, 1371660, 1468841, 1585876, 1899186` |
| **Primary** | **`839881`** (13:59) — kill then death; 10 s before + 7 s after |
| Game interval | **`829881`–`846881`** |
| Alternate (2nd window) | `1062798` → `1052798`–`1069798` |

No coaching finding required.

### 2. Capture interval (primary)

| Field | Value |
|---|---|
| Capture id | `01KZZAGC6QZ8FWB61KQYDX4VVY` |
| Game interval | `829881`–`846881` (17 s) |
| Source interval | `829881`–`846881` (identity clock) |
| ClockMap | IDENTITY / GOOD / verified; offset 0; length_ms `2484308` |
| `camera_controlled` | **false** |
| Media | `~/.riftlens/captures/NA1_5620410094/01KZZAGC6QZ8FWB61KQYDX4VVY/clip_g829881.webm` (~3.1 MB; **not committed**) |
| Duration | 17 s requested; decode ~125 frames @ ~30 fps (file ends prematurely after encode finalize) |

**R.10 Mac capture bugs fixed during this validation (not V.5 cues):** seek-before-record; promote League’s `clip.webm.tmp` when GET `/replay/recording` stalls; retry timeout/`http_error`/`connect_failed` while tmp is stable; Mac transport read timeout 15 s.

### 3. V.4 baseline (primary)

| Field | Value |
|---|---|
| Status | **UNKNOWN** |
| Confidence | **0.0** |
| Track id | none |
| Tracks | 1× `CHAMPION_LIKE` (`trk_0001`), **1 obs**, duration 0 ms |
| Team calibration | WEAK spectator prior (RED→200 / BLUE→100); 0 anchors |
| Informative frames / detections | 17 / 1 |
| Death in window | `839881` |
| Reasons | death-time alignment insufficient; capture ownership ignored |

### 4–6. V.5 result + cues + confidence

| Field | Value |
|---|---|
| Status | **UNKNOWN** (unchanged) |
| Confidence before → after | **0.0 → 0.0** |
| Selected track | none |
| Identity change | **unchanged** |
| Cue bundle | none (`rejected_cues: no_base_likely_track`) |
| Supporting / conflicting cue counts | 0 / 0 |

Trajectory **did not** invent identity from UNKNOWN. No silent track swap.

**Frame note:** Directed Camera stayed on **fountain/base**, not the death fight (HUD ~13:49→13:52; subject dead on scoreboard while camera empty). Subject combat pixels were not available for continuity SUPPORT. Refs (local, optional): `artifacts/v5_mac_5620410094_frames/primary_839881/frame_0000.jpg`, `frame_0090.jpg`.

### Alternate window `1062798`

Capture `01KZZAK270FZT68YAKNH40QZVC` succeeded (~2.9 MB webm). V.4: **0** champion-like tracks, UNKNOWN; V.5 unchanged UNKNOWN. Same Directed Camera / non-subject framing issue. Stopped after two windows per scope.

### 7. Runtime (primary)

| Stage | ms |
|---|---|
| Extract | 280 |
| Detect | 346 |
| Track | 0.1 |
| Color sample | 9.2 |
| Calibrate | ~0 |
| **V.5 continuity / refine** | **≪1** (`continuity_ms ≈ 0.003`) |
| V.4 wall | ~0.64 s |

V.5 remains cheap vs detection.

### 8. Fail-closed observations (real pixels)

| Check | Result |
|---|---|
| Trajectory invents CORRELATED/LIKELY from UNKNOWN | **No** |
| Uncontrolled camera blocks unsupported CORRELATED | **Yes** (`camera_controlled=false`; status ≠ CORRELATED) |
| Capture ownership used as identity evidence | **No** (`capture_review_pid_ignored_for_identity`) |
| Silent subject track swap | **No** |
| Conflicting trajectory reduces/fails closed | Exercised in unit tests; this clip had no LIKELY base to conflict |

Evidence JSON: `services/analysis/artifacts/v5_mac_5620410094_validation.json`.

## Runtime

| Stage | Cost |
|---|---|
| V.5 continuity / refine | **≪1 ms** on track observations (synthetic + real) |
| Detector | unchanged (still dominates when clip present) |

V.5 does not re-run detect.

## Fail-closed examples (synthetic)

- Impossible screen jump → CONFLICT → LIKELY cleared  
- Two tracks disappearing at death → CONFLICT  
- Track still observed >1.5 s after GST death → CONFLICT  
- Team ENEMY vs expected ALLY → CONFLICT  
- UNKNOWN base + beautiful trajectory → still UNKNOWN  

## What remains UNKNOWN

- Pixel champion / participant identity  
- Fog, wards, minimap  
- Map-space trajectory  
- Camera ownership (`UNCONTROLLED`) / Directed Camera not locked to subject  
- Engage quality / Case A vs B coaching labels  
- Live LIKELY→stronger path on a subject-visible Mac death fight (this match’s Directed Camera missed combat)

## Research verdict

**PARTIALLY_SUPPORTED**

Cue model, confidence policy, fail-closed behavior, and isolation are implemented and unit-tested. Fresh Mac R.10 captures for `NA1_5620410094` (two death windows) confirm: V.5 stays UNKNOWN when V.4 has no LIKELY track; ownership is ignored; CORRELATED is not invented under uncontrolled camera. Continuity **SUPPORT** toward a stronger LIKELY was not observed because Directed Camera did not keep subject combat on screen.

## Recommendation for V.6 (do not implement)

1. Re-run V.4→V.5 on a death window where camera contains the subject for several seconds (or restored Vladimir LIKELY capture).  
2. Only then consider appearance/reassociation across miss-grace — still classical.  
3. Minimap/fog and champion identity remain later. Do not wire coaching.

## Files

- `riftlens/visual/trajectory.py`
- `riftlens/visual/continuity.py`
- `riftlens/visual/correlate_v5.py`
- `riftlens/visual/v5_analyze.py`
- `tests/unit/test_visual_v5.py`
- `scripts/v5_run_vladimir.py`
- `scripts/v5_mac_death_validation.py`
- `artifacts/v5_mac_5620410094_validation.json`
- R.10 Mac capture harden: `recording.py`, `artifact_store.py`, `mac/host.py`, `test_capture_r10.py`
- updates: `__init__.py`, `__main__.py`, `test_visual_v3.py`

Unchanged: detector/tracker cores, coaching, overlay, GST writers, H.6/H.8. V.5 cue algorithm unchanged.
