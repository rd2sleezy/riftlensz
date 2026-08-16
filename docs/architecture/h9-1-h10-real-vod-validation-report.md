# H.9.1 / H.10 — Real VIDEO corpus + validation

**Date:** 2026-08-16  
**Branch:** `integrate/ui-r1`  
**Does not implement:** H.12, H.12a/b/c, R.12, V.7, baseline-corpus harvesting, new coaching rules, cloud/neural OCR, UI redesign.

Companion to [`h9-1-real-clock-corpus-validation-report.md`](./h9-1-real-clock-corpus-validation-report.md) and [`h10-automatic-video-sync-report.md`](./h10-automatic-video-sync-report.md).

This work order built a reproducible real-VOD validation workflow and evaluated every locally available League recording. It did **not** invent or download footage.

---

## 1. Local media inventory

Searched (typical user-media locations, not Application bundles):

`~/Movies`, `~/Videos`, `~/Documents`, `~/Desktop`, `~/Downloads`, `~/.riftlens`, `~/Documents/League of Legends`.

Also checked OBS/ShadowPlay/NVIDIA default folders (absent) and the repo (no committed VODs).

**League-looking VIDEO:** none (0 files classified `REAL`).

**Present locally:**

| Asset | Count | Notes |
|---|---|---|
| Native `.rofl` | 1 | `~/Documents/League of Legends/Replays/NA1-5620410094.rofl` (~18 MB). Match duration **2478 s (~41 min)**, queue 420. |
| R.10 capture WebMs | 8 | `~/.riftlens/captures/NA1_5620410094/**/*.webm`. Two time windows (~13:49 and ~17:32). Longest clip **16.992 s @ 1520×982 vp9 30 fps**. |
| Riot MATCH/timeline cache | 1 match | `NA1_5620410094` only. |
| H.9.1 labelled clock crops | 46 REAL + 3 SYNTHETIC | Committed PNGs; same match, 1520×982, mid-game. |
| Downloads / iCloud videos | several | Stock/boxing/phone clips. **Not League.** Left unused. |

Downloads numbered `*-hd_*.mp4` files and CapCut/iMovie bundled clips were **not** treated as League gameplay.

## 2. Number of REAL VODs found

**0** REAL user gameplay recordings (OBS / ShadowPlay / full or partial player-POV VIDEO).

## 3. Number actually usable for H.10 / H.12 real-VOD acceptance

**0.**

R.10 clips are catalogued as `R10-CLIP` and were run through production H.10 as **experimental** material only. They do not count.

## 4. Recording types

| Kind | Locally available? |
|---|---|
| OBS full-game | no |
| ShadowPlay | no |
| Other player-POV VIDEO | no |
| R.10 CLIP (MacReplayHost) | yes — 8 files, 1 match |
| Native ROFL | yes — 1 file |
| Replay-generated VIDEO | no |
| Synthetic | clock-crop fixtures only |

## 5. Resolutions

| Source | Resolution |
|---|---|
| R.10 clips / H.9.1 crops | **1520×982** only (windowed capture) |
| Native 1080p | not found |
| Native 1440p | not found |
| Native 720p | not found |

## 6. Game phases represented

On REAL clock crops and R.10 clips, HUD times are **13:49–14:06** and **17:32–17:36** of a ~41-minute match.

| Phase | Present? |
|---|---|
| Early (`m:ss` before 10:00) | **no** |
| Mid (10:00–25:00) | yes |
| Late (≥25:00) | **no** |
| Recording starts mid-game | yes (all R.10 clips) |
| Pause / resume | **no** |
| Loading / menu / post-game | **no** (negatives are other HUD elements from in-game frames) |

## 7. Corpus manifest design

Committed catalog: `services/analysis/tests/fixtures/vision/vod_corpus/manifest.yaml`.

- Portable refs only: `r10://{match}/{capture}/{file}` and `vod://{relative}`.
- Optional uncommitted overlay: `~/.riftlens/vod_corpus/local.yaml` (absolute paths allowed there only).
- Kinds: `REAL` / `SYNTHETIC` / `REPLAY-GENERATED` / `R10-CLIP`.
- `counts_toward_h10_acceptance` is **computed** from kind (`REAL` only), not a writable flag.
- Media stays uncommitted (`vod_corpus/media/` gitignored; `*.rofl` gitignored).
- Checkpoint files are small YAML next to the catalog.

CLI: `python -m riftlens.cli vod-corpus {inventory,validate-manifest,extract-checkpoints,eval-ocr,eval-h10,summary}`.

## 8. Independent checkpoint methodology

Labels are `video_t_ms → visible HUD clock / game_t_ms`.

