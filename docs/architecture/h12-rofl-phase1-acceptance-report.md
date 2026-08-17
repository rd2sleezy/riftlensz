# H.12-ROFL — Phase 1 ROFL-First Definition of Done

**Date:** 2026-08-16  
**Branch:** `integrate/ui-r1`  
**Does not implement:** R.12, V.7, VIDEO corpus harvesting, new visual research, new coaching rules, new product architecture, remote replay hosting, Phase 2.

This work order is validation / hardening on current HEAD. Historical VIDEO verdicts are not reinterpreted.

---

## 1. Amendment / spec used

Authoritative acceptance specification:

- [`docs/architecture/phase1-rofl-first-acceptance-amendment.md`](./phase1-rofl-first-acceptance-amendment.md)

Also re-read: `docs/CURSOR.md` (native `.rofl` is Phase 1 primary).

Primary Mac case: **`NA1_5620410094`**.  
Real file: `/Users/rylanddunn/Documents/League of Legends/Replays/NA1-5620410094.rofl` (19 295 406 bytes).

Machine: Apple M4 (10-core), macOS darwin 25.5.0.

---

## 2. Current commit tested

- Amendment HEAD at start of this work order: **`95b2b51`** (`Record the Phase 1 decision that native .rofl is the primary gameplay source.`)
- This report is committed with the H.12-ROFL validation patches on `integrate/ui-r1` (CLI no-VIDEO path, idempotent persist, end-of-replay READY recovery). The tree that produced the RF evidence is that patched HEAD, not `95b2b51` alone.

Evidence artifacts (no media, no secrets):

- [`h12-rofl-rf1-rf2-evidence.json`](./h12-rofl-rf1-rf2-evidence.json)
- [`h12-rofl-rf3-rf6-evidence.json`](./h12-rofl-rf3-rf6-evidence.json)
- [`h12-rofl-rf6-capture-evidence.json`](./h12-rofl-rf6-capture-evidence.json)

---

## 3. RF-1 — Real ROFL import / identity

**Verdict: PASS**

| Field | Value |
|---|---|
| Replay identity | filename `NA1-5620410094.rofl` → `match_id_hint=NA1_5620410094` |
| Identify method | `filename` (header parse `partial`; magic `RIOT`; declared patch `16.16.804.9184`) |
| Match id | `NA1_5620410094` (already in local MATCH-V5 cache / DB; queue 420; duration 2 478 546 ms) |
| Gameplay source id | `01M06GVEVV8E4VTD3K2FXPXW9B` |
| Source type / URI | `rofl` / the real Documents path above |
| Review id | `01M06GVG21399Y34RQ3YSWN96A` |
| Participant id | **6** |
| Champion / role / result | **Vladimir** / TOP / WIN |

Checks:

1. Identity extracted from the `.rofl` (not typed by the operator).
2. Bound match id is the Riot id, not a fixture.
3. Import with open-review `NA1_fixture_a` returned **`MATCH_IDENTITY_MISMATCH`** (`open_match_id=NA1_fixture_a`, `replay_match_id=NA1_5620410094`). No silent fixture bind.
4. Production review list (`include_fixtures=False`) shows this real review only among non-fixture cards.
5. Participant 6 is Vladimir in `match_participation`; review champion matches.
6. After constructing a new `GameplaySourceService` (reload), `resolve_source` and `status_for_match` still select source `01M06GVEVV8E4VTD3K2FXPXW9B` on `NA1_5620410094`.
7. `gameplay_source` rows: one real ROFL; `fixture_source_bound=false`.
8. Review presentation `fixture_id=null`, `sync_map=null`, `unpaired_match_timeline=false`.

---

## 4. RF-2 — H.11 real analysis

**Verdict: PASS**

Production path: `python -m riftlens.cli review NA1_5620410094 --pid 6 --no-llm` (no `--vod`). Provider **`null`**.

| Stage | Fresh (ms) | Fresh cache | Cached rerun (ms) | Cached cache |
|---|---:|---|---:|---|
| ingest_riot | 252 | miss | 6 | **hit** |
| ingest_video | 0 | skipped | 0 | skipped |
| synchronize | 0 | skipped | 0 | skipped |
| build_facts | 12 | miss | 51 | **hit** |
| compute_metrics | 102 | miss | 1 | **hit** |
| run_rules | 354 | miss | 0 | **hit** |
| prioritize | 87 | miss | 0 | **hit** |
| compose_coaching | 2 | miss | 0 | **hit** |
| persist | 300 | n/a (uncacheable) | ~294–335 | miss (always runs) |
| **job wall** | **1109** | 0 hits / 7 misses | **~335–546** | **6 hits** |

