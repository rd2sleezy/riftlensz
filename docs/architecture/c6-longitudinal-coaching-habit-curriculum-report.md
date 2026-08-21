# C.6 — Longitudinal Coaching, Habit Tracking & Active Curriculum

**Date:** 2026-08-20  
**Branch:** `integrate/ui-r1`  
**Schema:** `c6.0`  
**Config:** `c6.0-provisional-1`  
**Package:** `riftlens.coaching.longitudinal`  
**Persistence:** **A — pure engine only; persistence deferred**

---

## 1. Objective

Turn multi-game C.1–C.5 structured outputs into:

* concept histories with opportunity-aware evidence
* conservative objective evaluation
* process trends (not win/loss)
* one primary active focus with hysteresis
* PreGameFocus / FocusUpdate loop packets

Without replacing production H.8/H.11 coaching.

## 2. External-reference behavior (generic)

| Style | Generic behavior reproduced |
| --- | --- |
| Trenix-like | Multi-game pattern vs one-off; next-game priority |
| Mobalytics-like | Persistent skill focus; keep/improve/move-on |
| iTero-like | Recent behavioral process tracking over outcomes |

No proprietary scoring, APIs, or scraping.

## 3. Architecture

```
HistoricalCoachingGame[]
        │
        ├─ build_concept_history
        ├─ evaluate_practice_objective
        ├─ derive_longitudinal_trend
        ├─ update_active_focus (hysteresis)
        └─ build_player_coaching_state
                │
                ├─ PreGameFocus
                └─ FocusUpdate
```

Pure: no network, LLM, visual, replay, or DB inside the engine.

## 4. c6.0 schema

`LONGITUDINAL_SCHEMA_VERSION = "c6.0"`.  
Does not bump C.1–C.5 schemas.

## 5. Historical input model

`HistoricalCoachingGame` carries match identity, patch, role, champion, optional win context, concept observations, C.4 tier ids, learning values, and optional teaching payload maps.

Prefer explicit history over DB queries.

## 6. Concept history

`ConceptHistory` aggregates independent games within a compatible `CoachingScope`:

* games observed / with opportunity
* positive / negative / mixed / unknown
* trajectory (`TrendState`)
* status (`PatternStatus`)
* evaluations, reason codes, confidence

## 7. Pattern states

`NEW`, `EMERGING`, `RECURRING`, `ACTIVE_FOCUS`, `IMPROVING`, `STABLE`, `REGRESSING`, `RESOLVED`, `INSUFFICIENT_EVIDENCE`.

These describe evidence history — not permanent traits.

## 8. Opportunity model

`OpportunityStatus`:

* `OBSERVED_OPPORTUNITY`
* `NO_OBSERVABLE_OPPORTUNITY`
* `UNKNOWN_OPPORTUNITY`
* `NOT_APPLICABLE`

Absence of a Finding without observed opportunity is never success.

## 9. Objective evaluation

`evaluate_practice_objective` → `ObjectiveEvaluation` with
`SUCCESS | PARTIAL | FAILURE | NOT_EVALUATED | UNKNOWN`.

## 10. Measurability

Respects C.5:

* `MEASURABLE_NOW` → deterministic success/failure when opportunity observed
* `PARTIALLY_MEASURABLE` → capped `PARTIAL` / `UNKNOWN`
* `NOT_MEASURABLE` → `NOT_EVALUATED`

## 11. Process vs outcome

Win/loss may be stored as context on `HistoricalCoachingGame.won`.  
Trends and objective results use process metrics (occurrence counts / measurable_metric), never winrate/LP.

## 12. Normalization

When `opportunity_denominator` exists, observations can carry normalized metrics.  
If no denominator: limited qualitative trend handling. Documented in config/tests.

## 13. Trend model

`derive_longitudinal_trend`: simple recent-vs-prior average of comparable opportunity metrics.

`IMPROVING | STABLE | REGRESSING | UNKNOWN`

## 14. Hysteresis

`focus_switch_margin`, `min_focus_continuity_games`, resolved cooldown.  
One loud unrelated MAJOR does not flip focus.

## 15. Active focus

`ActiveFocus`: one primary concept + objective/cue/rule/drill + continuity + evaluations.

Default policy: **one** primary (`allow_multiple_primary_focuses=False`).  
Not production `focus_count: 3`.

## 16. Transition policy

Keep unless resolved, blocked, or challenger clearly/outlastingly outranks with recurrence + margin.

## 17. Resolution

Conservative: enough successful opportunity evaluations, enough opportunity games, no recent failures.  
Not perfection.

## 18. Regression / reactivation

`REGRESSING` + prior cooldown can `REACTIVATE_FOCUS`.

## 19. Scope

`ScopeLevel`: `GLOBAL | ROLE | CHAMPION`.  
Role-incompatible games do not inflate recurrence.

## 20. Recency

`max_games`, `recent_window` in `LongitudinalCoachingConfig`.

## 21. Strengths

`StrengthHistory`: `POSITIVE_SIGNAL | EMERGING_STRENGTH | CONSISTENT_STRENGTH`.  
Secondary; never becomes correction focus automatically.

## 22. PreGameFocus

Structured reminder packet (cue/rule/drill/objective/why/progress). Not UI-wired.

## 23. FocusUpdate

Post-game keep/switch/resolve/reactivate/no-new with reason codes.

## 24. Existing DB compatibility

| Record | C.6 use |
| --- | --- |
| `FocusCommitmentRecord` | Prior art only — different semantics; do not reinterpret |
| `FindingFeedbackRecord` | Future seam only |
| `PlayerRecord` / champion profile | Identity adapter seam only |
| Review JSON | No C.x persistence today |

## 25. Persistence decision

**A.** Pure longitudinal engine; persistence deferred. No migration.

## 26. Future LLM seam

Narration only after structured state exists. No LLM in C.6 state determination.

## 27. Blocked capabilities

`wave.management`, `mechanics.execution`, `combat.summoner_usage`, `risk.information_discipline` cannot become measurable active focuses or claim improving/resolved from RiftLens evidence.

## 28. Tests

`tests/unit/test_coaching_longitudinal_c6.py` covers HS/OE/TR/CUR/LOOP/golden/anti-bias.

## 29. Limitations

* Requires caller-supplied C.x history (not reconstructed from production reviews)
* Provisional thresholds
* Patch-specific sensitivity not modeled beyond recording patch
* Champion-family coaching not elaborate

## 30. Completion criteria

See work-order §71 — met by package + tests + isolation + no production wiring.

## 31. C.7 readiness

C.7 can quality-benchmark serialized `PlayerCoachingState` against multi-game goldens.  
C.6 does not design C.7.

---

## Explicit laws (restated)

1. One game ≠ recurring habit  
2. Absence of Finding ≠ success  
3. Improvement needs observable comparable evidence  
4. Win/loss ≠ coaching progress  
5. Blocked/non-measurable ≠ improved/resolved  
6. Do not chase the latest loudest mistake  
7. One primary deliberate-practice focus  
8. RESOLVED ≠ perfection  
9. Longitudinal state is inference, never GST fact
