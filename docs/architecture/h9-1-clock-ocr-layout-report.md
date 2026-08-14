# H.9.1 — Clock OCR & Layout Calibration

**Status:** engineering complete; real corpus acceptance blocked  
**Date:** 2026-08-14  
**Branch:** `integrate/ui-r1`  
**Does not implement:** H.10 RANSAC / `/sync/auto`, H.11, R.12, V.7, neural OCR, ROFL OCR dependency, overlay, ReplayHost, coaching.

H.9.1 is the missing remainder of the original Phase 1 H.9 work order: a deterministic **VIDEO-only** clock-reading pipeline that later feeds H.10 SyncMap fitting. Shipped “H.9” earlier was desktop + manual sync; this work order adds PTS sampling, layout calibration, classical glyph OCR, and `ClockReading` production.

---

## 1. Architecture implemented

```
VideoGameplaySource (path)
        ↓
iter_samples(path, hz≈1)   # PTS-based sparse decode
        ↓
detect_layout / calibrate_layout
        ↓
is_in_game(frame, layout)
        ↓
read_clock → Estimate[int]
        ↓
ClockReading(t_video_ms, t_game_ms|None, confidence)
```

ROFL / ReplayHost clocks are untouched. `riftlens.vision` is isolated from coaching, analysis API, gameplay, visual V.*, and ROFL via import-linter (`h9.1 vision isolation`). Domain types stay pure (`ClockReading`, `LayoutProfile` ↔ existing `LayoutProfileRecord` shell).

## 2. Files added/changed

**Added**

| Path | Role |
|---|---|
| `riftlens/domain/clock_reading.py` | `ClockReading` |
| `riftlens/domain/layout_profile.py` | Runtime `LayoutProfile` / `PixelRect` |
| `riftlens/pipeline/ingest_video/reader.py` | PTS `iter_samples` |
| `riftlens/vision/**` | layout, OCR, detectors, pipeline |
| `riftlens/resources/vision/glyphs/{16,20,24,32}px/` | SYNTHETIC Hershey atlas |
| `tests/unit/test_video_reader.py` | PTS reader tests |
| `tests/unit/test_clock_ocr.py` | OCR / layout / plausibility tests |
| `docs/architecture/h9-1-clock-ocr-layout-report.md` | this report |

**Changed**

| Path | Role |
|---|---|
| `riftlens/cli.py` | `read-clock` command |
| `riftlens/domain/__init__.py` | exports |
| `riftlens/pipeline/ingest_video/__init__.py` | exports reader |
| `services/analysis/pyproject.toml` | vision isolation contracts |

## 3. Video reader behavior

`iter_samples(path, hz=1, max_samples=None)`:

- Derives `t_video_ms` from presentation timestamps normalized to stream `start_time` — **never** from frame index.
- Seeks near each target PTS, decodes forward, picks nearest frame within a small window.
- Integer milliseconds; deterministic target grid `0, interval, 2*interval, …`.
- Handles CFR (unit-tested), VFR (unit-tested), non-zero start offset (unit-tested).
- Duration: prefers stream duration → container duration; if metadata is missing or absurdly short (`<50ms`, seen on some R.10 WebMs), falls back to a packet PTS scan.

## 4. LayoutProfile design

Runtime dataclass mapped to existing `LayoutProfileRecord`:

- `width`, `height`, `ui_scale`
- `minimap_rect`, `clock_rect` (`PixelRect`)
- `minimap_flipped`
- `confidence`, `version="h9.1"`, optional `regions` JSON bag

No second persistence model. Affine / world-map fields remain unused (`None`).

## 5. Layout detection strategy

1. Frame dimensions from sample(s)  
2. Minimap estimate in bottom-right band (edge contours / aspect)  
3. `ui_scale` from minimap height vs ~18% of frame height  
4. Flip heuristic via corner blue-channel comparison (False when uncertain)  
5. Clock seeds from resolution-relative `CLOCK_SEEDS`  
6. Local search over offsets/scales  
7. Score candidates with classical digit OCR + colon/clock-shaped text  
8. Emit `LayoutProfile` with blended confidence  