Confirmations:

- Job **COMPLETED**. VIDEO/OCR/H.10 stages skipped (`No VIDEO media` / `No VIDEO to synchronize`).
- Review shape: **3 focus**, **2 secondary**, **1 strength**, **9 findings**, 10 H.5 metric ids (`M-01`–`M-05`, `M-07`, `M-15`, `M-19`, `M-20`, `M-22`).
- Every coaching `body` / `the_fix` / `next_game_check` non-empty (`all_explanations_nonempty=true`).
- `llm_provider=null`, `llm_fallback=false`. Findings remain deterministic authority.
- Review persists under `~/.riftlens/reviews/` and reloads.
- No LLM network. First ingest used on-disk Riot cache (`riot_get` `cache_hit=true`); cached rerun made **0** `RiotClient.get_match` / `get_timeline` calls.

A first cached rerun **FAILED** with `IntegrityError UNIQUE finding.id` — genuine persist bug, fixed in this commit, then rerun **COMPLETED** (same `review_id`).

---

## 5. RF-3 — Native replay / ClockMap

**Verdict: PASS**

| Step | Result |
|---|---|
| Discover League | `/Applications/League of Legends.app/Contents/LoL` (`well_known`) |
| `game.cfg` | EnableReplayApi already true (Game + LoL Config copies) |
| Environment | `install_found=true`, `replay_api_documented=true`, `live_game=false` |
| Open Replay | phase **PLAYING**, error null, ~1.06 s (existing GAMELOOP attached) |
| GAMELOOP / READY | `session_reached_ready=true`; playback `length_ms=2484308` |
| ClockMap | **OFFSET**, `clock_verified=true` (from reveal; ~+3 ms vs identity) |
| Review / status | real source `01M06GVEVV8E4VTD3K2FXPXW9B`; not a fixture |

No manual VIDEO SyncMap. No OCR. No H.10. `sync_map_involved=false`.

**Bug found then fixed:** first open failed `PLAYBACK_NOT_ADVANCING` at `t=2484.4s` (end of replay). Supervisor now rewinds a finished replay, then proves advancement. Mid-timeline freeze still fails. Regression: `test_playback_at_end_rewinds_then_ready`.

Cold League launch (process start → READY) was **not** measured; this session attached to an already-running replay (~1.07 s open→READY). Product timeout remains ~120 s.

`status_for_match` has `session_reached_ready`, not a `replay_connected` key. Session was live (`PLAYING`, length > 0).

---

## 6. RF-4 — Real coaching seeks

**Verdict: PASS**

Lead-in: **8000 ms**. Tolerance: **≤1000 ms** vs intended target. Four legitimate items (3 focus + 1 secondary).

| Item | evidence `t_ms` | lead-in | expected target (game−lead-in) | Replay API target | landed | Δ vs target | Δ vs raw evidence | seek wall |
|---|---:|---:|---:|---:|---:|---:|---:|---:|
| Stop dying to an unseen jungler | 1 468 841 | 8000 | 1 460 841 | 1 460 844 | 1 460 844 | **0** | −7997 | 1876 ms |
| Do not start fogged fights | 1 446 861 | 8000 | 1 438 861 | 1 438 864 | 1 438 864 | **0** | −7997 | 1920 ms |
| Spend tempo after a won fight | 1 556 719 | 8000 | 1 548 719 | 1 548 722 | 1 548 722 | **0** | −7997 | 1891 ms |
| Show up for objectives | 427 729 | 8000 | 419 729 | 419 732 | 419 732 | **0** | −7997 | 1882 ms |

Landing error vs intended ClockMap target is **0 ms** on all four (well under 1000 ms). Δ vs raw evidence is the configured 8 s lead-in plus the ~3 ms OFFSET.

The fourth seek recorded `ok=false` **after** a perfect landing: subsequent `GET /replay/playback` returned HTTP 404 `Invalid URI format`. Not silently compensated. First three seeks fully `ok=true`. RF-4 uses the ≤1000 ms landing gate; all four landings meet it.

No manual SyncMap.

---

