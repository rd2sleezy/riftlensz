# H.12-ROFL — Phase 1 ROFL-First Definition of Done

**Date:** 2026-08-16 (engineering + real-replay gates); **RF-5 manual T4 updated 2026-08-19**; **second-ROFL ingest fix 2026-08-19**; **third-ROFL Open Replay fix 2026-08-19**  
**Branch:** `integrate/ui-r1`  
**Does not implement:** R.12, V.7, VIDEO corpus harvesting, new visual research, new coaching rules, new product architecture, remote replay hosting, Phase 2, camera-attachment changes.

This work order is validation / hardening on current HEAD. Historical VIDEO verdicts are not reinterpreted. The 2026-08-19 update is documentation / acceptance only.

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
- H.12-ROFL engineering + real-replay evidence commit: **`9574475`** (CLI no-VIDEO path, idempotent persist, end-of-replay READY recovery). Automated RF evidence was produced on that tree, not on `95b2b51` alone.
- RF-5 user-observed overlay acceptance (this update): performed **2026-08-19** against current-HEAD product on `integrate/ui-r1` at **`9574475`** (no production-code change in the docs-only follow-up).

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

**Verdict: PASS**

**Evidence class: USER-OBSERVED / MANUAL T4.** This is not automated visual verification. No agent, screenshot pipeline, or pixel test observed the overlay over League. The 2026-08-16 engineering run left RF-5 BLOCKED because Electron overlay was not launched in that session. The operator closed that gap on **2026-08-19** on current HEAD **`9574475`**.

### Engineering (automated, current HEAD) — PASS (unchanged)

- `inputPolicy.test.ts`: no Electron `globalShortcut` in overlay modules; no process injection / Replay API from overlay code.
- `macOverlay.contract.test.ts`: prev/next/seek/minimize/expand **without Escape or Space**; live-game refuse; Spaces/fullscreen documented, not auto-switched.
- `hotkeys.ts`: Escape and bare Space unclaimed.
- `displayModeAssist.ts`: exclusive fullscreen / separate macOS Space cannot keep an always-on-top companion; Borderless/Windowed is the supported path; no `game.cfg` WindowMode write, no Alt+Enter, no injection.
- Overlay vitest suite included in 90 passing desktop tests.

### USER-OBSERVED / MANUAL T4 (2026-08-19, HEAD `9574475`) — PASS

Real RiftLens replay/review flow on macOS, current HEAD. Operator observations:

- Real League replay opened successfully.
- RiftLens overlay appeared **visibly over** the League replay.
- Overlay was **not** trapped behind League.
- Access Overlay returned/preserved the expected League experience rather than leaving the user stranded in the RiftLens main window.
- Overlay was usable during the replay.
- Overlay controls behaved correctly.
- Previous/next coaching navigation worked.
- Coaching seek worked.
- Overall overlay behavior looked correct to the user.

**Fullscreen limitation (honest, unchanged):** overlay is not claimed over a separate macOS fullscreen Space or Windows exclusive D3D fullscreen. Player path is Borderless/Windowed + Recheck.

### Deferred (non-blocking): subject camera lock on coaching seek

**Not a Phase 1 blocker. Do not fix in this work order. Do not start V.7. Do not change ReplayHost or camera-attachment code.**

During the same manual session, jumping to coaching timestamps did **not** necessarily lock the replay camera onto the reviewed subject (Vladimir, pid 6). The replay may frame/pan around the broader event (for example the full team fight) rather than remaining specifically attached to Vladimir.

Current behavior remains **acceptable** for Phase 1 because:

- seek timing is correct (RF-4 landing ≤1000 ms; operator also saw seek work from overlay);
- the relevant event is visible;
- coaching evidence remains inspectable;
- native replay synchronization is functioning.

Recorded as **deferred improvement after planned H.x / R.x work is complete**. Future work (not now) may use prior camera-attachment spike research:

- champion-name attachment can visually follow Vladimir;
- Replay API exposes **no** authoritative participant/entity id;
- `selectionName` may clear during playback while attachment remains;
- seek **clears** camera attachment;
- therefore a future subject-focused replay path likely needs a deliberate **`seek → attach/reacquire`** lifecycle;
- that work must stay separate from visual identity claims / `CONTROLLED_SUBJECT` semantics unless independently justified.

This note is **not** a V.7 work order and is **not** a change to current camera behavior.

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
| E. Overlay access | if measurable | **not instrumented** (no wall-clock) | RF-5 closed by **USER-OBSERVED / MANUAL T4** 2026-08-19; not an automated pixel measurement |
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

**Verdict: PARTIAL — production ingest bug fixed; real second-match acceptance not yet re-run on fixed HEAD**

Second independent `.rofl` now present on this Mac:

| Field | Value |
|---|---|
| File | `/Users/rylanddunn/Documents/League of Legends/Replays/NA1-5624772791.rofl` (7 585 597 bytes) |
| Identity | `NA1_5624772791` (filename `NA1-5624772791.rofl` → underscore form) |
| Pre-fix DB | **Absent** from `~/.riftlens/riftlens.db` `match` table (only `NA1_5620410094` + fixtures) |

### Reproduced failure (pre-fix)

Import League Replay wizard correctly identified `NA1_5624772791`, reported **match not in RiftLens yet**, and showed **Ingest this match**. Clicking the button **looped** to the same state without persisting the match or opening the participant picker.

### Root cause (diagnosed)

1. **UI:** `ImportReplayWizard` treated `ingest_match` like `open_replay_match` — it re-ran `openReplayMatchFlow` instead of calling `window.rift.ingestMatch` → `POST /matches/ingest`. No explicit ingest IPC on button click.
2. **Error mapping:** Riot HTTP **403 Forbidden** (typical expired 24 h dev key) was mapped to **`MATCH_NOT_INGESTED`**, so the UI showed “match not in RiftLens yet” and offered **Ingest this match** again — an infinite misleading loop even when `listMatchParticipants` attempted fetch.
3. **Why `NA1_5620410094` worked:** that match was already persisted locally from an earlier successful ingest; `import_rofl` only checks the DB and does not call Riot. The second match is genuinely uncached.

`POST /matches/ingest` was **not** invoked on **Ingest this match** before the fix. Match-id normalization (`NA1-5624772791.rofl` → `NA1_5624772791`) was already correct.

### Fix (smallest production diff)

- Wizard: `runIngestMatch()` calls `ingestMatch` IPC, then continues participant/review flow; initial `MATCH_NOT_INGESTED` stops at failed step with honest ingest button (no silent auto-loop).
- Sidecar: `_replay_error_from_riot_exc` maps **Forbidden → `RIOT_CREDENTIAL_MISSING`** (sign-in action), **NotFound / RateLimited / 5xx** → honest messages (not generic ingest loop).
- Regression: `test_real_match_ingest_errors.py`, `importReplayWizard.test.ts`.

### Post-fix real acceptance (2026-08-19, HEAD `ee2c898`)

**Import / ingest / review: PASS.** Operator refreshed Riot access, imported `NA1-5624772791.rofl`, ingested the uncached match, selected participant, and reached a persisted real review.

| Field | Value |
|---|---|
| Review id | `01M0EHDEJ62VBMQY6TSVVW12PR` |
| ROFL source id | `01M0EHDEXRRA122NS1KKP9Q23V` (`linked`) |
| Participant | **6** — Vladimir TOP |
| Riot identity | **immynator#loler** (same account as first match) |
| Result | **WIN** · ~17 min (`duration_ms` 1 025 114) |
| KDA | 6 / 1 / 0 |

**Coaching composition (diagnosed, not a bug):**

