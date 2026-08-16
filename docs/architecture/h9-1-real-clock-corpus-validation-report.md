# H.9.1 — Real League Clock OCR Corpus Validation

**Date:** 2026-08-14  
**Branch:** `integrate/ui-r1`  
**Corpus status (2026-08-16):** still **PARTIAL** — see [`h9-1-h10-real-vod-validation-report.md`](./h9-1-h10-real-vod-validation-report.md). No new REAL matches/resolutions/phases were found locally.

Companion to [`h9-1-clock-ocr-layout-report.md`](./h9-1-clock-ocr-layout-report.md).

---

## 1. Corpus collection method

**Inventory (this Mac):**

| Asset | Usable? |
|---|---|
| `~/Documents/League of Legends/Replays/NA1-5620410094.rofl` | Present (~19 MB). `MacReplayHost.open_session` failed: *Replay is unpaused but game time is not advancing* — no fresh early/late/loading screenshots from live replay. |
| `~/.riftlens/captures/NA1_5620410094/*.webm` | Yes — R.10 research clips @ **1520×982**, game starts ~13:49 and ~17:32 (clock-verified captures). |
| `artifacts/v5_mac_5620410094_frames/*.jpg` | Yes — same match; used sparingly (pad timing vs folder name). |
| Full VOD / 720p / 1080p / 1440p native | **Not found** locally. |

**Labelling:**

1. Decode R.10 WebMs at ~1 Hz; crop top-center HUD clock ROI (below kill score).
2. **Ground truth = manual visual reading** of the crop (enlarged contact sheet), cross-checked against capture `requested_start_game_ms + t_video_ms`.
3. Observed systematic **+1 s** HUD vs floored API approx on the ~13–14 min attach clips; **17:xx** clips matched. Visual text wins.
4. **H.9.1 OCR was never used as a label.**
5. Negatives: real kill-score / gold / minimap / portrait / scoreboard-without-clock crops from the same frames.
6. Synthetic Hershey / uniform frames kept under `synthetic/` and **excluded** from real acceptance.

Committed assets: small PNGs + `manifest.json` only (no `.rofl` / `.webm`).

## 2. Number of REAL samples

| Bucket | Count |
|---|---|
| REAL clean in-game clock crops | **41** |
| REAL non-clock negatives | **5** |
| **REAL total** | **46** |

## 3. Number of SYNTHETIC samples

**3** (malformed Hershey `9:99`, uniform dark, uniform bright) — labelled `SYNTHETIC`; **do not count** toward acceptance.

## 4. Source matches / videos

- Match: **NA1_5620410094**
- Media: R.10 clips under `~/.riftlens/captures/NA1_5620410094/` (attach, camspike, plain CLIP) + 2 v5 validation JPGs
- Times covered (visual): **13:49–14:06** and **17:32–17:36**

## 5. Resolutions actually represented

**Only 1520×982** (windowed Mac replay capture).  
720p / 1080p / 1440p native League clients: **not validated** (do not pretend otherwise).

## 6. HUD scales actually represented

**Unknown / single observed layout.** Capture manifests do not record client UI scale. Rough layout `ui_scale≈1.35` was seen in earlier H.9.1 smoke — not a multi-scale corpus.

## 7. Atlas changes

Added `riftlens/resources/vision/glyphs/league/24px/`:

- **LEAGUE_CROP** templates `0–9` + `colon.png`
- Median of up to 8 manually labelled crops per glyph across multiple timestamps
- Single height **24px** (native glyphs ~10px; upscaled for matching)
- `SOURCE.txt` documents origin; synthetic `{16,20,24,32}px/` **unchanged** for unit tests
- `choose_atlas()` prefers `league/` when complete

OCR segmentation updated for real HUD: bright-peak mask + projection runs + height-aware colon merge + outlier chrome drop + multi-threshold search requiring a colon.

## 8. Confidence-threshold changes

- **`GLYPH_MATCH_FLOOR` remains 0.72** (per-glyph). Not lowered to inflate accuracy.
- **`read_clock`**: no longer re-applies the same floor to *combined* confidence after every glyph already passed (combine can land below 0.72 on correct reads). Documented in code.
- Clock-like reads must contain `:`; colon-less digit strings abstain.

## 9. Clean real in-game results

From `python -m riftlens.vision.ocr.validate_corpus`:

| Metric | Value |
|---|---|
| Total | 41 |
| Correct | **39** |
| Wrong | **0** |
| Abstained | **2** (`clean_009` 13:53, `clean_011` 13:54 — segmentation) |
| Accuracy | **95.1%** |
| Coverage (non-abstain) | **95.1%** |

Target ≥99%: **not met** on this corpus.

## 10. Real non-game / non-clock results

| Metric | Value |
|---|---|
| Total REAL non-clock crops | 5 |
| Correctly rejected / low-conf | **5** |
| Confidently wrong | **0** |
| Rejection rate | **100%** |

Target ≥95% rejection: **met** on this small negative set.  
**Caveat:** these are non-clock HUD crops from in-game frames — **not** loading / menu / post-game screens (unavailable after replay open failure).

## 11. Confidently-wrong examples

**None** on REAL samples (0 wrong with a colon-bearing parse).

## 12. Abstention examples

- `clean_009` expected `13:53` → empty (`glyph_below_floor`) — connected colon/digit runs under several thresholds
- `clean_011` expected `13:54` → empty after rejecting colon-less `1354` candidate

## 13. Failure modes

- Adjacent glyph merging / split at some thresholds
- Left HUD chrome flecks (mitigated by cluster filter)
- Atlas/templates from **same match** as eval (honest optimism risk)
- No early-game (`m:ss` single-digit minutes), late-game, loading, post-game, occlusion-by-UI diversity
- Full-frame layout+OCR path on VODs still depends on clock ROI quality

## 14. Performance

Corpus OCR (46 REAL crops) finishes in well under 1 s wall time on this Mac (template match only; no video decode in harness). Video 1 Hz path unchanged from engineering report.

## 15. Corpus limitations

- N≪ original ~150-image aspirational gate
- Single resolution / single match / mid-game only
- Replay launch for broader times blocked
- R.10 clips ≠ full VOD diversity
- Negatives ≠ true non-game screens

## 16. Final `REAL_CORPUS_ACCEPTANCE` verdict

**REAL_CORPUS_ACCEPTANCE = PARTIAL**

Reasons:

- Real League glyphs + labelled crops exist; OCR reads **95.1%** clean with **0** wrong
- Non-clock rejection **100%** on available negatives
- Misses ≥99% clean accuracy and lacks resolution / phase / true non-game breadth for **PASS**
- Not `BLOCKED_INSUFFICIENT_CORPUS` (a real labelled set now exists), not `FAIL` (no confident wrongs; metrics useful)

## 17. Whether H.10 real auto-sync is now honestly unblocked

| Question | Answer |
|---|---|
| H.10 **engineering** (fit SyncMap from `ClockReading[]`) | Still unblocked (unchanged) |
| H.10 **real auto-sync** on arbitrary League VODs | **Partial / not yet** — OCR works on this match’s mid-game 1520×982 crops, but corpus/resolution/phase coverage is too thin to claim production-ready auto-sync |

Stop here. Do not start H.10 without an explicit work order.