## 7. RF-5 — Overlay

**Verdict: BLOCKED** — live overlay on this real replay was **not visually observed** in this agent session (Electron overlay was not launched over League).

### Engineering (automated, current HEAD) — PASS

- `inputPolicy.test.ts`: no Electron `globalShortcut` in overlay modules; no process injection / Replay API from overlay code.
- `macOverlay.contract.test.ts`: prev/next/seek/minimize/expand **without Escape or Space**; live-game refuse; Spaces/fullscreen documented, not auto-switched.
- `hotkeys.ts`: Escape and bare Space unclaimed.
- `displayModeAssist.ts`: exclusive fullscreen / separate macOS Space cannot keep an always-on-top companion; Borderless/Windowed is the supported path; no `game.cfg` WindowMode write, no Alt+Enter, no injection.
- Overlay vitest suite included in 90 passing desktop tests.

### Manual checks still required (not claimed)

On a Windowed or Borderless replay of `NA1_5620410094`:

1. Access Overlay opens the separate overlay window.
2. League remains or is restored frontmost after Access Overlay.
3. Overlay is visible over the replay (not trapped behind League).
4. Previous / next coaching item works.
5. Seek from overlay lands (same ClockMap path as RF-4).
6. Minimize/hide works; restore/Access Overlay works.
7. Overlay survives replay seeks / session updates.
8. Overlay closes/hides when the replay session ends.
9. Live-game safety remains fail-closed (do not overlay a live match).
10. No global hotkey regression; Escape/Space remain League’s.

**Fullscreen limitation (honest):** overlay is not claimed over a separate macOS fullscreen Space or Windows exclusive D3D fullscreen. Player path is Borderless/Windowed + Recheck.

---

## 8. RF-6 — Capture

**Verdict: PASS** (one representative covered CLIP on current HEAD). Large `.webm` **not committed**.

### 8 s attempt (too short on disk after cleanup)

| Field | Value |
|---|---|
| Capture id | `01M06HAW7605DV5CTY654W4GP2` |
| Requested | 1 464 841–1 472 841 ms (**8000 ms**) around death `t_ms=1468841` |
| Result | **`CAPTURE_TRUNCATED`**, status **failed**, not COMPLETE |
| Wall | 8.555 s |
| Artifacts | 0 (partials deleted on truncate — existing R.10 behavior) |

Truncated media did **not** become COMPLETE.

### 3 s covered CLIP (representative success)

| Field | Value |
|---|---|
| Capture id | `01M06HD279SGGSWT69P30K1EFY` |
| Requested | 1 467 341–1 470 341 ms (**3000 ms**); evidence 1 468 841 **inside** interval |
| Actual duration | **2762 ms** |
| Frame count | **72** |
| Min acceptable | 2700 ms (90% of 3000) |
| Coverage verdict | **`covered`** |
| Completion method | `api_recording_false` |
| Status | **`complete`** |
| Wall | 3.824 s |
| Artifact | `clip_g1467341.webm` 2 408 246 bytes (local only) |
| Camera strategy | none requested |
| `camera_controlled` | **false** (honest — no framing plan) |
| Placement delta | n/a |
| Restore | n/a (no camera apply) |
| Clock | GOOD, verified |

An 8 s request truncating while a 3 s request covering is recorded honestly. Capture wall time is **not** mixed into analysis budgets (RF-7 F).

---

## 9. RF-7 — ROFL-first performance

**Verdict: PASS** against the amendment table (no borrowed VIDEO &lt;90 s gate).

| Op | Target | Measured | Notes |
|---|---|---|---|
| A. Fresh deterministic analysis (cached match, cold stage cache, `--no-llm`, no League) | &lt;10 s (amendment) | **1.300 s** (job 1109 ms) | Riot disk cache hits; not a new invented threshold |
| B. Cached deterministic rerun | **&lt;10 s**, **0 Riot API calls** | **0.488–0.546 s**, **0** `get_match`/`get_timeline` | 6 stage-cache hits |
| C. Replay open → READY | record; fail if never READY in ~120 s | **1.07 s** attached session | Cold launch not measured this run |
| D. Coaching seek request → landed clock | landing ≤1000 ms | landing **0 ms**; request wall **~1.9 s** | Wall includes HTTP; gate is landing error |
| E. Overlay access | if measurable | **not measured** | RF-5 blocked |
| F. R.10 capture | report separately | **3.824 s** for 3 s CLIP; 8.555 s truncated 8 s attempt | Recording consumes wall time |

