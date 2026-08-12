# V.4 — Spectator Team-Color Calibration

**Status:** complete (local research spike, not production)  
**Date:** 2026-08-12  
**Branch:** `r1-gameplay-source-domain`  
**Does not change coaching, overlay, R.10 capture internals, R/P rules, or H.6/H.8.**

V.4 fixes unreliable ALLY/ENEMY classification in free-spectator / replay rendering by replacing live-play green=ally / red=enemy assumptions with calibrated, subject-relative team labels.

## Real fixture (research only — not hardcoded into production)

| Field | Value |
|---|---|
| Match | `NA1_5614479225` |
| Subject | Vladimir pid **6**, team **200**, TOP, WIN 14/2/12 |
| Finding | R-003 @ `903411` (15:03.411) |
| Capture | `01KZT2ZK13TPZP72070CEC9DEF` |
| Artifact | `01KZT30ZS5AX3K261QZDRXQY7K` |
| Source | `01KZT26PMDZ984ZYEEM172KCVB` |
| ClockMap | `01KZT2ZK0QNDCKWKV4EATV7PVM` |
| GAME | `891411–918411` |

## Observed spectator color behavior

Sampled frames from the real clip show **team-absolute** free-spectator health bars, not live-play relative coloring:

| Visual cluster | Typical OpenCV HSV hue | Riot team (this match) | Relative to Vladimir (200) |
|---|---|---|---|
| Red / magenta bar fill | ~0–10 / 170–180 | team **200** | **ALLY** |
| Blue / cyan bar fill | ~95–125 | team **100** | **ENEMY** |
| Green (play-perspective ally) | ~40–85 | rare / not used here | unmapped → **UNKNOWN** |

Also observed:

- Selected/outline bright edges exist; sampling shrinks 1px inward and requires sat/val ≥ 80.
- Narrow HUD chrome (~34px) continues to be rejected by V.2 champion-bar geometry.
- Neutral / non-champion candidates are not forced into ALLY/ENEMY (`CandidateKind.NOISE` skipped; unusable color → UNKNOWN).

## Old classification root cause

V.0 / V.1 / V.2 treated **green = ALLY**, **red = ENEMY** (live client perspective).

In free spectator, Vladimir’s team-200 bars are **red**, so every credible track was labeled **ENEMY**. Blue team-100 bars were largely never proposed (V.0 only green/red masks). Result on this clip: **8/8 ENEMY**.

## Calibration design

1. Detect with V.2 geometry + optional strict blue-bar proposals (`detect_v4`).
2. Track with unchanged V.1 tracker.
3. Sample bar HSV (median hue/sat/val over saturated interior pixels).
4. Build `TeamCalibration`: color cluster → Riot team (`TEAM_100` / `TEAM_200`).
5. Label tracks as **ALLY / ENEMY / UNKNOWN** relative to subject Riot team from MATCH/GST.
6. Emit track presence as `Source.VISUAL`; team labels as `Source.VISUAL_INFERRED`.

Calibration confidence:

| Level | Meaning |
|---|---|
| `UNAVAILABLE` | No subject team, or conflicting anchors |
| `WEAK` | Spectator prior only, or single ≤0.55 LIKELY anchor |
| `GOOD` | ≥2 agreeing anchors / two color clusters |
| `VERIFIED` | ≥2 strong (≥0.7) anchors on distinct colors |

Single LIKELY subject anchor **cannot** produce `VERIFIED`. Downstream track team confidence under `WEAK` is capped at ≤0.55.

## Anchors used on Vladimir clip

| Anchor | Color | Riot team | Notes |
|---|---|---|---|
| Subject LIKELY `trk_0003` | RED_LIKE | 200 | GST death alignment; conf ≤0.55 |
| Spectator prior (fill) | BLUE_LIKE → 100 | when only one cluster anchored |

Extra GST death anchors require ≥2 observations and a unique pre-death disappearance; one-frame post-death flashes are ignored (`disappearing_near` requires `first_seen ≤ death_t`).

## Real Vladimir V.4 result

| Metric | V.3 / V.2 baseline | V.4 |
|---|---:|---:|
| Frames @ 4 fps | 109 | 109 |
| Tracks | 8 | 13 |
| ALLY | 0 | **7** |
| ENEMY | **8** | **5** |
| UNKNOWN | 0 | **1** |
| Subject correlation | LIKELY `trk_0003` 0.55 | LIKELY `trk_0003` 0.55 |
| Calibration | n/a (wrong prior) | **WEAK** (1 subject RED→200 anchor + blue prior) |
| Subject track team conf | ENEMY (wrong) | ALLY ≤0.55 |
| Total analyze | ~41 s (earlier machine) / ~16 s here | ~17–28 s |

“All tracks ENEMY” is resolved. Subject stays **LIKELY** (uncontrolled camera; no CORRELATED upgrade from team alone).

### Timeline (supported only)

| GAME | Observation |
|---|---|
| 14:51 | `trk_0001`/`trk_0002` ALLY (red), one-frame |
| 15:01–15:02 | `trk_0003` ALLY, likely subject; ends ~734 ms before GST death |
| 15:03.411 | **GST:** Zaahen kills Vladimir |
| 15:04+ | `trk_0004` ALLY long track; blue ENEMY flashes `trk_0005`/`trk_0006` |
| 15:08+ | Mix of ALLY/ENEMY/UNKNOWN shorter tracks; `trk_0013` ENEMY persists |

### Performance (this run)

| Stage | ms |
|---|---:|
| Extract | 4382 |
| Detect | 12961 |
| Track | 3 |
| Color sample | 52 |
| Calibrate | 1 |
| Align | 1 |
| Total | 17414 |

V.4 overhead (color + calibrate) ≈ **53 ms** — small vs detect.

## R.11 provenance

- Pixel / track presence → `VisualClaimKind.OBSERVED` → `Source.VISUAL`
- Calibrated team labels → `observation_type=track_team_label` → `Source.VISUAL_INFERRED`
- Subject correlation → `Source.VISUAL_INFERRED` (unchanged)
- GST not mutated; Riot team IDs never overwritten by color

## Failure modes / limitations

- Blue proposals still add some one-frame tracks vs pure V.2 (13 vs 8).
- Colorblind modes / shield overlays not exhaustively tested; approach avoids single RGB constants.
- GREEN_LIKE remains unmapped in spectator prior → UNKNOWN.
- Team labels remain WEAK without multi-anchor verification.
- No champion identity; no minimap/fog.

## V.5 recommendation

Smallest evidence-driven next step: **subject identity / trajectory cues on the LIKELY track** (motion continuity around GST death, optional second independent cue) — not minimap, and not coaching.

Color calibration is now usable at WEAK/GOOD; identity is the remaining bottleneck for CORRELATED.

## Files

- `riftlens/visual/color_sample.py`
- `riftlens/visual/team_calibrate.py`
- `riftlens/visual/detect_v4.py`
- `riftlens/visual/v4_analyze.py`
- `riftlens/visual/gst_align.py` (post-death flash filter)
- `tests/unit/test_visual_v4.py`
- `scripts/v4_run_vladimir.py`
