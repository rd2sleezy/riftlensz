# C.1 — Coaching Context & Episode Foundation

**Date:** 2026-08-19  
**Branch:** `integrate/ui-r1`  
**Schema:** `c1.0` (`COACHING_EPISODE_SCHEMA_VERSION`)  
**Does not implement:** C.2+ coaching intelligence, H/R/V changes, V.7, R.12, visual consumption, LLM/prompt changes, DB persistence, API/UI/review selection changes.

C.1 adds a deterministic, evidence-preserving **temporal context container** around existing Findings. Player-facing reviews are unchanged.

> Temporal association does not imply causality.

> Condition resolution does not imply that the original decision was correct.

---

## 1. Objective

GST holds the surrounding match sequence. A Finding cites only the evidence needed to fire one rule. C.1 records what else was happening **before**, **at**, and **after** those findings without interpreting mistakes, root causes, or advice.

---

## 2. Architecture

```
existing Finding[] + GameStateTimeline
        ↓
build_coaching_episodes (pure, no I/O)
        ↓
temporal window per finding (pre 60s / post 30s, clamped)
        ↓
merge overlapping/near windows (merge gap 5s) = TEMPORAL_COPRESENCE
        ↓
CoachingEpisode
  FindingRef (ANCHOR | TEMPORALLY_ASSOCIATED)
  FactRef[] (lightweight GST pointers)
  ParticipantStateSample BEFORE / ANCHOR / AFTER
  FightWindowRef[] (segment_fights, DERIVED)
  ContextGap[]
  ConditionResolution[] (fail-closed)
```

Not wired into H.11 `JobRunner`, `cluster_findings`, `prioritize`, EvidenceBundle, composer, persist, API, or UI.

Package: `riftlens.coaching.context` (consumes domain + GST features; domain does not import coaching).

---

## 3. Files changed

**Added**

| Path | Role |
|---|---|
| `riftlens/coaching/context/__init__.py` | Public C.1 API |
| `riftlens/coaching/context/models.py` | Schema, enums, `to_dict`, episode ids |
| `riftlens/coaching/context/grouping.py` | Temporal merge (non-causal) |
| `riftlens/coaching/context/snapshots.py` | BEFORE/ANCHOR/AFTER + ContextGap |
| `riftlens/coaching/context/resolution.py` | Conservative R-006/R-007 resolvers |
| `riftlens/coaching/context/builder.py` | `build_coaching_episodes` |
| `tests/unit/test_coaching_context_c1.py` | Builder / provenance / resolution / isolation |
| `docs/architecture/c1-coaching-context-episode-foundation-report.md` | This report |

**Changed**

| Path | Role |
|---|---|
| `riftlens/coaching/__init__.py` | Re-exports C.1 types (no behavior change) |
| `services/analysis/pyproject.toml` | `c1 coaching context isolation` import-linter contract |

---

## 4. Schema (`c1.0`)

`CoachingEpisode` fields: `id`, `schema_version`, `match_id`, `participant_id`, `start_ms`, `end_ms`, `phase`, `grouping` (`TEMPORAL_COPRESENCE`), `anchor_timestamps_ms`, `findings`, `fact_refs`, `samples`, `fights`, `gaps`, `resolutions`, `provenance`.

No root-cause, recommendation, decision-quality, counterfactual, or priority fields.

Episode ids: `c1e_` + sha256 of canonical `{schema_version, match_id, participant_id, start_ms, end_ms, anchor_finding_ids}`.

Serialization: `CoachingEpisode.to_dict()` for tests/future persistence. **C.1 does not write DB rows or change Review JSON.**

---

## 5. Episode / window / grouping semantics

Context retrieval defaults (not gameplay truth):

- pre-context: 60_000 ms
- post-context: 30_000 ms
- merge gap: 5_000 ms

Window for a finding: `[max(0, t_ms − pre), min(duration, (t_end_ms or t_ms) + post)]`.

Non-suppressed findings seed clusters. Overlapping windows or a gap ≤ merge gap merge. **Merge means copresence only.**

Suppressed findings never seed. If `t_ms` falls in a seeded window they are `TEMPORALLY_ASSOCIATED` and keep `suppressed=true`. Strengths (`P-*`) may be anchors; C.1 does not interpret polarity.