Future budget: keep the amendment’s **&lt;10 s** fresh cached-match analysis number. Measured 1.3 s on M4; no tighter gate invented here.

---

## 10. RF-8 — Coaching precision / metrics

**Verdict: PASS**

Command: `pytest tests/unit/test_labelled_corpus.py`

| Item | Value |
|---|---|
| Labelled corpus | **15 synthetic GSTs** (not 15 real games) |
| TP | **15** |
| FP | **0** |
| Precision | **1.0** (≥ 0.8) |
| Production rule ids in pack | 25 (`R-0*` / `P-0*` excluding `R-000`) |

H.5 computers present and exercised (10):

`CsPerMinute`, `CsDifferential`, `GoldDiffCurve`, `XpDifferential`, `DeathsByPhase`, `DeathCostTotal`, `ObjectiveParticipation`, `FightParticipation`, `DamageGoldEfficiency`, `DeathLocationClusters`.

Real-match review emitted metric ids M-01, M-02, M-03, M-04, M-05, M-07, M-15, M-19, M-20, M-22. No rules added to inflate precision.

---

## 11. RF-9 — Tests / coverage

**Verdict: PASS**

### Python

| Gate | Result |
|---|---|
| Full pytest (no cov) | **736 passed**, 8 skipped, 99.59 s |
| Coverage command | `python -m pytest --cov=riftlens.domain --cov=riftlens.analysis --cov-report=term --cov-report=json` |
| Combined `domain`+`analysis` | **89.11%** (6234 stmts, 5555 covered, 679 missing) |
| `riftlens.domain` | **91.97%** |
| `riftlens.analysis` | **86.58%** |
| ruff | clean |
| mypy --strict | clean (267 source files) |
| import-linter | 12 contracts kept |

Coverage under instrumentation failed `test_engine_fixture_a_under_500ms` (589.8 ms vs 500 ms). **Same test passes without coverage** (0.51 s file). Not a product regression; do not game coverage.

Lowest coverage files (not padded with junk tests): `rules/lab.py` 58%, `predicates/segmenters.py` 73%, observation HUD/entity ~75–76%, `metrics/risk.py` 77%. Combined still ≥85%.

### Desktop

| Gate | Result |
|---|---|
| typecheck | PASS |
| lint | PASS |
| vitest | **90 passed** (16 files) |
| electron-vite build | PASS |
| Playwright | **4 passed** (`add-gameplay`, `review-fixture`, sidecar status ×2) |

---

## 12. RF-10 — Security / log redaction

**Verdict: PASS**

Scanned without printing secret values:

- CLI stdout/stderr for the real `--no-llm` run
- RF-1/RF-2 JSON logs (`riot_get` URLs only; `cache_hit=true`)
- Persisted review `01M06GVG21399Y34RQ3YSWN96A.json`
- H.12-ROFL evidence JSON under `docs/architecture/`
- Unit test `test_riot_key_never_appears_in_structlog_output` still present

No `RGAPI-…` key material, no `RIFTLENS_RIOT_API_KEY` value, no provider tokens in those artifacts. Settings for the real run had **no API key present** (cache/DB sufficient). Structlog redactor remains in the processor chain.

No credential leak found; no security stop-the-line fix required.

---

## 13. RF-11 — Review quality / friend test

**Verdict: BLOCKED_INSUFFICIENT_REAL_REVIEWS**

Genuinely distinct **real ROFL-backed** reviews available on this machine after this run: **1** (`NA1_5620410094` pid 6 Vladimir).

Local DBs also contain many **fixture A/B/C** reviews. Those are not counted. Older `~/.riftlens-integrate-ui-r1` has the **same** match/pid once — not a second distinct review. Do not duplicate one review ten times.

### Rubric (use for each distinct review)

| # | Question | Scale |
|---|---|---|
| 1 | Coaching item understandable? | Y / N / mixed |
| 2 | Evidence specific (time, fact labels, not vibe)? | Y / N / mixed |
| 3 | Recommendation actionable next game? | Y / N / mixed |
| 4 | Certainty appropriate (inferred vs fact disclosed)? | Y / N / mixed |
| 5 | Timestamp / replay action useful? | Y / N |
| 6 | Obvious duplicate / redundant advice? | Y / N |
| 7 | Obvious false statement? | Y / N |
| 8 | Would show this to a friend? | Y / N / not yet |