| Stage | Count |
|---|---|
| Raw rule findings | **1** (P-001 strength only) |
| Improvement findings (R-001…R-020) | **0** |
| Focus / “coaching plan” items | **0** |
| Secondary items | **0** |
| Strengths | **1** (“Clean lane phase”) |

Re-running the production pipeline on cached MATCH-V5 + timeline reproduces the persisted JSON exactly: GST **2 178** facts, **23** `CHAMPION_KILL` events, **17** metrics computed, **25** rules in pack, **0** improvement rules triggered. UI renders `focus_items.length === 0` with the existing empty-state copy — not a rendering bug.

**Why zero improvements (primary diagnosis: `ZERO_FINDINGS_CORRECT`):**

- Dominant lane win: CS diff **+33** at 14:00 vs Garen, **1** death before 14:00 → **P-001** fires as a strength.
- Sole death at **5:30** (`t_ms=330 407`) to **Garen (TOP lane opponent)**, not an unseen jungler → **R-001** correctly does not fire.
- Shorter stomp (~17 min vs ~41 min on first match) → fewer macro/tempo/objective windows; **R-008 / R-014 / R-017 / R-012** did not trigger (same as first-match structural comparison).
- **R-002** logged `rule_inputs_unsatisfied` for `unspent_gold_estimate` on this death — inputs missing, not a silent failure.

**Open Replay / seek gate:** not exercised here — no legitimate coaching timestamps to seek. Do not invent a seek.

**Second ROFL verdict:** **PARTIAL** — fresh import + real review + ROFL link **PASS**; replay READY/seek **not applicable** (no improvement items).

**RF-11:** this counts as a **second distinct real review** → **n=2** (still **BLOCKED**, need 10).

Historical Windows T4 on `NA1_5617764200` (older HEAD) remains **historical only**.

---

## 14b. Third-replay result

**Verdict: PASS — real third-match import/review/Open Replay/seek on fixed HEAD**

Third independent `.rofl` on this Mac:

| Field | Value |
|---|---|
| File | `/Users/rylanddunn/Documents/League of Legends/Replays/NA1-5624560795.rofl` |
| Identity | `NA1_5624560795` |
| Review id | `01M0EJ5B4KZ8X8414391996QCV` |
| ROFL source id | `01M0EJ5BK3FTDVSNCFC66732M9` (`linked`) |
| Participant | **6** — Vladimir |
| Duration | ~30 min (`game_duration_ms` 1 813 000) |
| Focus / Areas of Improvement | **3** |

### Reproduced failure (pre-fix)

Operator imported, ingested, selected participant, and persisted a real review with **3** legitimate coaching items. **Open Replay** failed immediately with **“Replay API is not enabled in the game client”** (`REPLAY_API_DISABLED`).

### Root cause (diagnosed)

1. League had **removed** `Game/Config/` since the prior successful Mac session (`NA1_5620410094`). Only `LoL/Config/game.cfg` retained `EnableReplayApi=1`.
2. `MacReplayHost.check_environment()` correctly warned `REPLAY_API_DISABLED` (`reason=game_cfg_missing`).
3. **Bug:** `MacReplayHost.open_session()` returned **FAILED before launch** when the warning was present and the swagger probe was unreachable (`not env.replay_api_documented`). **`enable_mac_replay_api` was never called** on Open Replay — only via the separate enable IPC/button.
4. Windows `open_session` does not have this pre-launch gate; Mac regressed the previously proven lifecycle (create `Game/Config`, seed from `LoL/Config`, launch with `GameBaseDir=<Game>`).

This is **not** an H.12 fresh-match regression; it is a **Mac Open Replay lifecycle** issue present since the early-fail guard was added.

### Fix (smallest production diff)

- `MacReplayHost.open_session`: when `REPLAY_API_DISABLED` is detected, **auto-call** `enable_mac_replay_api(consent=True)` (Open Replay implies consent) to create/seed `Game/Config/game.cfg`, then proceed to supervisor launch like Windows.
- Remove the pre-launch early return that blocked launch when swagger was not yet reachable.

