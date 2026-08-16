# Phase 1 acceptance amendment — native `.rofl` is primary

**Document type:** Spec / acceptance-plan amendment (not an implementation work order)  
**Date:** 2026-08-16  
**Branch:** `integrate/ui-r1`  
**Amends:** Cursor Spec **H.12** (Phase 1 Definition of Done); Technical Design §11.4 (MVP 0.1 success table) as overlapping context  
**Does not rewrite:** H.9.1 / H.10 historical VIDEO reports or their verdicts  
**Does not implement:** product code, H.12 execution, R.12, V.7, baseline-corpus harvesting

Sources for the original gates: `RiftLens_Phase1_Cursor_Spec.md` §H.12; `RiftLens_Technical_Design.md` §11.4. Architecture history: [`native-replay-ingestion-amendment.md`](./native-replay-ingestion-amendment.md). VIDEO status: [`h9-1-h10-real-vod-validation-report.md`](./h9-1-h10-real-vod-validation-report.md).

---

## 0. Product decision (this is the load-bearing sentence)

**Native League `.rofl` replay is the primary supported gameplay source for RiftLens Phase 1.**

VIDEO/VOD remains implemented as an **optional / experimental** gameplay source. Lack of a 10-real-VOD corpus **must not** block completion of the ROFL-first Phase 1 product.

This was **not** the original Phase 1 plan. Original H.12 assumed player-POV VIDEO + clock OCR + verified `SyncMap` as the way to attach gameplay. The R-series then made `.rofl` a first-class `GameplaySource`. MacReplayHost later made native replay viable on macOS. Real OBS/ShadowPlay VODs never appeared on the development machine, and fabricating a VOD corpus to satisfy an obsolete assumption is rejected.

GST, metrics, rules, findings, evidence, and null-LLM completeness are unchanged. Only the **Phase 1 release-blocking gameplay surface** changes.

---

## 1. Historical VIDEO verdicts (unchanged, still true)

These remain the correct VIDEO statements. They are **not** flipped by this amendment.

| Verdict | Value | Meaning |
|---|---|---|
| **H9_1_REAL_CORPUS** | **PARTIAL** | Real clock crops exist (one match, 1520×982, mid-game). Not held-out, not 1080p/1440p, not early/late. |
| **H10_REAL_VOD_ACCEPTANCE** | **BLOCKED_INSUFFICIENT_CORPUS** | Zero REAL OBS/ShadowPlay/player-POV VODs locally. Engineering PASS is not acceptance. |
| **H12_VIDEO_READINESS** | **BLOCKED** | Original H.12 gates #1, #5, #6 cannot be attempted honestly. |

**ROFL must not fake those numbers.**

- `.rofl` does **not** satisfy H.10 real-VOD acceptance.
- Replay API `ClockMap` does **not** prove H.9.1 OCR accuracy.
- R.10 generated `.webm` does **not** count as OBS/ShadowPlay validation.
- Replay-generated video does **not** count toward the historical 10-VOD gate.
- MacReplayHost success does **not** satisfy H.10 real-VOD acceptance.

The historical VIDEO gates stay BLOCKED/PARTIAL. They are **no longer release-blocking** for ROFL-first Phase 1. They become **deferred VIDEO validation debt** (§6).

---

## 2. Why the architecture changed

| Era | Gameplay attachment assumption |
|---|---|
| Original Cursor Spec / TD | Match + optional **VOD**. Click-to-moment = VIDEO `SyncMap` from clock OCR (H.9/H.10). |
| Native-replay amendment | `.rofl` added as a **parallel** `GameplaySource` (initially specified Windows-only). VIDEO path kept. H.10+ continued. |
| MacReplayHost production | Native replay control proven on macOS. Overlay, R.10 capture, camera framing exist on the supported replay path. |
| VIDEO corpus work (2026-08-16) | Local inventory: **0** REAL VODs. Tooling ready. Acceptance still BLOCKED. |
| **This amendment** | Phase 1 **ships on TIER 1 ROFL**. TIER 2 VIDEO stays in the product as experimental, not production-validated. |

