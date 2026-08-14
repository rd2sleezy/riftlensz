# V.6 pre-algorithm track-loss diagnostic

**Status:** complete (diagnostic only; no identity ranking; no production tracker/detector default changes)  
**Date:** 2026-08-14  
**Branch:** `integrate/ui-r1`  
**Spike:** `spikes/v6_track_loss_diagnostic/`  

## Capture-duration fix rerun (same diagnostic, new media)

**Capture:** `~/.riftlens/captures/NA1_5620410094/01M00NSCH421BEY2SP3PADQT8A`  
**Match / subject / death:** `NA1_5620410094` · Vladimir pid 6 · GST death `839881`  
**Framing:** production `path` + GST · `camera_controlled=true` · placement delta 0

After the R.10 Mac duration fix (`enforceFrameRate=false` so encode stays 1x):

| Field | Before (Case D clip) | After |
|---|---|---|
| Requested | 829881–846881 (17 s) | same |
| Decoded frames | 132 | **468** |
| Duration | ~4.366 s | **16.788 s** |
| Implied end | ~834247 | **846669** |
| `death_in_file` | false | **true** |
| Longest track | ~4266 ms | **16717 ms** (829917–846634) |
| End→death (tracks that end before death) | 5734 ms | **2724 ms** |
| Tracks continuing past death | n/a | trk_0002 / trk_0003 last_seen 846634 (**−6753 ms**) |
| Unique disappearance ±2000 ms | no | **no** (`disappearing_near_death=[]`) |
| V.4 / V.5 | UNKNOWN | **UNKNOWN** (no identity-rule changes) |
| Verdict | `TRACK_CONTINUITY_NOT_FIXABLE` Case D | **`TRACK_CONTINUITY_PARTIAL`** Case D (EOF vs identity disappearance) |

Death is now in the file. V.4 still does not reach LIKELY: no unique champion-like disappearance within `DEATH_ALIGN_MS`. Longest tracks continue **through** death rather than disappearing at it. Do not implement V.6 ranking from this rerun.

Original short-clip writeup retained below.

---

**Original capture:** `~/.riftlens/captures/NA1_5620410094/01KZZCQ1C9W831FNC40H2R8MS2`

## Original verdict (short clip)

### `TRACK_CONTINUITY_NOT_FIXABLE` (on the truncated capture)

**Primary case: D — capture/media ends before GST death.**

The framed R.10 clip does **not** contain the death window. Encoded media lasts **~4.366 s** (132 frames @ 30 fps) and ends at implied game time **~834247**, while death is at **839881** (**~5634 ms shortfall**). Requested interval was `829881–846881` (17 s).

Tracker miss-grace / association / 8 fps resampling **cannot** create observations past EOF. Widening `DEATH_ALIGN_MS` would be an identity-rule cheat and is rejected.

Within the available media, champion-like tracks **persist to the last sample**; they are not mid-stream association losses.

---

## 1. Exact track-loss cause

| Layer | Finding |
|---|---|
| Media | `clip_g829881.webm` decodes to **132 frames / 4.366 s**; `death_in_file=false` |
| Sampling | Last sample @ **834147** (= clip end under 4 fps grid) |
| Detections after loss | **0** (no frames exist) |
| Tracker | `trk_0003` / `trk_0004` last_seen **834147**, `closed_reason=LEFT_VIEW` because the clip ends |
| End→death gap | **5734 ms** (834147 → 839881) |

**Cause:** premature Mac encode finalize / short clip vs requested interval — **not** miss-grace, not IoU association, not sampling cadence alone.

Secondary notes on the **last available frames** (not the death moment):

- Fight still on-screen (Vladimir + Ezreal visible in annotated `f4_833647.jpg` / `f4_834147.jpg`).
- Detector boxes in those frames often sit on **turret chrome** while champions remain visible — possible false-positive / miss mix, but irrelevant until death is actually encoded.
- HUD may still label “Directed Camera” even when API framing was `path` (known non-authoritative HUD text).

---

## 2. Frame-by-frame timeline around loss (`832000–834147`)

Research sampling **4 fps**. Compact loss-band rows:

| game_t_ms | raw | confirmed | coverage | active tracks | center_sat |
|---|---:|---:|---|---|---:|
| 833647 | 2 | 2 | USEFUL | trk_0003, trk_0004 | ~115 |
| 833881 | 2 | 2 | USEFUL | trk_0003, trk_0004 | ~123 |
| 834147 | 2 | 2 | USEFUL | trk_0003, trk_0004 | ~112 |

Then: **EOF**. No samples in `834148–841000`. Death `839881` never appears.

Full focus timeline + boxes: `spikes/v6_track_loss_diagnostic/artifacts/track_loss_diagnostic.json` → `baseline_4fps.timeline_focus`.

Annotated JPEGs (local spike artifacts): `artifacts/frames/f4_*.jpg`.

---

## 3. Raw detection vs tracking