Zero findings → `[]`. No synthetic episode.

---

## 6. Provenance

Reuses `Source`, `Fact.confidence`, and `Provenance`. Additive `ContextOrigin`: `GST_FACT`, `GST_DERIVED`, `FEATURE`, `INFERENCE`, `UNAVAILABLE`.

Visual/`CV` facts are skipped (`origin_for_source` rejects them). `goldPerSecond` / `healthRegen` are stripped from copied payloads.

Finding evidence is referenced by label only. C.1 does not replace `Finding.evidence`.

---

## 7. ContextGap

Statuses: `UNAVAILABLE`, `UNKNOWN`, `INFERRED_ONLY`, `COARSE`.

Always recorded when applicable: true fog, ward map, continuous movement, wave state, visual observations. Inspection-based: summoner_state (no production GST loadout), unspent_gold/alive when PatchData is omitted, position_precision when a sample is off a 60s frame.

UNKNOWN/UNAVAILABLE stay explicit. C.1 does not default them into facts.

---

## 8. ConditionResolution

Statuses: `RESOLVED`, `PERSISTED`, `NOT_EVALUATED`, `UNKNOWN`.

Supported:

- **R-006** — purchase in post-window → RESOLVED; exact GOLD `currentGold` vs threshold → RESOLVED/PERSISTED; else UNKNOWN.
- **R-007** — purchase → RESOLVED; exact HEALTH ratio above YAML `hp_fraction_max` → RESOLVED; exact GOLD below min → RESOLVED; both conjuncts still true on exact frames → PERSISTED; else UNKNOWN.

Unsupported rules (including unseen jungler, vision, wave, positioning): `NOT_EVALUATED`. Interpolated HP/gold is not used to prove resolution. Config thresholds are copied from rule YAML and tested for equality.

---

## 9. Isolation

`riftlens.coaching.context` must not import `visual`, `vision`, `replay_host`, `gameplay`, `api`, `orchestration`, coaching providers/composer/validator/bundler, `openai`, or `anthropic`. Enforced by import-linter + source scan test.

C.1 does not import LLM code and requires no LLM at runtime.

---

## 10. Tests

`tests/unit/test_coaching_context_c1.py`: zero findings, clamp, merge/separate, deterministic ids, provenance/quarantine/visual skip, coarse position, suppressed/strengths, R-006/R-007 resolution fail-closed, YAML threshold match, `NA1_fixture_a` + H.7 GSTs, isolation scan.

Existing H.6/H.7/H.8/H.11 tests are regression (C.1 is unused by those pipelines).

---

## 11. Limitations / UNKNOWN

- 60s frames remain coarse; interpolation is GST policy, not new truth.
- Post-window is 30s, so many R-006/R-007 cases are UNKNOWN (no exact frame/purchase).
- Summoner/rune/vision-score MATCH fields are still not GST facts.
- Fight refs are H.5 `segment_fights` clusters (DERIVED).
- Alive is PatchData respawn inference when patch is passed.
- Episodes are not persisted and not shown in the UI.

---

## 12. C.1 completion criteria

1. Versioned CoachingEpisode exists (`c1.0`).
2. Findings deterministically become episode context.
3. BEFORE/ANCHOR/AFTER GST samples exist.
4. Grouping is explicit TEMPORAL_COPRESENCE.
5. Provenance preserved; visual sources excluded.
6. ContextGap keeps missing information missing.
7. Conservative extensible ConditionResolution exists.
8. No coaching/root-cause judgement fields.
9. No visual dependency.
10. No LLM dependency.
11. No DB migration.
12. No UI/API change.
13. Player-facing reviews unchanged (C.1 not in the job DAG).
14. Targeted tests added.
15. Targeted C.1 tests pass (18). Full sidecar pytest: **759 passed, 9 skipped**. `mypy --strict` clean. Import-linter: **13 kept** including `c1 coaching context isolation`. Ruff clean on C.1 files. Full `ruff check riftlens tests` currently fails on pre-existing `real_match.py:200` E501 from `ee2c898` (not part of this diff).
16. Diff is C.1-only.
17. This report matches the implementation.

---

## 13. C.2 readiness

C.2 can import `build_coaching_episodes` and read episodes without changing H.8. C.1 does not decide causes, decision quality, or coaching copy. That work is out of scope here.