### ENGINEERING REVIEW (1 of 1) — not friend acceptance

Review `01M06GVG21399Y34RQ3YSWN96A`, Vladimir TOP, WIN, ~41 min, null LLM templates.

| Item | 1 | 2 | 3 | 4 | 5 | 6 | 7 | 8 |
|---|---|---|---|---|---|---|---|---|
| Stop dying to an unseen jungler | Y | Y (24:28, unseen ~70s, 61% jungler damage) | Y | mixed (inferred info-age disclosed) | Y (seek 0 ms) | mixed vs fogged fights | N | engineering: useful |
| Do not start fogged fights | Y | Y (24:06, 5 unaccounted) | Y | mixed (conf ~0.41) | Y | mixed overlap | N | mixed |
| Spend tempo after a won fight | Y | Y (28:07, 4-kill, no convert) | Y | Y | Y | N | N | Y |
| Show up for objectives | Y | Y (7:07 earth dragon, interpolated distance) | Y | Y (interpolation disclosed) | Y | N | N | Y |
| Roam only with lane priority | Y | Y | Y | mixed | Y | N | N | mixed |
| Keep your clean early lane | Y | Y | Y (keep doing) | Y | Y | N | N | Y |

**USER/FRIEND ACCEPTANCE:** not performed. Needs a human reading **10** distinct real reviews. Engineering cannot close this gate.

---

## 14. Second-replay result

**Verdict: BLOCKED** — second independent `.rofl` **not present** on this Mac.

Inventory: only `NA1-5620410094.rofl` under Documents League Replays. **`NA1_5617764200` is not on this machine.** Not fabricated.

Historical Windows T4 on `NA1_5617764200` (older HEAD) may be cited as **historical only**. Current Windows real-replay acceptance is **unverified**.

---

## 15. CLI result

**Verdict: PASS** (after smallest production fix)

Before this work order, `riftlens.cli review` without `--vod` always loaded `tests/fixtures/riot/<match_id>/` and failed for a real cached match.

Fix: `--vod` remains optional TIER 2; fixture folders remain the developer path; a non-fixture `match_id` runs H.11 `JobRunner` with `media_asset_id=None`. `--no-llm` forces `provider=null`. Missing `--fixtures` folder errors tell the operator to omit `--fixtures` for a real cached match.

Validated:

```text
python -m riftlens.cli review NA1_5620410094 --pid 6 --no-llm
→ COMPLETED, review_id=01M06GVG21399Y34RQ3YSWN96A, ingest_video/synchronize skipped
```

No VIDEO argument required. No developer-only fixture path required for the real match. No second CLI built.

---

## 16. Platform matrix

| Platform | What is actually true after H.12-ROFL |
|---|---|
| **macOS** | Current HEAD: RF-1 import/identity, RF-2 analysis, RF-3 READY+ClockMap, RF-4 seeks (0 ms), RF-6 covered 3 s CLIP, CLI `--no-llm`, engineering gates. Overlay **contracts** tested; **live overlay visual not observed**. One real `.rofl`. |
| **Windows** | Automated T0–T2 (pytest fakes, Playwright not Windows-specific). Historical T4: R.9 desktop + R.10.5 overlay on `NA1_5617764200` (older HEAD). **Current HEAD real Windows rerun: not done.** Do not generalize Mac T4 to Windows. |
| **Linux** | Native replay **unsupported** (`UnsupportedReplayHost`). Analysis-only possible. Not a Phase 1 native Open Replay claim. |

---

## 17. VIDEO deferred status

Unchanged, still true, **not** satisfied by ROFL:

| Verdict | Value |
|---|---|
| **H9_1_REAL_CORPUS** | **PARTIAL** |
| **H10_REAL_VOD_ACCEPTANCE** | **BLOCKED_INSUFFICIENT_CORPUS** |
| **H12_VIDEO_READINESS** | **BLOCKED** |

VIDEO remains experimental. **H.12-ROFL PASS must not imply VIDEO production readiness.** Replay API ClockMap, R.10 `.webm`, and MacReplayHost do not satisfy H.9.1/H.10.

---

## 18. Bugs discovered / fixed