| Question | Answer |
|---|---|
| Do detections continue after track last_seen? | **No** — no frames after last_seen |
| Does temporal confirmation drop raw hits? | **No evidence** in the missing tail (raw=confirmed while media exists) |
| Is this Case A (tracker)? | **No** on this capture |
| Case B (detector)? | **Not primary** — cannot evaluate death-time detector without pixels |
| Case C (left FOV)? | **Not primary** — last frames still show fight; media ends first |
| Case D (capture/timestamp)? | **Yes — primary** |

---

## 4. Duplicate tracks `trk_0003` / `trk_0004`

Measured overlap **4266 ms** (entire long window).

| Metric | Value |
|---|---|
| mean IoU | **0.09** |
| mean center distance | **65.5 px** |
| `likely_same_region` | **false** |
| `likely_distinct_side_by_side` | **true** |

Interpretation: **two distinct champion-like regions** (side-by-side), not a split of one champion. Fragmentation is **not** what prevents death alignment here; **missing media** is.

Do not merge them from similarity alone.

---

## 5. Tracker parameter counterfactuals (offline, same detections)

Defaults: `MISS_GRACE_FRAMES=2`, `LONG_GAP_FRAMES=8`, `MATCH_CENTER_PX=72`, `MATCH_IOU=0.12`.

Tried (temporary only): miss_grace 4/6/8, long_gap 16/24, center 96–160 px, IoU 0.08–0.03.

| Result | Value |
|---|---|
| Best end→death gap | **still 5734 ms** |
| Any reach ±2000 ms of death | **false** |
| Unique death-aligned track | **false** |

Reason: last observation time is bounded by last detection/sample = **EOF**. Grace cannot extend past absent frames.

---

## 6. Sampling-rate comparison

| | 4 fps (default) | 8 fps |
|---|---|---|
| Samples | 18 | 35 |
| Last sample | 834147 | 834147 |
| Raw / confirmed dets | 42 / 42 | 84 / 84 |
| Longest duration | 4266 ms | 4266 ms |
| End→death gap | 5734 ms | 5734 ms |
| Detect ms | ~208 | ~397 |
| Death-aligned? | no | no |

Higher sampling densifies the **same** short media; it does not recover the missing ~12.6 s to requested end / death.

---

## 7. Detector observations (available media only)

- Coverage remains `USEFUL` through EOF.
- Confirmed detection count stays 2 on late frames (`trk_0003`/`trk_0004`).
- Annotated frames show champions visually present near EOF; some boxes latch onto **turret** UI — classical false-positive risk for later work, **not** the cause of the 5.7 s death gap.
- No justified detector patch in this diagnostic (death pixels absent).

---

## 8. Subject/fight on-screen?

**Yes, through the end of the file** (~13:53–13:54 HUD), including Vladimir-visible combat.  
**No frames exist at GST death** (`839881` / ~13:59).

---

## 9–10. End→death gaps

| Gap | ms |
|---|---:|
| Current (baseline) | **5734** |
| Best legitimate counterfactual | **5734** (unchanged) |
| Media shortfall to death | **5634** |

---

## 11. Runtime impact

| Stage | Cost |
|---|---|
| Extract 4 fps | ~280 ms |
| Detect 4 fps | ~208 ms |
| Track | ≪1 ms |
| Extract+detect 8 fps | ~detect ~397 ms |
| Counterfactuals | negligible on cached detections |

No production pipeline change.

---

## 12. Diagnostic verdict

**`TRACK_CONTINUITY_NOT_FIXABLE`** for death-aligned identity on this artifact, because the artifact does not contain death.

Classical detector/tracker **cannot** produce a unique track within ±2000 ms of `839881` without unsafe identity assumptions **on this file**.

Identity fail-closed behavior (V.4/V.5 UNKNOWN) remains correct given missing death pixels.

---

## 13. Smallest recommended next change

**Do not start V.6 identity ranking yet.**

1. **Fix / harden R.10 Mac encode so requested `[start,end)` is actually present in the webm** (premature finalize / tmp promote / duration shortfall). Re-validate with `death_in_file=true` and decoded duration ≈ 17 s for this window.  
2. Re-run **this diagnostic** on a full-length framed capture.  
3. Only then decide tracker vs detector continuity vs V.6 ranking.

Rejected now:

- widening `DEATH_ALIGN_MS` to ~6 s  
- longest-track / majority-team / camera-target-as-Vladimir identity  
- V.6 ranking on incomplete media  

---

## Files

- `docs/architecture/v6-track-loss-diagnostic-report.md` (this file)
- `spikes/v6_track_loss_diagnostic/run_diagnostic.py`
- `spikes/v6_track_loss_diagnostic/README.md`
- `spikes/v6_track_loss_diagnostic/artifacts/track_loss_diagnostic.json`
- optional local frames under `spikes/v6_track_loss_diagnostic/artifacts/frames/` (not required in git)

Unchanged: production tracker/detector defaults, identity rules, coaching, overlay, GST.