Regression: `test_mac_host_open_auto_enables_missing_game_config`, `test_mac_host_open_auto_enables_flag_missing`.

### Post-fix real acceptance (2026-08-19, HEAD pending commit)

**Open Replay: PASS** on real `NA1_5624560795` without manual `game.cfg` edits and without calling enable IPC first.

| Check | Result |
|---|---|
| `Game/Config` before open | **missing** |
| `enable_mac_replay_api` before open | **not called** |
| Install | `/Applications/League of Legends.app` → `Contents/LoL/Game` |
| `game.cfg` after open | created at `Game/Config/game.cfg`, `EnableReplayApi=1` |
| Launch | direct exe, `GameBaseDir=<Game>` |
| Session | **PLAYING** (READY), Replay API connected |
| ClockMap | native **OFFSET** (`offset_ms=-6546`, `verified=false`, **no SyncMap**) |
| Overlay | **not re-tested** this run (non-blocking) |

**Three coaching seeks** (lead-in 8000 ms; tolerance per `REAL_SEEK_TOLERANCE_MS`):

| # | Focus title | Rule | Finding | Expected `t_ms` | Seek target (source) | Landed clock | Δ vs target | Δ vs expected |
|---|---|---|---|---|---|---|---|---|
| 1 | Base when low with a gold pile | R-007 | `01M0EJ5AZKTH7WF8R85TBPDEB9` | 600 000 | 598 546 | 598 546 | **0** | −1454 |
| 2 | Respect dive angles under tower | R-015 | `01M0EJ5B23KX0ESPR1VDXDT7J8` | 1 438 382 | 1 436 928 | 1 436 928 | **0** | −1454 |
| 3 | Roam only with lane priority | R-018 | `01M0EJ5B0VD19R8MXBZ9NBJYD1` | 1 020 000 | 1 018 546 | 1 018 546 | **0** | −1454 |

All three seeks **ok=true**. Uniform −1454 ms vs game `t_ms` matches calibrated OFFSET + lead-in mapping (landed exactly on computed target; no silent compensation).

**Third ROFL verdict:** **PASS** — import, real review (3 improvements), ROFL link, Open Replay READY, native ClockMap, three legitimate seeks.

**RF-11:** third distinct real review → **n=3** (still **BLOCKED**, need 10).

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
| **macOS** | Current HEAD (`9574475`): RF-1 import/identity, RF-2 analysis, RF-3 READY+ClockMap, RF-4 seeks (0 ms), RF-6 covered 3 s CLIP, CLI `--no-llm`, engineering gates. Overlay **contracts** tested; **RF-5 live overlay = PASS** via USER-OBSERVED / MANUAL T4 (2026-08-19). One real `.rofl`. |
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
| Second `.rofl` ingest loop (`NA1_5624772791`) | Ingest button never called `ingestMatch` IPC; Riot 403 mapped to `MATCH_NOT_INGESTED` | Wizard `runIngestMatch` + honest Riot error mapping in `_fetch_pair` | `test_real_match_ingest_errors.py`, `importReplayWizard.test.ts` |
| Third `.rofl` Open Replay `REPLAY_API_DISABLED` (`NA1_5624560795`) | Mac `open_session` failed before launch when `Game/Config` missing and swagger unreachable; `enable_mac_replay_api` not invoked on Open Replay | Auto-enable `Game/Config` in `MacReplayHost.open_session` when disabled, then launch | `test_mac_host_open_auto_enables_missing_game_config`, `test_mac_host_open_auto_enables_flag_missing` |

No feature expansion.

---

## 19. Limitations