The analysis core never needed VIDEO: GST is MATCH-V5 + timeline. Replay is a **rendering and navigation surface** over an analysis that already exists. Once that surface worked via Replay API, VIDEO OCR stopped being a Phase 1 prerequisite.

---

## 3. Source support tiers

### TIER 1 — Native `.rofl` (primary Phase 1)

Expected capabilities:

- Import `.rofl`
- Authoritative replay identity (filename / sniffer; no fixture contamination)
- Riot MATCH/timeline association
- Participant selection
- Deterministic coaching review (H.2–H.8 via H.11)
- Native `ClockMap` (Replay API / calibrated replay clock — **not** VIDEO `SyncMap`)
- Open Replay
- Replay API **READY**
- Click coaching finding → correct replay seek
- Lead-in handling
- Overlay on supported platform
- Optional R.10 capture
- Camera framing where applicable
- **No manual VIDEO SyncMap required**

### TIER 2 — VIDEO/VOD (experimental / optional in Phase 1)

Engineering exists:

- H.9.1 clock OCR
- H.10 automatic synchronization
- Manual synchronization
- H.11 `ingest_video` / `synchronize` stages (skipped for ROFL)

**Must not be described as production-validated.** UI may still offer Attach Video. Docs, marketing, and H.12 reports must say experimental until §6 debt is closed.

---

## 4. Original H.12 → ROFL-first traceability

Classification:

- **A** — still mandatory for ROFL-first Phase 1
- **B** — VIDEO-specific; deferred / non-blocking
- **C** — still useful; adapt to ROFL
- **D** — obsolete because newer R-series architecture superseded it (keep the original text; do not delete)

Cursor Spec H.12 originally required **all 11 true simultaneously**. This amendment **splits** that conjunction: A/C gates remain the Phase 1 DoD; B gates remain on the books as VIDEO debt; D notes architecture supersession without erasing history.

| # | Original gate | Original intent | Class | ROFL-first replacement | VIDEO status |
|---|---|---|---|---|---|
| 1 | `review … --vod <path>` → complete review, **verified SyncMap**, ≥20 metrics, findings from ≥20 rules, exactly 3 focus, ≥2 strengths | Prove the full CLI product **with attached gameplay media** | **C** | `review <match_id> --pid <n>` **without** `--vod`, with a **linked real `.rofl`**: complete review; native ClockMap (not VIDEO SyncMap); shipped H.5 metric computers all run; H.7 production pack (≥20 rules) can emit findings; exactly 3 focus; ≥2 strengths. `--vod` is TIER 2 and not required. | Historical #1 remains BLOCKED (no verified VIDEO SyncMap on real VODs). |
| 2 | `--no-vod` → complete review minus video-linked features | Analysis must not depend on VIDEO | **A** | Same. Omitting `--vod` is the CLI equivalent if `--no-vod` is absent. ROFL import is **not** “video-linked.” | N/A (this gate is the no-VIDEO path). |
| 3 | `--no-llm` → complete review, template prose | Null provider is a product, not a stub | **A** | Unchanged. | Unchanged. |
| 4 | Re-run after a rule change **<10 s**, **0 Riot calls** | Cacheable deterministic pipeline | **A** | Unchanged. Confirm on a **cached real match_id** (not only fixtures). VIDEO OCR must not be in this budget. | VIDEO decode time is irrelevant to this gate. |
| 5 | Fresh **30-minute VOD <90 s** excluding LLM, 6-core CPU | Bound VIDEO OCR + analysis | **B** | See §5 performance: ROFL-first wall-clock targets. Do **not** reuse 90 s VIDEO decode as a ROFL target. | Remains BLOCKED (no ~30 min REAL VOD). Deferred VIDEO debt. |
| 6 | Auto-sync unaided **≥9/10** real recordings, **p95 ≤500 ms** | Production VIDEO SyncMap quality | **B** | Native ClockMap + measured seek landing (expected `t_ms`, lead-in target, actual replay clock, delta). No 10-VOD OCR fitter. | **H10_REAL_VOD_ACCEPTANCE = BLOCKED_INSUFFICIENT_CORPUS** (unchanged). |
| 7 | `pytest` pass; coverage `domain` + `analysis` **≥85%** | Engineering hygiene | **A** | pytest still mandatory. Coverage ≥85% still mandatory (currently **unmeasured** — must be run, not waived). | N/A |
| 8 | `mypy --strict`, `ruff`, `import-linter` clean | Engineering hygiene | **A** | Unchanged. | N/A |
| 9 | No Riot API key in `logs/` | Secret hygiene | **A** | Unchanged. Scan a real run, not only unit tests. | N/A |
| 10 | 15-match labelled corpus, rule precision **≥0.8** | Coaching quality | **C** | Keep ≥0.8 on the **existing** H.7 labelled corpus (synthetic GSTs — already the engineering bar). Do **not** pretend those 15 folders are 15 real Riot games. Product quality additionally requires criterion 11 on **real ROFL-backed reviews**. Expanding to 15 real labelled matches is valuable but is **not** a VIDEO-shaped N=10 requirement. | N/A |
| 11 | Read **10** generated reviews; would show a friend | The real DoD | **A** | Unchanged intent. Prefer reviews from **real** matches (ROFL-linked when possible). Template/`--no-llm` prose is allowed. Live LLM is not required. | Must not use fake VOD reviews to pad the 10. |

