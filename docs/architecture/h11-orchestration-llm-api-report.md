# H.11 — Orchestration, Evidence-Grounded Narration, and Phase 1 API

**Date:** 2026-08-16  
**Branch:** `integrate/ui-r1`  
**Does not implement:** H.12, R.12, V.7, baseline-corpus harvesting, real-VOD Definition of Done, new visual detectors, new coaching rules, remote replay hosting.

Companion to the H.11 readiness report. Wraps existing H.2–H.10 analysis. The LLM never selects, ranks, or invents findings.

---

## 1. Architecture implemented

```
POST /jobs/analyze
        ↓
JobService (dedicated thread + event loop)
        ↓
JobRunner DAG
  ingest_riot  ∥  ingest_video (VIDEO only)
        ↓
  synchronize (VIDEO + media only; skipped for ROFL / no-media)
        ↓
  build_facts → compute_metrics → run_rules → prioritize
        ↓
  compose_coaching (EvidenceBundle → provider → validator → prose or template)
        ↓
  persist (existing H.8 Review + presentation JSON)
        ↓
GET /jobs/{id}  |  GET /jobs/{id}/stream (SSE)  |  GET /diagnostics/last-job
```

Deterministic H.2–H.8 remains authoritative. `compose_coaching` rewrites already-selected `CoachingItem` bodies from H.8 `EvidenceBundle` only.

`JobService` runs on a dedicated thread so FastAPI request cancellation cannot leave jobs `RUNNING`. Crash restart marks leftover `RUNNING` rows `FAILED` via `SqlJobRepository.fail_running_sync`.

---

## 2. DAG

Logical order (`STAGE_ORDER`):

```
ingest_riot ──────────────┐
                          ↓
optional ingest_video → optional synchronize
                          ↓
                    build_facts
                          ↓
                  compute_metrics
                          ↓
                     run_rules
                          ↓
                    prioritize
                          ↓
                 compose_coaching
                          ↓
                       persist
```

When `media_asset_id` is set, `ingest_riot` and `ingest_video` run concurrently (`asyncio.gather`). When it is absent, `ingest_video` and `synchronize` are skipped (zero-duration timings, `skipped=true`). A job without VIDEO still completes a full Review from Riot/GST.

---

## 3. Stage definitions / versions

All stages start at version `"1"` (`DEFAULT_STAGE_VERSIONS`). Each is a thin wrapper around an existing implementation.

| Stage | Version | Cacheable | Wraps |
|---|---|---|---|
| `ingest_riot` | 1 | yes | fixtures or H.2 `ensure_match_ingested` |
| `ingest_video` | 1 | yes | H.9 media probe; skipped for ROFL / no media |
| `synchronize` | 1 | yes | H.10 `AutoSyncService` (VIDEO only) |
| `build_facts` | 1 | yes* | H.2 `build_game_state_timeline` |
| `compute_metrics` | 1 | yes | H.5 `compute_metrics` |
| `run_rules` | 1 | yes | H.6/H.7 `RuleEngine` + production pack |
| `prioritize` | 1 | yes | H.8 cluster / score / prioritize / items |
| `compose_coaching` | 1 | yes | H.8 EvidenceBundle + composer/validator |
| `persist` | 1 | **no** | existing `persist_review_async` |

\* GST is not pickled. Cache stores fact counts; restore rebuilds GST from cached match+timeline DTOs.

Upstream versions are mixed into each stage cache key transitively, so bumping `run_rules` invalidates `run_rules` and every downstream stage while leaving ingest/facts/metrics reusable.

---

## 4. Cache design

Filesystem pickle cache under `{cache_dir}/stages/`.

Key: `sha256(stage.name + stage.version + canonical_json(input_refs))`.

`input_refs` is JSON-canonical (sorted keys, no Python object identity). It includes:

- declared input hashes (`match_hash`, `timeline_hash`, `media_hash`, …)
- `match_id`, `participant_id`
- `_upstream_versions` (transitive dependency versions)

`compose_coaching` also mixes `llm_provider`, `llm_model`, and `PROMPT_VERSION`.