- Ground truth is **manual visual reading** of a top-center HUD strip / known clock ROI.
- H.10 SyncMap output is rejected as a label source (`label_basis` must not be `h10_syncmap` / `h10_predicted` / `auto_sync`).
- Replay API / R.10 `requested_start_game_ms` is **not** used as VIDEO OCR truth.
- Tooling: `vod-corpus extract-checkpoints` writes a detected-ROI crop **and** a wider strip (layout often latches onto the kill score).

For the two catalogued R.10 clips, visual labels (known clock ROI x=706, y=54):

| Clip | video_t_ms | visible clock |
|---|---|---|
| mid 17s | 0 / 4981 / 9983 / 15017 | 13:50 / 13:55 / 14:00 / 14:05 |
| late clip | 0 / 2000 / 4000 | 17:32 / 17:34 / 17:36 |

Small PNGs: `tests/fixtures/vision/vod_corpus/checkpoints/crops/`.

## 9. Atlas training / evaluation separation

League glyph atlas `resources/vision/glyphs/league/24px` was built from **NA1_5620410094** R.10 crops.

Policy (enforced in `atlas_role_for_sample`):

- Crops from atlas-train match IDs → `atlas_match` (same-match / template family).
- Crops from any other match → `held_out`.
- SYNTHETIC never enters REAL acceptance.

**Held-out REAL samples available this run: 0.**  
Atlas-match accuracy is reported separately and is **not** claimed as held-out generalization.

No atlas templates were changed (no new matches to train from; no evidence that glyphs are the blocker vs layout).

## 10. Total REAL clock samples

| Bucket | N |
|---|---|
| REAL clean in-game crops | 41 |
| REAL non-clock negatives | 5 |
| REAL total | 46 |
| SYNTHETIC (excluded) | 3 |
| Held-out REAL | **0** |
| New early/late/1080p/1440p crops | **0** (no source media) |

Expansion beyond the existing mid-game single-match set was **not possible** without additional recordings. Thresholds were not lowered.

## 11. OCR correct / abstain / wrong counts

**Atlas-match REAL clean (NA1_5620410094, 1520×982, mid-game):**

| Status | Count |
|---|---|
| correct | 39 |
| abstained | 2 |
| wrong | 0 |
| confidently wrong | **0** |

**Atlas-match REAL negatives:**

| Status | Count |
|---|---|
| rejected | 5 |
| confidently wrong | **0** |

**Held-out REAL:** no samples.

**SYNTHETIC:** excluded from acceptance (unchanged fixtures).

## 12. Held-out OCR accuracy

**Not measurable.** N=0 held-out crops.

Atlas-match accuracy on the existing 41 clean crops: **39/41 = 95.1%** (2 abstentions, 0 wrong). This is **not** held-out accuracy.

## 13. Negative rejection performance

5/5 REAL non-clock crops rejected (rejection rate **1.0**). Confidently wrong: **0**.

No loading / menu / post-game / obscured-HUD negatives exist locally beyond the five in-game HUD-element crops.

## 14. Per-VOD H.10 result

Production path used: `collect_clock_readings` → `AutoSyncService.run(..., persist=False, force=True)` → constrained RANSAC fitter. No spike-only fitter.

**REAL VODs:** none to run.

**Experimental R10-CLIP (does not count toward acceptance):**

| corpus id | OCR attempted | readable | abstain | filter accepted | sync | code | failure_class |
|---|---|---|---|---|---|---|---|
| `r10_na1_5620410094_mid_17s` | 17 | 0 | 17 | 0 | fail | `INSUFFICIENT_READINGS` | `ocr_insufficient` |
| `r10_na1_5620410094_late_clip` | 5 | 0 | 5 | 0 | fail | `INSUFFICIENT_READINGS` | `ocr_insufficient` |

Root cause (manual inspection, not used as GT): `detect_layout` on these 1520×982 frames places `clock_rect` on the **kill score** (y≈5) instead of the game clock (y≈54). Production OCR therefore never sees the clock and **abstains**. That is preferable to a confident wrong SyncMap.

Native ROFL ClockMap was **not** counted as VIDEO SyncMap acceptance.

## 15. Per-VOD p50 / p95 / max sync error

Independent checkpoint errors vs a fitted SyncMap: **not applicable** (no successful VIDEO SyncMap; checkpoints uncovered).

R10-CLIP residual stats: none (fit never produced a map).

## 16. Aggregate success rate

REAL auto-sync: **0/0**.

Acceptance target ≥9/10 cannot be scored. Engineering target ≥5/5 cannot be scored.

Experimental R10-CLIP auto-sync: **0/2** (abstained).

## 17. Aggregate p95

REAL independent-checkpoint p95: **n/a**.

## 18. Verification results

No REAL SyncMap to verify. R10-CLIP runs never reached verification.

## 19. Failure classifications