Architecture supports 720p / 1080p / 1440p seeds; **only synthetic + one local 1520×982 capture were exercised** (see §14).

## 6. Glyph atlas construction/source

Under `resources/vision/glyphs/{16,20,24,32}px/`:

- Glyphs `0–9` and `colon.png`
- Each directory has `SOURCE.txt`: **SYNTHETIC OpenCV Hershey glyphs — not League crops**
- `glyphs/README.md` restates the synthetic label

**No fabricated “real League corpus.”** No large media committed.

## 7. OCR algorithm

Classical only (`riftlens/vision/ocr/digits.py`):

ROI → grayscale → adaptive threshold / invert → connected components → height-normalized crops → `cv2.matchTemplate(..., TM_CCOEFF_NORMED)` vs atlas → text + confidence.

No Tesseract, neural OCR, ONNX, or cloud APIs.

## 8. Confidence calculation

- Per-glyph floor: **`GLYPH_MATCH_FLOOR = 0.72`**
- Any glyph below floor → fail closed (`confidence=0`, empty text)
- Multi-glyph confidence via existing domain `combine(scores)`
- Clock reading confidence = digit estimate confidence when parse/plausibility pass; else `0.0` with an explicit `basis` / `reason`

## 9. In-game gate

`is_in_game(frame, layout)`:

- Rejects very low layout confidence
- Requires non-uniform clock crop (std / mean gates)
- Accepts strong digit+colon reads, else weak top-center edge energy + layout confidence floor
- Fail closed: menus / loading / uniform frames → `t_game_ms=None`

## 10. ClockReading schema

```text
ClockReading(
  t_video_ms: int,
  t_game_ms: int | None,
  confidence: float,          # [0, 1]
  in_game: bool = False,
  raw_text: str = "",
  reason: str = "",
)
```

`read_clock` returns `Estimate[int]` (domain convention). Pipeline maps failures to null game time + reason (`not_in_game`, `glyph_below_floor`, `exceeds_90_minutes`, `implausible_jump`, …).

Parses `m:ss` / `mm:ss` / `h:mm:ss`. Rejects malformed seconds, `>90` minutes, and jumps `>5` minutes vs prior confident reading. Pause freeze: repeated samples may report the same `t_game_ms` (not artificially advanced).

## 11. CLI usage

```bash
cd services/analysis
python -m riftlens.cli read-clock <video> --hz 1 [--max-samples N]
```

Prints layout summary and a table: `t_video_ms`, `t_game_ms`, `conf`, `in_game`, `reason`. Unreadable / non-game rows are explicit (`—`, conf `0.000`, reason set).

## 12. Synthetic / unit validation

Deterministic coverage includes:

- PTS CFR / VFR / non-zero start / monotonicity / cadence / accuracy
- `ClockReading` validation
- Atlas load (SYNTHETIC labelled)
- Digit floor fail-closed, missing atlas
- Parse variants + malformed
- `>90` minute rejection (forced OCR path)
- Implausible jump rejection (forced OCR path)
- Non-game uniform frame rejection
- Layout scaling + `LayoutProfile` record round-trip
- Frozen clock equality when readable
- Corrupt/tiny frame handling

H.9.1-focused: **19 passed**. Full sidecar pytest: **660 passed, 8 skipped** (pre-push verify).

## 13. Real League validation performed

Local material under `~/.riftlens/captures/NA1_5620410094/` (not committed):

| Artifact | Notes |
|---|---|
| `attach_…/clip_g829881.webm` | ~16.8 s, 1520×982; primary smoke |
| Earlier `clip_g829881.webm` copies | Bad duration metadata (~0.001 s advertised); reader now scans PTS |