`MappingProxyType` values are converted to dicts before pickle. Cache get treats unpickle errors as a miss. Invalid LLM text is never written to the LLM cache.

`POST /reviews/{id}/sync` invalidates `DOWNSTREAM_FROM_SYNC` (synchronize onward) after wrapping H.10 `build_manual_sync`.

---

## 5. Cancellation design

`DELETE /jobs/{id}` sets a thread-safe `CancellationToken`.

Checked:

- at the start of every stage (`current_stage` is set first)
- inside `StageContext.tick` (including ~5% progress increments)
- during `ingest_video` cooperative hold (`ingest_video_hold_ms`, 50 ms sleep)
- in `CancellablePool.run` (spawned process; `terminate`/`kill` on cancel)

Queued jobs become `CANCELLED` immediately. Running jobs become `CANCELLED` with `failure_stage` = current stage. Jobs are not left `RUNNING`.

---

## 6. Progress / SSE

`ProgressEvent`: `job_id`, `stage`, `pct`, `message`, `ts`, `status`.

`ProgressBus` is thread-safe. History is replayed on subscribe so reconnects see current state. Disconnected queues are dropped; emit never raises into the job.

`GET /jobs/{id}/stream` is Server-Sent Events (`text/event-stream`). The iterator stops on a terminal `COMPLETED` / `FAILED` / `CANCELLED` event. No WebSocket.

Within a stage, `pct` is monotonic. Overall percent is derived from stage index × within-stage percent.

---

## 7. Persistence

Alembic `0004_h11_jobs` revises `0003_capture`. Table `analysis_job` stores status, inputs JSON (no API keys), timings, cache counters, LLM metadata, fact/finding counts, and optional VIDEO sync quality JSON.

`SqlJobRepository.upsert_sync` writes after create, cancel, and job completion. `fail_running_sync` on `JobService` start converts orphan `RUNNING` rows to `FAILED`.

Reviews still persist through the existing H.8 path (`review`, `finding`, `metric_value`, `coaching_item`, presentation JSON). Finding feedback uses the existing `finding_feedback` model and does not mutate evidence.

---

## 8. Diagnostics

`GET /diagnostics/last-job` returns the public job snapshot plus:

- `wall_ms` (started → completed)
- `stage_timing_sum_ms` (non-skipped stage durations)
- cache hits/misses
- fact/finding counts
- `sync_quality` when VIDEO sync ran
- `llm_provider` / `llm_model` / `llm_fallback`

No API keys, tokens, or prompts.

---

## 9. EvidenceBundle → narration flow

```
H.8 prioritize
  → Review + CoachingItems (deterministic)
  → bundle_review / bundle_item (existing EvidenceBundle)
  → provider.complete(prompt + bundle JSON)
  → mechanical validator
  → accepted prose  OR  one repair  OR  template fallback
```

The LLM does not see video, screenshots, raw Riot JSON, GST internals beyond the bundle, or the database. It does not select or rank findings. Certainty language is enforced in the validator/composer, not trusted to the model.

Prompts: `riftlens/resources/prompts/finding_v1.md`, `summary_v1.md` (`PROMPT_VERSION = "v1"`).

---

## 10. Provider architecture

Shared `LLMProvider` protocol (`name`, `model`, `complete`). Factory `create_provider` is the only name switch.

| Provider | Module | Runtime |
|---|---|---|
| `null` | `providers/null.py` | mandatory default; echoes template; no network |
| `openai` | `providers/openai.py` | httpx; missing key → `ProviderUnavailable` |
| `anthropic` | `providers/anthropic.py` | httpx; missing key → `ProviderUnavailable` |
| `ollama` | `providers/ollama.py` | httpx to local URL |
| unknown | factory | `NullProvider` |

No paid SDKs. Pipeline code does not branch on provider name. Provider failures are recoverable (template fallback).

---

## 11. Null / offline behavior

Default `Settings.llm_provider = "null"`. CLI `--no-llm` forces `null`. `LLM_PROVIDER=null` (env `RIFTLENS_LLM_PROVIDER`) is the same path.

Null `complete()` returns `fallback_text` (the deterministic template). Every coaching explanation remains non-empty. No network, no API key.

