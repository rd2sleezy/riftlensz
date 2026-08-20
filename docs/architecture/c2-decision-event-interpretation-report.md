# C.2 — Decision & Event Interpretation

**Date:** 2026-08-20  
**Branch:** `integrate/ui-r1`  
**Schema:** `c2.0` (`EPISODE_INTERPRETATION_SCHEMA_VERSION`)  
**Does not implement:** C.3+ root-cause synthesis, C.4 prioritization, C.5 prose/alternatives/drills, H/R/V changes, visual consumption, LLM changes, DB persistence, API/UI wiring.

C.2 adds a deterministic interpretation layer over C.1 `CoachingEpisode` objects. Player-facing reviews remain unchanged.

## Laws

> A bad outcome does not prove a poor decision.

> A good outcome does not prove a good decision.

> Temporal precedence does not prove causality.

> Omniscient GST information does not prove player knowledge.

> Condition resolution does not prove the original decision was correct.

> UNKNOWN is a valid interpretation.

---

## 1. Objective

Answer structured questions about what happened, what can be evaluated, and what remains unknown — without inventing decision quality from results.

---

## 2. Reference-coaching principles

| Principle | C.2 reflection |
|---|---|
| Decision ≠ outcome | Independent `DecisionAssessment` and `ObservedOutcome` |
| Decision before execution | Separate `ExecutionAssessment`, usually `NOT_OBSERVABLE` |
| Rewind from anchors | Consumes C.1 BEFORE/ANCHOR/AFTER + temporal buckets |
| Sequence | Antecedent / concurrent / consequence observations (non-causal) |
| Player knowledge | `InformationClaim` with `KnowledgeStatus`; fog UNAVAILABLE |
| Execution UNKNOWN | GST-only → `NOT_OBSERVABLE` |
| No over-review | Not wired into H.11 / UI |
| Generalization later | No alternatives, root causes, or practice objectives |

---

## 3. Architecture

```
GST + Finding[]
  → C.1 build_coaching_episodes
  → CoachingEpisode[]
  → interpret_coaching_episodes
  → EpisodeInterpretation[]   (c2.0)
```

Package: `riftlens.coaching.interpretation`

| File | Role |
|---|---|
| `models.py` | Schema, enums, helpers |
| `catalog.py` | R-001..R-020 / P-001..P-005 signal profiles |
| `registry.py` | FindingInterpreter protocol + default interpreter |
| `builder.py` | `interpret_coaching_episode(s)` |
| `__init__.py` | Public exports |

Not called from H.11, clusterer, prioritizer, composer, persist, API, or UI.

---

## 4. Schema `c2.0`

`EpisodeInterpretation` includes episode identity, finding interpretations, outcomes, episode-level decision/execution/actionability, decision×outcome relation, temporal observations, C.1 condition resolutions, information claims, unknowns, provenance, `alternative_analysis=NOT_IMPLEMENTED`.

IDs: `c2i_` + sha256 of `{schema, method, method_version, episode_id, participant_id}`.

---

## 5–8. Outcome / decision / relation / execution

**Outcome** polarity may be FAVORABLE / UNFAVORABLE / NEUTRAL from the catalog without implying decision quality.

**Decision:** production path always `UNKNOWN` in C.2.  
`evidence_contracts()` returns `{}`. No GOOD/POOR/MIXED contracts ship.

**Relation:** `derive_decision_outcome_relation` — if decision is UNKNOWN → `UNCLASSIFIED` regardless of outcome. Matrix representable in model tests (RB-09).

**Execution:** `NOT_OBSERVABLE` with reason `GST_ONLY_NO_MECHANICAL_EVIDENCE`.

---

## 9–12. Actionability / temporal / knowledge / coverage

**Actionability:** `NOT_ACTIONABLE` only when AFTER sample proves dead; otherwise `UNKNOWN` (alive ≠ strategic agency).

**Temporal:** ANTECEDENT / CONCURRENT / CONSEQUENCE with note that ordering is not causal.

**Knowledge:** enemy POSITION frames are system-available with player knowledge `UNAVAILABLE`. High `info_age` does not become “player could not see.”

**Catalog:** all R-001..R-020 and P-001..P-005 mapped; `decision_assessable=False`, `execution_observable=False`.

---

## 13. Non-UNKNOWN decision assessments

**None in production C.2.**

Documented intentionally. Inventing POOR from deaths or GOOD from strengths would violate anti-result-bias and documented rule false positives.

---

## 14. Provenance / confidence

Finding confidence is not reused as decision confidence. Decision confidence is `0.0` when UNKNOWN. Episode confidence is min outcome confidence for serialization only — not a decision score.

---

## 15. Anti-result-bias / RB tests

RB-01..RB-10 in `tests/unit/test_coaching_interpretation_c2.py`.

---

## 16. Isolation

Import-linter contract `c2 coaching interpretation isolation` forbids visual, replay_host, LLM providers/composer/validator/bundler, openai, anthropic.

---

## 17. Limitations

- Zero production GOOD/POOR decisions (by design)
- Execution almost always NOT_OBSERVABLE
- Enemy knowledge UNAVAILABLE without fog
- No alternatives / root causes
- Not persisted / not shown in UI

---

## 18. Completion criteria

Met for structured fail-closed C.2 foundation. Full suite intended green except pre-existing `real_match.py:200` E501.

---

## 19. C.3 readiness

C.3 can consume `EpisodeInterpretation` + C.1 episodes to attempt causal synthesis without inventing decision labels from outcomes alone. C.2 does not perform that synthesis.
