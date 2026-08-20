# C.3 — Coaching Concepts, Causal Synthesis & Reference Capability Mapping

**Date:** 2026-08-20  
**Branch:** `integrate/ui-r1`  
**Schema:** `c3.0` (`CONCEPTS_SCHEMA_VERSION`)  
**Does not implement:** C.4 prioritization, C.5 teaching/drills/prose, H/R/V changes, visual, LLM, DB persistence, API/UI wiring, competitor integrations.

C.3 turns C.1 episodes + C.2 interpretations into reusable concept signals, conservative causal hypotheses, lesson candidates, and an explicit capability-readiness catalog.

## Laws

> A concept signal is not automatically a coaching weakness.

> Temporal proximity does not establish causality.

> Outcome does not establish decision quality.

> A broader supported concept is preferable to a specific unsupported concept.

> An external coaching system demonstrating a capability does not mean RiftLens has the evidence required to reproduce it.

> Capability gaps should be documented, not hidden through inference.

> UNKNOWN/BLOCKED is a successful result when evidence is insufficient.

---

## 1. Objective

Answer:

1. What reusable coaching concept might these observations represent?
2. Are multiple findings likely manifestations of related issues (hypothesis only)?
3. Which specialized coaching capabilities can RiftLens safely mimic today?

Without changing player-facing reviews.

---

## 2. Reference-system development policy

For major coaching domains:

1. identify reference capability behavior  
2. list required evidence  
3. compare to RiftLens GST/C.1/C.2 evidence  
4. classify READY / PARTIAL / BLOCKED / UNKNOWN  
5. implement only what evidence supports  
6. document missing evidence explicitly  
7. never add competitor runtime dependencies  

External products are **benchmarks**, not code dependencies.

---

## 3. Architecture

```
GST + Finding[]
  → C.1 CoachingEpisode[]
  → C.2 EpisodeInterpretation[]
  → C.3 map_concept_signals / synthesize_lesson_candidates
  → ConceptSignal[] + CausalHypothesis[] + LessonCandidate[]
  → evaluate_capability_readiness()
```

Package: `riftlens.coaching.concepts`

| File | Role |
|---|---|
| `models.py` | c3.0 schema |
| `catalog.py` | CoachingConcept taxonomy |
| `mapping.py` | R-001..R-020 / P-001..P-005 mappings |
| `capabilities.py` | CAP-* readiness catalog |
| `h8_priors.py` | read-only H.8 graph priors |
| `synthesis.py` | public synthesizer APIs |
| `__init__.py` | exports |

Not called from H.11, prioritizer, composer, API, or UI.

---

## 4. Schema `c3.0`

Types: `CoachingConcept`, `ConceptSignal`, `CausalHypothesis`, `LessonCandidate`, `CoachingCapability`, `SynthesisResult`.

IDs: `c3s_` / `c3h_` / `c3l_` + sha256.

`teaching_output = NOT_IMPLEMENTED`, `prioritization = NOT_IMPLEMENTED`.

---

## 5–7. Taxonomy, mapping, specificity

Concepts are justified by production rules (economy, tempo, risk, vision, laning, objective, combat, positional, strengths) plus explicit **blocked** concepts (`wave.management`, `mechanics.execution`, `combat.summoner_usage`, `risk.information_discipline`).

Specificity ladder: SPECIFIC → GENERAL → BROAD → UNRESOLVED. Unknown rules fall to `context.risk_broad` / UNRESOLVED.

---

## 8–11. CausalHypothesis / LessonCandidate / support / conflicts

**CausalStatus:** SUPPORTED / PLAUSIBLE / CONFLICTED / UNKNOWN.

**SUPPORTED contracts in C.3:** **none** (`supported_causal_contracts() == {}`).

Temporal order alone → never SUPPORTED.  
H.8 graph prior + temporal co-occurrence → at most PLAUSIBLE with `SUPPORTED_CONTRIBUTOR` / `POTENTIAL_ANTECEDENT`.

Lesson polarity: CONSISTENT_NEGATIVE / CONSISTENT_POSITIVE / MIXED / INSUFFICIENT.  
Support: STRONG / MODERATE / WEAK / INSUFFICIENT (C.3 practically caps at MODERATE).  
Conflicts preserved on MIXED lessons.

---

## 12. H.8 relationship

C.3 loads `causal_graph.yaml` via `load_causal_graph()` as **prior art only**.

- Does not call `cluster_findings`
- Does not change production clustering
- H.8 edge match → PLAUSIBLE, never automatic SUPPORTED
- Documented reason codes: `H8_CAUSAL_GRAPH_PRIOR`, `H8_PRIOR_NOT_SUPPORTED`

---

## 13–14. C.1 resolution / C.2 UNKNOWN

RESOLVED reduces persistence/support strength via `CONDITION_RESOLUTION_REDUCES_PERSISTENCE`.  
It does **not** mark the original decision good.

Every concept signal carries `C2_DECISION_REMAINS_UNKNOWN` when C.2 decision is UNKNOWN.  
C.3 does not emit POOR/GOOD decision labels.

---

## 15–16. Capability readiness

| Capability | Readiness | Can safely mimic? |
|---|---|---|
| CAP-WAVE-STATE | BLOCKED | no |
| CAP-WAVE-ACTION | BLOCKED | no |
| CAP-RESET | PARTIAL | yes (signals only) |
| CAP-FIGHT-SELECTION | BLOCKED | no |
| CAP-OBJECTIVE-PRESENCE | PARTIAL | yes (narrow presence) |
| CAP-VISION-QUALITY | BLOCKED | no |
| CAP-JUNGLE-INFORMATION | BLOCKED | no |
| CAP-MECHANICAL-EXECUTION | BLOCKED | no |
| CAP-SUMMONER-USAGE | BLOCKED | no |
| CAP-RESOURCE-SPENDING | PARTIAL | yes |

### Wave analysis (explicit)

| Action | Status | Missing evidence |
|---|---|---|
| freeze | BLOCKED | minion counts/HP, wave position/direction |
| slow_push | BLOCKED | same |
| hard_push | BLOCKED | same |
| crash | BLOCKED | same |
| bounce | BLOCKED | same |
| hold | BLOCKED | same |

CS snapshots and coarse position are **not** wave state.

---

## 17. Isolation

Import-linter contract `c3 coaching concepts isolation` forbids visual, replay_host, LLM providers/composer/validator/bundler, openai, anthropic.

---

## 18. Limitations

- Zero CausalStatus.SUPPORTED contracts
- No wave recommendations
- No mechanical execution claims
- No true fog / ward-map quality
- Within-match recurrence only (not C.6 habits)
- Not persisted / not shown in UI

---

## 19. Completion criteria

Met for fail-closed C.3 foundation. Pre-existing `real_match.py:200` E501 unrelated.

---

## 20. C.4 readiness

C.4 can consume `LessonCandidate` features (occurrences, support, conflicts, specificity, gaps) for prioritization. C.3 does not sort final coaching priority.