---

## 12. Validator rules

`validate_narration` against `EvidenceBundle.allowed_values` plus match roster names:

- **Numbers:** reject values not within ±2% of an allowed number (comma-stripped). Timestamps are stripped first so `47:12` does not yield extra integers.
- **Timestamps:** only `mm:ss` / `h:mm:ss` tokens present in the bundle.
- **Champion names:** Title-Case tokens must be in allowed names, extra roster, or the stoplist (`You`, `Gold`, `Jungler`, …). Invented names (e.g. Yasuo when absent) fail.
- **Provenance / certainty:** prompts forbid upgrading inferred evidence; validator rejects unsupported structured claims via the token checks above.

---

## 13. Repair / fallback behavior

1. First completion is validated.
2. On failure: exactly one repair call, with the violation description in the prompt.
3. Second validation.
4. If still invalid or `ProviderUnavailable`: deterministic template, `llm_fallback = true`, safe reason recorded. No retry loops.

---

## 14. LLM caching

Accepted narration only: `sha256(bundle JSON + prompt_version + provider.name + model)` under `{cache_dir}/llm/`. Invalid responses are not stored. Null/template path skips validation cache and stays deterministic. Prompt version or model change is a miss.

---

## 15. API surface

| Method | Path | Notes |
|---|---|---|
| POST | `/jobs/analyze` | `{match_id, participant_id, media_asset_id?}` → `{job_id}` |
| GET | `/jobs/{id}` | snapshot |
| GET | `/jobs/{id}/stream` | SSE |
| DELETE | `/jobs/{id}` | cancel |
| POST | `/accounts/link` | H.2 Riot client; desktop remains credential owner |
| GET | `/accounts/{puuid}/matches?count=20` | H.2 match ids |
| POST | `/media/import` | VIDEO probe/hash |
| POST | `/media/match-candidates` | VIDEO duration ranking; not ROFL identity |
| GET | `/reviews` | existing list |
| GET | `/reviews/{id}` | existing |
| GET | `/reviews/{id}/series?kinds=&stride=` | GST series, deterministic stride |
| POST | `/reviews/{id}/sync` | H.10 `build_manual_sync` + cache invalidate |
| POST | `/findings/{id}/feedback` | `{verdict, note?}`; no evidence mutation |
| GET | `/diagnostics/last-job` | timings / cache / counts |

Typed pydantic request models. API keys accepted on sidecar calls from Electron main only; never stored on jobs; never in renderer payloads.

Existing `/reviews/from-match` is unchanged.

---

## 16. VIDEO / ROFL branching

**VIDEO** (`media_asset_id` set, non-ROFL asset): `ingest_video` probes; `synchronize` may run H.10 auto-sync; diagnostics may include SyncMap quality; Review presentation may include `sync_map`.

**ROFL:** analysis completes without VIDEO. `ingest_video` / `synchronize` skip. No OCR, no League launch, no seek, no capture, no ReplayHost, no overlay. Native ClockMap / MacReplayHost remain outside this job.

**No gameplay source:** Riot/GST review still completes.

Filename heuristics are not applied to native ROFL identity (`match-candidates` is VIDEO-only).

---

## 17. Desktop integration

Thin IPC only. ReviewScreen is unchanged (no second coaching list, no overlay/replay-control changes).

- `startAnalyzeJob` → `POST /jobs/analyze` (API key from main/keychain)
- `getAnalyzeJob` → poll status / stage / percent
- `cancelAnalyzeJob` → `DELETE /jobs/{id}`

`ImportReplayWizard` starts a job when building a participant review, shows stage/progress, and Cancel during a running job requests sidecar cancellation. Zod schemas accept optional `explanation_source` / `llm_*` fields. Analysis logic stays in the sidecar.

---

## 18. AC1 result

FakeProvider returns `You lost 9,999 gold to Yasuo at 47:12`.

- First call rejected (unsupported number, champion, timestamp)
- Repair call occurs exactly once
- Second invalid response → template body, `fallback=true`

**PASS** (`test_ac1_fake_provider_rejected_repair_then_template`, ~0.00 s)