**TD §11.4 extras** (not Cursor H.12, recorded so they are not silently dropped or silently adopted):

| TD §11.4 | Class | Disposition |
|---|---|---|
| ≥90% auto-sync on 1080p OBS/ShadowPlay | **B** | Same debt as H.12 #6 / H.10 real-VOD. |
| p95 ≤500 ms when VIDEO sync succeeds | **B** | Unchanged VIDEO debt. |
| ≤4 Riot calls per new match | **A** | Still mandatory (account + match + timeline cache). |
| ≤10 s re-analysis | **A** | Same as H.12 #4. |
| ≥99% crash-free on **50-VOD** corpus | **B** / **D** | VIDEO crash corpus is deferred. Do not invent a 50-ROFL crash corpus for symmetry. ROFL-first crash bar: analysis jobs on available real matches + fixture suite; no League-in-CI. |
| 6–14 shown findings, exactly 3 focus | **A** | Unchanged review shape. |
| ≥80% precision on 20 hand-reviewed games | **C** | Cursor H.12 used 15 labelled + 10 friend-reads. Do not raise to 20 real games in this amendment. Friend-test (H.12 #11) is the qualitative bar. |
| 100% LLM numeral hallucinations caught | **A** | H.11 AC1 already; keep. |
| App works with LLM disabled | **A** | Same as H.12 #3. |
| Three friends / two “I didn’t know…” | **C** | Cursor H.12 #11 is the operator friend-test. Three live friends remain a **nice** MVP qualitative, not a new blocker invented here. |
| Overlay excluded from original v0.1 (TD §11.2) | **D** | R.10.5 shipped overlay. Overlay **is** in the ROFL-first DoD on supported platforms. Original “no live overlay” is superseded for TIER 1, not rewritten as if TD always included it. |

**Original H.12 also said** H.12 must not launch League / overlay / capture. That constraint applied to a **VIDEO-CLI DoD**. It is **D** for TIER 1: ROFL-first Phase 1 **does** launch League on the operator machine for seek/overlay/capture evidence. CI still must not require League (T0–T2).

---

## 5. ROFL-first Phase 1 Definition of Done

All of the following are **mandatory** for declaring ROFL-first Phase 1 complete. None may be satisfied by VIDEO OCR, R.10 clips-as-VODs, or synthetic GSTs pretending to be real matches (except the explicit H.7 precision corpus in Q2).

### RF-1 REAL ROFL IMPORT

- A real `.rofl` file (not a fixture binary pretending to be a full replay).
- Identity resolves to the correct `match_id` (filename/sniffer chain).
- No contamination from unpaired fixtures A/B/C.
- Real Riot MATCH + timeline association (cached forever after first fetch).

### RF-2 ANALYSIS

- H.11 job completes for that match (no `--vod` required).
- GST / shipped H.5 metrics / H.7 rules / H.8 review generated.
- Null-provider path works; every shown explanation non-empty.
- Deterministic review remains authoritative (LLM does not select findings).
- Review shape: exactly 3 focus items, ≥2 strengths, shown-finding count in the product’s normal band (target 6–14 when the match supports it; do not pad).

### RF-3 REPLAY SESSION

- Native replay opens on the claimed platform.
- GAMELOOP reached.
- Replay API **READY** (`playback` usable, length > 0).
- Native ClockMap available (CALIBRATED/GOOD as designed — **not** a VIDEO SyncMap).

### RF-4 SEEK

For **multiple** coaching items on a real session:

- Expected evidence `t_ms` recorded
- Lead-in target recorded
- Actual replay clock recorded after seek
- Delta measured
- Landing within the existing real-replay tolerance (**≤1000 ms**, as R.9 T4)
- **No manual VIDEO SyncMap**

### RF-5 OVERLAY (supported platform)

- Overlay appears over replay
- Access Overlay does not strand the user in RiftLens
- Next / previous / seek from overlay works
- Replay-only safety preserved (no live-game overlay)
- Exclusive-fullscreen limitation remains documented, not a silent fail

### RF-6 CAPTURE (optional path, still honest)

When R.10 capture is exercised:

- Requested interval actually covered
- Truncation detected rather than silent short files
- Camera framing metadata honest (`camera_controlled` not invented)

Capture is **not** a substitute for RF-3/RF-4. A Phase 1 claim of “capture works” needs at least one real covered interval on a real `.rofl`.

### RF-7 PERFORMANCE (ROFL-first, not VIDEO-borrowed)

Measure realistic operations. **Do not** use the 30-minute VOD <90 s number.

| Operation | Target |
|---|---|
| Cached re-analysis after a rule/stage bump (no VIDEO OCR, 0 Riot calls) | **<10 s** (H.12 #4) |
| Fresh analysis of an already-cached match (GST + metrics + rules + review, `--no-llm`, no League) | **<10 s** on a 6-core-class machine |
| First ingest of a new match (2 Riot GETs: match + timeline; account already cached) | **≤4 Riot calls**; wall clock not gated on network |
| Replay open → READY | Recorded; fail if session never becomes READY within the existing product timeout (R-series ~120 s poll). Not a 90 s VIDEO clone. |
| Seek landing | **≤1000 ms** vs lead-in target (RF-4) |

Record machine, OS, and whether League launch time is included (it should be reported separately from analysis time).

### RF-8 QUALITY

- H.7 labelled-corpus precision **≥0.8** (existing synthetic GST corpus — engineering).
- Do **not** weaken rules because the gameplay source is ROFL.
- Do **not** expand or shrink the rule pack solely to make a count look like “20.”
- Metric interpretation: Phase 1 requires the **shipped 10 H.5 computers** to run, not a silent claim of 20 Appendix F IDs. Expanding metrics is a separate work order, not a VIDEO unblocking trick.

### RF-9 OFFLINE / NULL LLM

- `llm_provider=null` / `--no-llm` yields a complete useful review.
- H.11 AC1-class hallucination rejection remains in force if a live provider is enabled later.

### RF-10 TOOLING HYGIENE

- Full sidecar pytest pass
- `mypy --strict`, `ruff`, `import-linter` clean
- Coverage of `riftlens/domain` and `riftlens/analysis` **≥85%** (measure; currently unknown)
- No Riot API key in `logs/` on a real run

### RF-11 FRIEND TEST

- Operator has read **10** generated reviews end to end and would show them to a friend.
- Prefer real matches. Fixture-only reads do not close this gate.

---

## 6. Deferred VIDEO validation (explicit debt)

Promote VIDEO from experimental to **production-supported** only after all of the following. Until then, say “experimental.”

1. Diverse **REAL** player-POV VOD corpus (OBS/ShadowPlay-class), paired `match_id`s. Historical target ≥10 remains the VIDEO bar — not a ROFL bar.
2. Held-out H.9.1 OCR (matches **other than** atlas-train `NA1_5620410094`), early/mid/late, native resolutions/scales where available. Flip **H9_1_REAL_CORPUS** from PARTIAL only with that evidence.
3. **H10_REAL_VOD_ACCEPTANCE = PASS** (independent checkpoints, p95 ≤500 ms, unaided auto-sync). R.10 clips still do not count.
4. Original H.12 **#5**: ~30-minute REAL VOD, <90 s excluding LLM, 6-core-class CPU. 17 s R.10 clips still do not count.
5. Original H.12 **#1** with `--vod` and a **verified VIDEO SyncMap**.
6. Original H.12 **#6** (≥9/10, p95 ≤500 ms).

Tooling already exists (`riftlens.cli vod-corpus`). No need to rebuild it. Do not start that work as part of ROFL-first H.12.

---

## 7. Platform matrix (honest claims)

| Platform | Native `.rofl` | VIDEO attach | Phase 1 claim |
|---|---|---|---|
| **macOS** | Supported via **MacReplayHost** (production). Proven locally on real `.rofl`: launch, Replay API pause/play/seek, ClockMap, coaching-item seek, overlay, R.10 capture, camera framing. | Experimental (engineering present; corpus BLOCKED). | **Primary Phase 1 demo platform for TIER 1.** H.12-ROFL must **re-record** seek/overlay evidence on current `integrate/ui-r1` HEAD (see §8). |
| **Windows** | Supported via **WindowsReplayHost**. R.9 desktop T4 **PASSED** (2026-08-09) and R.10.5 overlay T4 **PASSED** (2026-08-11) on `NA1_5617764200`. Those reports are **not** automatically valid for today’s HEAD. | Experimental. | **Do not claim current Windows real-replay acceptance until T4 is rerun on this HEAD.** Automated T0–T2 remain the CI confidence. |
| **Linux** | **Unsupported** native replay (`UnsupportedReplayHost` / no League Replay API host). | Experimental if someone attaches a VOD; not a Phase 1 support claim. | Analysis-only (Riot + review) may run; **no** native Open Replay. |

The original native-replay amendment’s “macOS ROFL = `PLATFORM_UNSUPPORTED`” UI copy is **superseded** by MacReplayHost. That older sentence stays in the historical amendment; this document is the current product claim.

---

## 8. H.12 readiness after this amendment

### 8.1 Already have evidence (do not treat as finished H.12)

| Area | Evidence | Gap |
|---|---|---|
| H.11 job / null LLM / cache / cancel / diagnostics | H.11 report; AC1–AC5 PASS | Re-run CLI `--no-llm` on a **real** cached match as RF-2/RF-9 |
| Sidecar pytest / ruff / mypy / import-linter | Green on current HEAD (post VIDEO-tooling commit) | Coverage 85% **not measured** (RF-10) |
| H.7 precision ≥0.8 | Synthetic labelled corpus | Not 15 real games (accepted as engineering bar in RF-8) |
| Windows T4 import/open/seek | [`r9-desktop-t4-report.md`](./r9-desktop-t4-report.md) `NA1_5617764200` | Older HEAD — **rerun** |
| Windows overlay | [`r105-overlay-t4-report.md`](./r105-overlay-t4-report.md) | Older HEAD — **rerun** |
| macOS native replay / ClockMap / seek / overlay / capture | Operator-proven on `NA1-5620410094.rofl`; R.10 clips and V-series captures exist | **Re-record on current HEAD** with timestamps/deltas (RF-4/RF-5/RF-6) |
| VIDEO OCR / auto-sync engineering | H.9.1 / H.10 engineering PASS | Real-VOD acceptance BLOCKED — **non-blocking** |

### 8.2 Requires rerun on current HEAD

- RF-2 analysis job for `NA1_5620410094` (and Windows match if rerun)
- RF-3/RF-4/RF-5 Mac session log (READY, seeks, overlay)
- RF-7 timings (analysis vs League launch vs seek)
- RF-10 coverage + log redaction scan
- Windows T4 if a Windows machine is available

### 8.3 Additional real `.rofl` matches

**One real match is sufficient for smoke** (import → identity → review → open → one seek).

**One match is not sufficient for meaningful Phase 1 acceptance.** Failure modes are launch/lifecycle/patch-lock/seek/overlay, plus coaching quality across different games. Those are not OCR-style sampling problems, so **N=10 is the wrong shape**.

**Recommended acceptance set: 2 independent real matches, 3 if a third `.rofl` is already on disk.**

| Match | Role |
|---|---|
| **`NA1_5620410094`** | Keep. Local Mac `.rofl` + Riot cache + capture/overlay history. Primary Mac H.12-ROFL case. |
| **`NA1_5617764200`** | Keep. Existing Windows T4 subject. Rerun T4 on current HEAD if Windows is available; still counts as a second independent real match for analysis/review even if Windows T4 waits. |
| **Optional third** | Only if a different patch and/or duration `.rofl` is already available. Do not grind ten new games for symmetry with the old VOD gate. |

**Why not 10:** VIDEO N=10 existed because constrained RANSAC + OCR residuals need a corpus. Native ClockMap is Replay API time vs GST `t_ms`. Repeating seek 10 times on the same client proves little that 4–6 seeks on 2 matches would not. Coaching quality is gated by RF-8/RF-11, not by replay-file count.

**Why not 1:** A single patch-locked replay can hide launch/cfg/API drift and makes the friend-test a single-game anecdote.

### 8.4 Can we proceed with H.12 now?

**Yes — as ROFL-first H.12 validation (execute §5), not as original VIDEO 11-gate DoD, and not as new architecture.**

**No** — if “H.12” still means Cursor Spec’s simultaneous 11 including `--vod` + 9/10 auto-sync + 30-minute VOD. That interpretation is what this amendment replaces for Phase 1 release.

Do not start R.12 or V.7. Do not harvest a baseline corpus. Do not “complete” VIDEO gates with ROFL.

---

## 9. Recommended next work order

**H.12-ROFL — Execute the ROFL-first Phase 1 Definition of Done** on `integrate/ui-r1`.

Scope: validation and evidence recording against §5 (RF-1…RF-11) and §7. No new coaching rules, no VIDEO corpus harvest, no R.12, no V.7, no production architecture redesign.

Primary Mac case: `NA1_5620410094`. Second case: `NA1_5617764200` (analysis now; Windows T4 if the machine is there). Measure coverage. Read 10 reviews.

Stop when the ROFL-first DoD is honestly PASS, PARTIAL, or FAIL — with VIDEO debt still listed as BLOCKED/PARTIAL.

---

## 10. What this document is not

- Not a claim that VIDEO engineering was wasted (H.9.1/H.10 remain in-tree for TIER 2).
- Not a license to skip RF-11 or precision.
- Not Windows T4 on current HEAD.
- Not Linux native replay support.
- Not H.12 execution (this file is the plan only).
