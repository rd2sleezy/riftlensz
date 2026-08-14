# V.5 — Subject trajectory / continuity cues (identity refinement)

**Status:** complete (local research spike, not production)  
**Date:** 2026-08-14  
**Branch:** `integrate/ui-r1`  
**Does not change coaching, overlay, R.10 capture internals, R/P rules, or H.6/H.8.**

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

## Real validation B — `NA1_5620410094`

GST on this Mac: subject **Vladimir pid 6**, team 200, multiple deaths (e.g. 839881, 1062798, …). Replay `NA1-5620410094.rofl` present.

**However:** no production review/finding row currently centers a death window for V.5, and no R.10 capture artifact exists.

**`NA1_5620410094 not suitable for V.5 death-window validation`** (no selected death-centered finding + no capture). Do not force a test.

## Runtime

| Stage | Cost |
|---|---|
| V.5 continuity / refine | **≪1 ms** on track observations (synthetic; no decode) |
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
- Camera ownership (`UNCONTROLLED`)  
- Engage quality / Case A vs B coaching labels  
- Live Vladimir pixel confirmation on this host (capture missing)

## Research verdict

**PARTIALLY_SUPPORTED**

Cue model, confidence policy, fail-closed behavior, and isolation are implemented and unit-tested. The published Vladimir LIKELY profile is consistent with SUPPORT→LIKELY (not CORRELATED). Live pixel confirmation on `NA1_5614479225` was blocked by missing local capture media.

## Recommendation for V.6 (do not implement)

1. Re-run V.4→V.5 on the restored Vladimir capture (or a fresh Mac death-window capture with an explicit finding).  
2. Only then consider appearance/reassociation across miss-grace — still classical.  
3. Minimap/fog and champion identity remain later. Do not wire coaching.

## Files

- `riftlens/visual/trajectory.py`
- `riftlens/visual/continuity.py`
- `riftlens/visual/correlate_v5.py`
- `riftlens/visual/v5_analyze.py`
- `tests/unit/test_visual_v5.py`
- `scripts/v5_run_vladimir.py`
- updates: `__init__.py`, `__main__.py`, `test_visual_v3.py`

Unchanged: detector/tracker cores, coaching, overlay, GST writers, H.6/H.8.