---

## 19. AC2 result

`llm_provider=null` via `POST /jobs/analyze`.

- Job `COMPLETED`
- Review loaded; every coaching `body` non-empty
- No network

**PASS** (`test_ac2_null_provider_full_review`, ~0.83 s)

---

## 20. AC3 result + timing

Bump only `run_rules` version to `"2"` and rerun on the same cache dir.

Reused: `ingest_riot`, `build_facts`, `compute_metrics` (cache hits).  
Rerun: `run_rules`, `prioritize`, `compose_coaching`, `persist`.

Measured cached rerun: **0.606 s** (limit &lt; 10 s).

**PASS** (`test_ac3_run_rules_version_reuses_upstream`; full test including first run ~1.24 s)

---

## 21. AC4 result + timing

Cancel during `ingest_video` (cooperative hold 8 s, missing media id so the stage stays in the hold loop).

Worker reached `CANCELLED` in **&lt; 3 s**. Test call duration **0.44 s**.

**PASS** (`test_ac4_cancel_during_ingest_video`)

---

## 22. AC5 result + timing / error

`GET /diagnostics/last-job`: `stage_timing_sum_ms` vs `wall_ms`.

Standalone fixture job: sum **819 ms**, wall **819 ms**, relative error **0.0** (limit 5%). Test also allows ≤250 ms absolute slack for clock granularity.

**PASS** (`test_ac5_diagnostics_timings`, ~0.82 s)

---

## 23. Full test results

| Gate | Result |
|---|---|
| Sidecar pytest | **718 passed, 8 skipped** |
| ruff | **pass** |
| mypy --strict | **pass** (255 files) |
| import-linter | **12 kept, 0 broken** |
| Desktop typecheck | **pass** |
| Desktop lint | **pass** |
| vitest | **16 files, 90 tests passed** |
| electron-vite build | **pass** |
| Playwright | **not run** (thin IPC/wizard wiring; no new e2e scenario) |
| H.11 AC1–AC5 | **5 passed** |

Import-linter: `riftlens.orchestration` is forbidden from `riftlens.visual` and `riftlens.replay_host`. Transitive use of `riftlens.vision` via H.10 VIDEO `AutoSyncService` is allowed so synchronize can wrap existing OCR sync. Coaching is forbidden from `visual`, `vision`, and `replay_host`. V.0–V.6 observations are not added to EvidenceBundle.

---

## 24. Known limitations

- H.10 real-VOD acceptance remains gated (unchanged). H.9.1 OCR real corpus remains PARTIAL.
- Live OpenAI/Anthropic/Ollama adapters exist but were not exercised against paid or local servers.
- `ingest_video` cancellation within 3 s is proven on the cooperative hold path; a stuck native probe in a spawned process is terminated via `CancellablePool`, but that path was not timed against a real multi-GB VOD.
- SSE reconnect replays in-memory history for the current sidecar process only (not durable across process restart). Job rows remain queryable via `GET /jobs/{id}`.
- Playwright e2e was not added for job progress UI.
- Stage cache is process-local filesystem pickle, not a shared remote cache.

---

## 25. Live providers actually tested

**None.** Null + FakeProvider only. No OpenAI, Anthropic, or Ollama live calls.

---

## 26. H11_ENGINEERING verdict

**PASS**

Critical gates AC1–AC5 passed. Sidecar and desktop engineering gates passed. Deterministic analysis remains authoritative. LLM is not the analyst.

---

## 27. Whether H.12 is now engineering-unblocked

**Engineering-unblocked as a product work order, not started.**

H.11 orchestration, null narration, and Phase 1 API are in place. Do **not** start H.12, R.12, or V.7 from this report.

Independent gates that still apply to later work:

- H.10 real-VOD Definition of Done
- H.9.1 OCR real-corpus completeness
- V-series remains research-isolated (no V.7)

H.12 requires an explicit user start. **Update 2026-08-16:** Phase 1 DoD is
reinterpreted as ROFL-first; VIDEO gates stay deferred. See
[`phase1-rofl-first-acceptance-amendment.md`](./phase1-rofl-first-acceptance-amendment.md).
