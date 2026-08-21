# C.5 — Coaching Teaching & Practice Design

**Date:** 2026-08-20  
**Branch:** `integrate/ui-r1`  
**Schema:** `c5.0` (`TEACHING_SCHEMA_VERSION`)  
**Does not implement:** C.6 history, production CoachingItem/LLM/UI wiring, wave/mechanics/vision/summoner fabrication.

C.5 converts C.4 prioritized lessons into structured, evidence-bounded teaching using curated concept playbooks.

## Laws

> Teaching specificity may never exceed evidence specificity.

> A coaching concept can be taught even when the exact decision cannot be judged.

> General game knowledge must not be presented as evidence from the analyzed match.

> A recognition cue must use information the player can reasonably observe.

> An alternative must not be stated as certain when the required decision evidence is unavailable.

> A drill should train a decision process, not merely tell the player to play more games.

> A practice objective should target behavior, not merely match outcome.

> Blocked capabilities must remain blocked in teaching.

> The LLM is a narrator, not the source of coaching logic.

---

## 1–3. Objective / reference / architecture

```
PrioritizedLessonSet
  → build_teaching_lessons (+ optional LessonCandidate map)
  → TeachingLessonSet (c5.0)
```

Package: `riftlens.coaching.teaching` — models, playbooks, builder, readiness, render.

---

## 4–7. Schema / specificity / content origin / playbooks

**TeachingSpecificity:** EVENT_SPECIFIC | CONTEXTUAL | CONCEPT_GENERAL | UNAVAILABLE  
Production path uses CONTEXTUAL/CONCEPT_GENERAL (never event-specific decision judgment).

**ContentOrigin:** MATCH_EVIDENCE | GENERAL_GAME_PRINCIPLE | COACHING_INFERENCE | PRACTICE_INSTRUCTION

**Implemented playbooks:**  
`economy.resource_spending`, `economy.reset_timing`, `tempo.post_fight_conversion`, `objective.presence`, `laning.cs_maintenance`, `laning.level_discipline`, `risk.isolation`, `risk.forward_positioning`, `risk.threat_awareness`, `vision.control_ward_habit`, `vision.preparation`, `economy.itemization_condition`, `strength.clean_lane`, `strength.efficient_resets`

**Blocked (UNAVAILABLE):** `wave.management`, `mechanics.execution`, `combat.summoner_usage`, `risk.information_discipline`

---

## 8–15. Teaching components

| Component | Behavior |
|---|---|
| Evidence summary | MATCH_EVIDENCE only |
| Why it matters | GENERAL_GAME_PRINCIPLE |
| Alternative | usually GENERAL_ONLY (SUPPORTED unavailable today) |
| Recognition cue | player-observable; omniscient positions listed unavailable |
| Rule | WHEN→THEN with non-absolute qualifier |
| Drill | VERBAL_CUE / REVIEW / TRACKING / PAUSE_CHECK / REINFORCEMENT |
| Objective | process metrics; MEASURABLE_NOW / PARTIAL / NOT_MEASURABLE |

---

## 16. Tier depth

| Tier | Depth |
|---|---|
| MAJOR | FULL (cue/rule/drill/objective) |
| SECONDARY | LIGHT (no drill/objective) |
| STRENGTH | REINFORCEMENT |
| WITHHELD | skipped (`WITHHELD_UPSTREAM`) |

---

## 17–20. Upstream interactions

C.1 resolution acknowledged without “corrected the mistake”.  
C.2 UNKNOWN → no decision-wrong claims.  
C.3 no SUPPORTED causality → no caused-claims.  
C.4 rank/tier preserved.

---

## 21. checks.yaml comparison

Existing `the_fix` / `next_game_check` map naturally to rule + objective templates, but often overclaim exact decisions relative to C.2/C.3. C.5 playbooks keep general teaching; production copy remains untouched for later selective retention.

---

## 22–23. Future seams

LLM narrator receives structured fields only.  
C.6 can evaluate `PracticeObjective` via `required_future_evidence` + `prior_lesson_id`.

---

## 24–27. Tests / limits / C.6 readiness

Targeted TE/TS/RC/RULE/DR/OB/COACH suites. Weights provisional; no production wiring; ready for C.6 measurement without designing C.6.
