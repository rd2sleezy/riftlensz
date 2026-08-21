# C.4 — Learning-Value Prioritization

**Date:** 2026-08-20  
**Branch:** `integrate/ui-r1`  
**Schema:** `c4.0` (`PRIORITIZATION_SCHEMA_VERSION`)  
**Does not implement:** C.5 teaching, C.6 cross-game history, H.8 replacement, API/UI wiring.

C.4 ranks C.3 `LessonCandidate`s by explainable **learning value**. Production H.8 `focus_count: 3` is unchanged.

## Laws

> The number of major lessons is evidence-driven, not fixed.

> Impact is not the same as learning value.

> Frequency is not the same as learning value.

> An unfavorable outcome does not prove a poor decision.

> Unsupported specificity must not outrank supported generality.

> A blocked capability cannot become high-confidence coaching merely because it sounds useful.

> Withholding a weak lesson is preferable to filling a quota.

---

## 1. Objective

Decide which match lessons are MAJOR, SECONDARY, STRENGTH, or WITHHELD — and why — without player-facing prose.

---

## 2. Reference prioritization principles

| Principle | C.4 reflection |
|---|---|
| Reduce overload | Variable major count; withholding |
| Select what matters | Thresholds + support gates |
| Weight relevance | role/rank/teachability priors |
| Repeated vs one-off | within-match recurrence factor |
| Clear priority | ranked MAJOR list |
| Explain why | PriorityFactors + reason codes |

---

## 3. Architecture

```
LessonCandidate[] (+ optional ScoringContext)
  → score_lesson_candidates
  → prioritize_lesson_candidates
  → PrioritizedLessonSet (c4.0)
```

Package: `riftlens.coaching.prioritization`

| File | Role |
|---|---|
| `models.py` | schema |
| `config.py` | provisional `LearningValueConfig` |
| `scorer.py` | factor scoring |
| `redundancy.py` | overlap relations |
| `prioritizer.py` | tier promotion |
| `__init__.py` | exports |

Not called from H.11 / H.8 production path.

---

## 4–5. Schema

`PrioritizedLessonSet`, `PrioritizedLesson`, `PriorityFactors`, `ScoringContext`, tiers MAJOR/SECONDARY/STRENGTH/WITHHELD.

IDs: `c4p_` + sha256.

---

## 6–8. Factors, config, variable count

Factors: evidence_support, within_match_recurrence, impact (capped), causal_leverage, actionability, teachability, specificity, capability_readiness, conflict/gap/resolution/redundancy penalties, role/rank relevance.

Config version `c4.0-provisional-1`. **No `focus_count`.**  
`max_major_safety_cap=8` is pathological guard only.

Tests prove 0 / 1 / 2 / 4 majors.

---

## 9–11. Tiers, redundancy, diversity

Strengths ranked on a separate track (no forced 2–3).  
Overlap: DISTINCT / RELATED / HIGH_OVERLAP / DUPLICATIVE via finding/episode Jaccard.  
Diversity is **not** a quota — never promotes weak unrelated lessons.

---

## 12–15. C.1 / C.2 / C.3 / capability interactions

- Capability BLOCKED / readiness BLOCKED → cannot be MAJOR  
- NOT_ACTIONABLE → cannot be MAJOR  
- INSUFFICIENT support → cannot be MAJOR  
- MIXED / conflicts → penalty  
- Resolution notes → persistence penalty (not “decision was good”)  
- C.2 UNKNOWN decision → no poor-decision bonus  

---

## 16. H.8 comparison

| H.8 production | C.4 experimental |
|---|---|
| `Gold × Freq^0.5 × Teach × Rank × Conf` | additive explainable factors |
| `focus_count: 3` fixed | threshold-driven variable count |
| FindingCluster input | LessonCandidate input |
| Diversity quota-ish | diversity not a quota |
| Strengths forced 2–3 | strengths variable |
| No explicit withhold reasons | WITHHELD + reason codes |

---

## 17–20. Tests / withhold reasons / C.6 seams

Withhold reasons: `INSUFFICIENT_SUPPORT`, `CAPABILITY_BLOCKED`, `HIGH_CONFLICT` (via MIXED→low value), `REDUNDANT_WITH_HIGHER_VALUE`, `LOW_LEARNING_VALUE`, `NOT_ACTIONABLE`, `TOO_BROAD`, `CONDITION_RESOLVED` (penalty), `DUPLICATE_EVIDENCE`, `UNSAFE_SPECIFICITY`, `SAFETY_CAP`.

`ScoringContext` reserves `cross_game_recurrence`, `active_focus`, `trend_by_concept` for C.6 (ignored with `C6_SEAMS_IGNORED`).

---

## 21. Limitations

Provisional weights; no calibrated science; impact often supplied via context; no teaching output.

---

## 22. C.5 readiness

C.5 can consume MAJOR/SECONDARY/STRENGTH rows with factors, gaps, conflicts, and reason codes. C.4 does not teach.