`read-clock --hz 1` on the attach clip:

- Layout ~`1520x982`, `ui_scale≈1.35`, low layout conf `0.35`, clock ROI seeded top-center
- 17 samples in ~2.5 s wall time
- **0 / 17 readable clocks** — all `glyph_below_floor` with synthetic Hershey vs real League HUD font
- Fail-closed behavior held (no confident wrong readings invented)

R.10 research clips ≠ labelled full-VOD H.9 corpus. No ~150-image labelled set exists in-repo.

## 14. Resolution / HUD configurations actually tested

| Config | How |
|---|---|
| Synthetic 1280×720 frames | unit tests |
| Synthetic glyph heights 16/20/24/32 | atlas load / OCR |
| Local capture **1520×982** | CLI smoke only |
| 720p / 1080p / 1440p real League | **not validated** |
| Multiple HUD scales on real client | **not validated** |

## 15. Clean in-game accuracy

**Not measured** against a labelled real corpus.  
Synthetic engineering path: fail-closed when template match is weak; not a substitute for ≥99% clean in-game accuracy.

## 16. Non-game rejection rate

Unit: uniform bright frame → `is_in_game=False`, confidence `0`.  
Real labelled non-game / loading / post-game set: **not measured** (corpus missing). Target ≥95% low-confidence on non-game: **unproven**.

## 17. Confidently-wrong count

On the local smoke clip: **0 confident wrong** (0 confident readings at all).  
Corpus gate “0 confidently wrong across ~150 labelled images”: **unproven**.

## 18. Sampling performance

- Attach clip (~17 s @ 1 Hz): **17 samples in ~2.5 s** wall clock on this Mac (decode + layout + OCR).
- Original “10-minute VOD @ 1 Hz under 20 s” not timed here; no flaky CI hard gate added. Correctness tests separate from benchmark evidence.

## 19. Known limitations

- Atlas is **SYNTHETIC Hershey**, not League HUD glyphs — real VODs currently fail closed at `glyph_below_floor`.
- No labelled 720/1080/1440 in-game / loading / post-game / occluded corpus (~150 images).
- Layout confidence on the smoke clip stayed modest (`0.35`) because OCR scoring of candidates is weak without League glyphs.
- Some WebMs lack trustworthy duration metadata (mitigated by PTS scan fallback; scan costs one demux pass).
- OpenCV and PyAV both ship libavdevice on macOS → duplicate Objective-C class warnings (benign noise).
- Minimap flip / UI scale heuristics are coarse.
- H.10 SyncMap fitting / auto-sync API intentionally not implemented.

## 20. ENGINEERING_COMPLETE verdict

**ENGINEERING_COMPLETE = YES**

PTS reader, domain types, layout package, classical OCR + synthetic atlas, in-game gate, clock parse/plausibility, pipeline orchestration, CLI, unit tests, import-linter isolation, and sidecar verify (pytest / ruff / mypy --strict / lint-imports) are in place.

## 21. REAL_CORPUS_ACCEPTANCE verdict

**REAL_CORPUS_ACCEPTANCE = BLOCKED_INSUFFICIENT_CORPUS**

Missing the original H.9 labelled ~150-image gate (resolutions × in-game/loading/post-game/occluded) with targets ≥99% / ≥95% / 0 confident-wrong. Local R.10 smoke does not satisfy that gate.

## 22. Whether H.10 is now genuinely unblocked

| Question | Answer |
|---|---|
| H.10 **engineering** (consume `ClockReading[]`, implement RANSAC / SyncMap fitter behind VIDEO path) | **Unblocked** — the H.9.1 API and types exist |
| H.10 **real auto-sync** on League VODs end-to-end | **Still blocked** until a real (or sufficiently League-like) glyph atlas + labelled corpus make OCR produce trustworthy 1 Hz readings |

Stop here. Do not treat this report as permission to start H.10 without an explicit work order.