- Three real ROFL-backed reviews on this Mac (`NA1_5620410094`, `NA1_5624772791`, `NA1_5624560795`); second has **zero** improvement items by correct rule outcome; third validates Open Replay auto-enable when League drops `Game/Config`.
- Overlay live pixels were **user-observed**, not automated.
- Coaching seeks do not lock the camera to the reviewed subject (deferred, non-blocking).
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
| RF-5 | **PASS** (USER-OBSERVED / MANUAL T4, 2026-08-19, HEAD `9574475`) |
| RF-6 | **PASS** |
| RF-7 | **PASS** |
| RF-8 | **PASS** |
| RF-9 | **PASS** |
| RF-10 | **PASS** |
| RF-11 | **BLOCKED_INSUFFICIENT_REAL_REVIEWS** (n=3) |
| Second ROFL | **PARTIAL** (import/review/ROFL link PASS; replay seek N/A — zero improvement items) |
| Third ROFL | **PASS** (import/review/3 improvements/Open Replay READY/three seeks; overlay not re-tested) |
| CLI | **PASS** |

---

## 21. H12_ROFL_ENGINEERING

**PASS**

Sidecar pytest, 89.11% domain+analysis coverage, ruff, mypy --strict, import-linter, desktop typecheck/lint/vitest/build/Playwright, labelled precision 1.0, null-LLM CLI, persist/open bugs fixed with tests.

---

## 22. H12_ROFL_REAL_ACCEPTANCE

**PARTIAL**

Mac TIER 1 path on `NA1_5620410094` and **`NA1_5624560795`** is real: import, analysis, READY, ClockMap, seeks, covered capture (first match), and **user-observed overlay** (first match). Still blocked on the 10-review friend-test (RF-11). Overlay PASS does **not** force Phase 1 READY.

---

## 23. PHASE1_ROFL_RELEASE_READINESS

**PARTIAL**

Not READY. Engineering is green and RF-5 is closed by manual T4. Release still needs more distinct real reviews (RF-11) and a second independent `.rofl` (and a current Windows T4 if Windows is a claimed demo platform). Do not treat overlay PASS as VIDEO readiness or as a 10-review friend-test.

---

## 24. Exact remaining blockers

1. **RF-11** — only **3** distinct real reviews; need 10 genuinely distinct real (prefer ROFL-backed) reviews + friend judgment. **BLOCKED_INSUFFICIENT_REAL_REVIEWS**.
2. **Second independent `.rofl` with improvement seeks** — `NA1_5624772791` has zero focus items (correct); third match now covers multi-seek Open Replay. Still need breadth across more distinct games.
3. **Windows current-HEAD T4** — historical only until rerun (do not generalize Mac overlay T4 to Windows).
4. **VIDEO** — remains PARTIAL / BLOCKED_INSUFFICIENT_CORPUS / experimental (non-blocking for ROFL-first, still debt).

RF-5 is **no longer** a Phase 1 blocker. Subject-camera-lock on seek is **deferred and non-blocking** (see §7).

---

## 25. Recommended next action after H.12-ROFL

Stop. Do **not** start R.12, V.7, VIDEO harvest, new rules, overlay features, ReplayHost features, or Phase 2.

When the operator continues:

1. Import/analyze additional **real** matches as `.rofl` files appear; fill RF-11 without fabricating.
2. If a second independent `.rofl` appears locally, run the reduced second-case acceptance (identity, analysis, Open Replay, READY, ClockMap, one seek).
3. If a Windows machine is available, rerun T4 on this HEAD (`NA1_5617764200` or another real replay).
4. Keep VIDEO experimental until a real VOD corpus exists.
5. Subject-camera-lock (`seek → attach/reacquire`) only **after** planned H.x / R.x work — not V.7, not now.

---

## Appendix — VIDEO status (repeat)

```text
H9_1_REAL_CORPUS = PARTIAL
H10_REAL_VOD_ACCEPTANCE = BLOCKED_INSUFFICIENT_CORPUS
H12_VIDEO_READINESS = BLOCKED
```