| Bug | Root cause | Fix | Regression |
|---|---|---|---|
| Real `review <match_id>` required `--vod` or a fixture folder | CLI always called `_load_fixture_pair` | Route non-fixture ids through H.11 with no media | `test_cli_review_real_match_without_vod_uses_null_job_runner` |
| Cached H.11 rerun `IntegrityError` on `finding.id` | Persist `add`s cached finding ULIDs; coaching/metrics already `replace_for_review` | Finding `replace_for_review` after clearing coaching links | `test_cached_rerun_persist_is_idempotent` |
| Open Replay `PLAYBACK_NOT_ADVANCING` at end of match (`t≈length`) | READY required time to increase; finished replay cannot | Rewind ~5 s from end, then re-sample; mid-timeline freeze still fails | `test_playback_at_end_rewinds_then_ready` |

No feature expansion.

---

## 19. Limitations

- One real `.rofl` / one real review on this Mac.
- Overlay live visual not observed.
- Friend-test N=10 not possible.
- Windows current-HEAD T4 not rerun.
- Cold League launch time not measured (attached session).
- Fourth seek post-land 404; capture 8 s truncated (3 s covered).
- Failed-capture rows still drop duration details after partial cleanup (pre-existing); 3 s COMPLETE manifest has coverage.
- `status_for_match` has no `replay_connected` field name; used `session_reached_ready` + PLAYING.
- Coverage JSON measured with pytest-cov; one timing test is invalid under instrumentation.

---

## 20. All RF verdicts

| Gate | Verdict |
|---|---|
| RF-1 | **PASS** |
| RF-2 | **PASS** |
| RF-3 | **PASS** |
| RF-4 | **PASS** |
| RF-5 | **BLOCKED** (manual overlay observation required) |
| RF-6 | **PASS** |
| RF-7 | **PASS** |
| RF-8 | **PASS** |
| RF-9 | **PASS** |
| RF-10 | **PASS** |
| RF-11 | **BLOCKED_INSUFFICIENT_REAL_REVIEWS** (n=1) |
| Second ROFL | **BLOCKED** (file absent) |
| CLI | **PASS** |

---

## 21. H12_ROFL_ENGINEERING

**PASS**

Sidecar pytest, 89.11% domain+analysis coverage, ruff, mypy --strict, import-linter, desktop typecheck/lint/vitest/build/Playwright, labelled precision 1.0, null-LLM CLI, persist/open bugs fixed with tests.

---

## 22. H12_ROFL_REAL_ACCEPTANCE

**PARTIAL**

Mac TIER 1 path on `NA1_5620410094` is real: import, analysis, READY, ClockMap, seeks, covered capture. Blocked on live overlay observation, 10-review friend-test, and a second independent `.rofl`.

---

## 23. PHASE1_ROFL_RELEASE_READINESS

**PARTIAL**

Not READY. Engineering is green; release still needs human overlay confirmation, more distinct real reviews (RF-11), and preferably a second real replay (and a current Windows T4 if Windows is a claimed demo platform).

---

## 24. Exact remaining blockers

1. **RF-5 live overlay** — operator must run the §7 manual checklist on Windowed/Borderless `NA1_5620410094`.
2. **RF-11** — only **1** distinct real review; need 10 genuinely distinct real (prefer ROFL-backed) reviews + friend judgment.
3. **Second independent `.rofl`** — not on this Mac; `NA1_5617764200` absent.
4. **Windows current-HEAD T4** — historical only until rerun.
5. **VIDEO** — remains PARTIAL / BLOCKED_INSUFFICIENT_CORPUS / experimental (non-blocking for ROFL-first, still debt).

---

## 25. Recommended next action after H.12-ROFL

Stop. Do **not** start R.12, V.7, VIDEO harvest, new rules, overlay features, ReplayHost features, or Phase 2.

When the operator continues:

1. Perform the RF-5 overlay checklist on this Mac (highest remaining product-surface gap).
2. Import/analyze additional **real** matches as `.rofl` files appear; fill RF-11 without fabricating.
3. If a Windows machine is available, rerun T4 on this HEAD (`NA1_5617764200` or another real replay).
4. Keep VIDEO experimental until a real VOD corpus exists.

---

## Appendix — VIDEO status (repeat)

```text
H9_1_REAL_CORPUS = PARTIAL
H10_REAL_VOD_ACCEPTANCE = BLOCKED_INSUFFICIENT_CORPUS
H12_VIDEO_READINESS = BLOCKED
```