| Recording | Auto class | Investigated cause |
|---|---|---|
| R10 mid 17s | `ocr_insufficient` | ROI/layout failure (kill-score latch); OCR abstained rather than inventing a clock |
| R10 late clip | `ocr_insufficient` | same |
| REAL VODs | — | none present |

No confidently wrong mappings were produced.

Pause / cut / multi-game / HUD-scale / 1080p/1440p classes were **not exercised** (no such recordings).

## 20. 30-minute runtime result

**BLOCKED.** No REAL VOD of approximately 30 minutes exists.

The cached match `NA1_5620410094` is ~41 minutes long, but the only VIDEO is 17-second R.10 CLIPs. Those clips were **not** used as evidence for the &lt;90 s / 30-minute gate.

Harness exists (`riftlens.validation.vod_corpus.bench`) and will time OCR + H.10 + optional deterministic analysis, excluding LLM, when a suitable REAL file is added.

Machine that would run it: **Apple M4, 10-core** (`darwin`).

## 21. H9_1_REAL_CORPUS verdict

**PARTIAL**

Real labelled crops exist (41 clean + 5 negatives), zero confident wrongs, 95.1% atlas-match accuracy, 100% negative rejection. Missing: held-out matches, early/late phases, native 1080p/1440p, HUD-scale diversity.

## 22. H10_REAL_VOD_ACCEPTANCE verdict

**BLOCKED_INSUFFICIENT_CORPUS**

Need ≥10 REAL recordings (engineering bar ≥5) with unaided auto-sync and independent checkpoint p95 ≤ 500 ms. Local N_REAL = 0.

Earlier H.10 engineering real-VOD target (≥5 diverse, all verified, p95 ≤ 500 ms): **not met** (still no REAL VODs).

## 23. Whether H.12 #1 is now runnable

**No.** Criterion 1 needs real VIDEO analysis on a real corpus. Zero REAL VODs.

## 24. Whether H.12 #5 is now runnable / passed

**Not runnable.** Need ≥10 REAL recordings and ≥9/10 unaided auto-sync. N=0.

## 25. Whether H.12 #6 is now runnable / passed

**Not runnable.** Need a ~30-minute REAL VOD and &lt;90 s excluding LLM. No such file.

## 26. Exact remaining assets needed

User-supplied or newly recorded **REAL League gameplay VIDEO** (OBS / ShadowPlay / equivalent player-POV). Do not substitute ROFL, R.10 clips, or replay-generated captures.

Minimum to unblock honest H.10 acceptance and H.12 VIDEO gates:

1. **≥10 paired REAL recordings** with `match_id` + Riot MATCH/timeline (or already-cached).
2. Independent checkpoint labels on each (early / mid / late / around cuts and pauses where they occur).
3. Preferred diversity, only if actually recorded: multiple matches, multiple durations, early + mid + late, at least one mid-game start, pause/resume if it happens, OBS and ShadowPlay if both exist, 1080p and 1440p if both exist, different HUD scales if they exist.
4. **Held-out clock crops from matches that are not `NA1_5620410094`** (atlas-train match), including early `m:ss` and late-game, plus genuine loading/menu/scoreboard/post-game negatives.
5. **One ~30-minute REAL VOD** for the H.12 performance gate (the 41-minute `NA1_5620410094` game would suffice **if** a full recording of it exists).

Easiest legitimate next step: record or locate existing OBS/ShadowPlay files of games already played; pairing with match IDs does not require playing ten new games today if the VODs already exist on another disk.

Drop files under `$RIFTLENS_VOD_ROOT` (default `~/.riftlens/vods`) and add entries to `~/.riftlens/vod_corpus/local.yaml`, then:

```text
python -m riftlens.cli vod-corpus extract-checkpoints vod://your.mp4 --id obs_01 --times 0,300000,900000,1500000
# fill visible_clock in the stub YAML
python -m riftlens.cli vod-corpus summary
```

---

## Tooling / tests added

| Path | Role |
|---|---|
| `riftlens/validation/vod_corpus/` | inventory, manifest, checkpoints, OCR split, H.10 batch, 30-min bench, verdicts, CLI |
| `tests/fixtures/vision/vod_corpus/` | portable catalog, independent labels, small crops, local eval JSON |
| `tests/unit/test_vod_corpus_validation.py` | deterministic tooling tests |
| `pipeline/ingest_video/reader.py` | public `decode_at` for labelling |

Production OCR confidence floors and H.10 RANSAC thresholds were **not** changed.

## Verdicts (do not collapse)

| Gate | Verdict |
|---|---|
| **H9_1_REAL_CORPUS** | **PARTIAL** |
| **H10_REAL_VOD_ACCEPTANCE** | **BLOCKED_INSUFFICIENT_CORPUS** |
| **H12_VIDEO_READINESS** | **BLOCKED** |

Stop. Do not start H.12, R.12, V.7, or baseline harvesting until REAL VODs exist.
