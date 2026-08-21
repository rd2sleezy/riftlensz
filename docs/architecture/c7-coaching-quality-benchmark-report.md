# C.7 — Coaching Quality Benchmark & Human Evaluation Framework

**Date:** 2026-08-21  
**Branch:** `integrate/ui-r1`  
**Schema:** `c7.0`  
**Config / rubric / corpus:** `c7.0-provisional-1` / `c7.0-rubric-1` / `c7.0-corpus-1`  
**Package:** `riftlens.coaching.evaluation`

## Verdict distinction (mandatory)

| Layer | Status |
| --- | --- |
| **BENCHMARK INFRASTRUCTURE** | COMPLETE |
| **HUMAN QUALITY VALIDATION** | **NOT YET PERFORMED** |

Passing C.1–C.6 unit tests does not prove coaching quality. C.7 infrastructure completion does not equal human validation.

---

## 1. Objective

Formal evaluation system for whether C.1–C.6 coaching is factually grounded, epistemically disciplined, prioritized, teachable, measurable, and longitudinally coherent — vs engineering correctness alone.

## 2. Engineering correctness vs coaching quality

Unit tests verify structure and invariants.  
C.7 detects mediocre or unsafe coaching that still “passes tests.”

## 3. Reference evaluation methodology

Same-case comparison · objective vs subjective separation · blinding · UNJUDGEABLE allowed · disagreement preserved · claims bounded by coverage.

## 4. Architecture

```
CoachingBenchmarkCase (system_input ⊥ evaluator_only gold)
        ↓
normalize_production_baseline / normalize_cx_candidate
        ↓
run_automated_checks (hard fails)
        ↓
build_evaluation_packet (blind A/B)
        ↓
ingest_human_evaluations (optional)
        ↓
summarize_benchmark / BenchmarkRun
```

CI: `run_ci_regression_benchmark` (safety invariants ≠ human quality).

## 5–8. Schema, levels, cases, sources

`c7.0` · Levels 1–6 · `CaseSourceType` includes SYNTHETIC / REPO / REAL_MATCH_LOCAL / HUMAN_CURATED / EXTERNAL_REFERENCE_MANUAL.  
Committed corpus is synthetic only; private raw matches must not be committed.

## 9–10. Rubric + hard gates

Q1–Q15 + LANGUAGE_CLARITY with behaviorally anchored 0–4 + N/A + UNJUDGEABLE.  
Hard fails: fact fabrication, decision/causal/player-knowledge overreach, capability violation, result bias, longitudinal false success, false progress.

## 11–17. Taxonomy, adapters, blinding, pairwise, humans, agreement

Failure taxonomy enum · H.8 and C.x normalizers (missing fields stay missing) · deterministic seed blinding · pairwise prefs · multi-evaluator + adjudication seam · lightweight agreement rates.

## 18–23. Results, claims, gates, coverage, seams

`BenchmarkRun` / `BenchmarkSummary` · claim-based reporting · provisional gates · capability coverage READY/PARTIAL/BLOCKED/UNTESTED · local real-match stub (rejects PUUID etc.) · manual `ReferenceCoachingOutput` only (no scraping).

## 24. Optional human-study protocol

Select anonymized multi-domain cases → ≥2 independent evaluators → blind packets → rubric + pairwise → adjudicate large disagreements → report by domain → do not overclaim from small N.

## 25. Player usefulness seam

Future feedback: useful / understandable / actionable / too much / already knew / disagree — no UI in C.7.

## 26–27. Laws

> Passing unit tests does not prove coaching quality.  
> Fluent language cannot compensate for incorrect coaching logic.  
> Human disagreement is data, not noise to erase.  
> Gold/reference annotations must never leak into the system being evaluated.  
> A benchmark can only support claims within the domains and cases it actually tests.  
> BLOCKED capabilities are evaluated on honest refusal, not on fabricated coaching.  
> C.7 must be capable of detecting regressions in newer coaching systems.  
> Benchmark infrastructure completion does not equal human quality validation.

## 28. CLI

`python scripts/c7_benchmark.py {regression|corpus|template|report}`

## 29. Limitations

No independent human ratings yet · synthetic corpus ≠ full League · provisional thresholds · no competitor adapters.

## 30. Post-C.7

Framework ready for studies. Coaching quality claims remain mostly **unsupported** until blinded human evaluation exists. Next phase should be driven by benchmark findings — not score chasing inside C.7.
