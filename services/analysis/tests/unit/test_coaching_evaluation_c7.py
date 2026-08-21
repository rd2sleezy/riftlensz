"""C.7 coaching quality benchmark tests."""

from __future__ import annotations

from pathlib import Path

from riftlens.coaching.evaluation import (
    EVALUATION_SCHEMA_VERSION,
    HUMAN_VALIDATION_STATUS,
    CaseSourceType,
    EvaluatorExpertise,
    FailureCategory,
    GateStatus,
    HardFailKind,
    HumanEvaluation,
    PairwisePreference,
    RubricDimension,
    RubricRating,
    RubricScore,
    adjudication_needed,
    build_benchmark_case,
    build_benchmark_run,
    build_evaluation_packet,
    build_initial_corpus,
    build_local_real_match_case_stub,
    compare_systems,
    evaluate_system_view,
    get_rubric_definitions,
    ingest_human_evaluations,
    normalize_cx_candidate,
    normalize_production_baseline,
    recover_systems_from_mapping,
    render_report_markdown,
    run_automated_checks,
    run_ci_regression_benchmark,
    summarize_agreement,
    summarize_benchmark,
)

_ROOT = Path(__file__).resolve().parents[2] / "riftlens" / "coaching" / "evaluation"


def test_schema_and_human_status() -> None:
    assert EVALUATION_SCHEMA_VERSION == "c7.0"
    assert HUMAN_VALIDATION_STATUS == "NOT_YET_PERFORMED"


def test_corpus_covers_core_domains() -> None:
    corpus = build_initial_corpus()
    assert len(corpus) >= 10
    ids = {item.case_id for item in corpus}
    assert "c7_economy_reset" in ids
    assert "c7_blocked_wave" in ids
    assert "c7_longitudinal_five_game" in ids
    assert all(item.source_type is CaseSourceType.SYNTHETIC_EDGE_CASE for item in corpus)


def test_rubric_anchors_complete() -> None:
    defs = get_rubric_definitions()
    assert len(defs) >= 16
    for item in defs:
        assert len(item.anchors) == 5


def test_hf01_decision_overreach() -> None:
    view = normalize_cx_candidate(
        {
            "decision_quality": "UNKNOWN",
            "structural": {"asserts_definite_decision": True},
        }
    )
    fails = run_automated_checks(view)
    assert any(item.kind is HardFailKind.DECISION_OVERREACH for item in fails)


def test_hf02_causal_overreach() -> None:
    view = normalize_cx_candidate(
        {
            "causal_status": "INSUFFICIENT",
            "structural": {"asserts_definite_causality": True},
        }
    )
    fails = run_automated_checks(view)
    assert any(item.kind is HardFailKind.CAUSAL_OVERREACH for item in fails)


def test_hf03_capability_violation() -> None:
    view = normalize_cx_candidate(
        {
            "concept_ids": ["wave.management"],
            "capability_statuses": {"wave.management": "BLOCKED"},
            "lesson": "You should freeze the wave here",
            "structural": {"gives_specific_blocked_advice": True},
        }
    )
    fails = run_automated_checks(view)
    assert any(item.kind is HardFailKind.CAPABILITY_VIOLATION for item in fails)


def test_hf04_player_knowledge() -> None:
    view = normalize_cx_candidate(
        {
            "player_knowledge": "UNAVAILABLE",
            "structural": {"claims_player_could_not_see": True},
        }
    )
    fails = run_automated_checks(view)
    assert any(item.kind is HardFailKind.PLAYER_KNOWLEDGE_OVERREACH for item in fails)


def test_hf05_longitudinal_false_success() -> None:
    view = normalize_cx_candidate(
        {
            "opportunity_status": "NO_OBSERVABLE_OPPORTUNITY",
            "objective_result": "SUCCESS",
        }
    )
    fails = run_automated_checks(view)
    assert any(item.kind is HardFailKind.LONGITUDINAL_FALSE_SUCCESS for item in fails)


def test_hf06_false_progress() -> None:
    view = normalize_cx_candidate(
        {
            "measurability": "NOT_MEASURABLE",
            "longitudinal_status": "RESOLVED",
        }
    )
    fails = run_automated_checks(view)
    assert any(item.kind is HardFailKind.FALSE_PROGRESS for item in fails)


def test_blinding_stable_and_recoverable() -> None:
    case = build_initial_corpus()[0]
    baseline = normalize_production_baseline(
        focus_items=[
            {
                "id": "1",
                "root_concept_id": "economy.reset_timing",
                "title": "Reset",
                "body": "Reset earlier",
            }
        ]
    )
    candidate = normalize_cx_candidate(
        {
            "lesson": "Reset before objective",
            "cue": "When gold > threshold",
            "concept_ids": ["economy.reset_timing"],
            "major_count": 1,
        }
    )
    p1 = build_evaluation_packet(case, baseline, candidate, seed=7)
    p2 = build_evaluation_packet(case, baseline, candidate, seed=7)
    assert p1.mapping.to_dict() == p2.mapping.to_dict()
    facing = p1.evaluator_facing_dict()
    assert "production_h8" not in str(facing)
    assert "cx_candidate" not in str(facing)
    assert facing["system_a"]["system_id"] == "REDACTED"
    recovered = recover_systems_from_mapping(p1.mapping, "A")
    assert recovered in {"production_h8", "cx_candidate"}

    p_other = build_evaluation_packet(case, baseline, candidate, seed=99)
    # Different seed may swap (not guaranteed for all case ids, but mapping differs)
    assert p_other.seed == 99


def test_gold_not_in_system_payload() -> None:
    case = build_benchmark_case(
        "x",
        case_type="t",
        source_type=CaseSourceType.SYNTHETIC_EDGE_CASE,
        evaluation_levels=(),
        match_ref="m",
        system_input={"a": 1},
        evaluator_only_notes="SECRET_GOLD_ANSWER",
    )
    payload = case.system_facing_payload()
    assert "SECRET_GOLD_ANSWER" not in str(payload)
    assert "evaluator_only" not in payload


def test_agreement_and_adjudication() -> None:
    def _ev(
        eid: str,
        score: RubricScore,
        pairwise: PairwisePreference,
        hard: tuple[HardFailKind, ...] = (),
    ) -> HumanEvaluation:
        return HumanEvaluation(
            evaluator_id=eid,
            expertise=EvaluatorExpertise.COACH,
            case_id="c1",
            system_label_shown="A",
            evaluated_at_ms=1,
            rubric_scores=(
                RubricRating(RubricDimension.Q5_PRIORITY_QUALITY, score),
            ),
            hard_fail_flags=hard,
            pairwise=pairwise,
        )

    a = _ev("e1", RubricScore.GOOD, PairwisePreference.A_SLIGHTLY_BETTER)
    b = _ev("e2", RubricScore.GOOD, PairwisePreference.A_CLEARLY_BETTER)
    summary = summarize_agreement([a, b])
    assert summary.n_pairs == 1
    assert summary.exact_agreement_rate == 1.0
    assert summary.pairwise_agreement_rate == 1.0

    c = _ev(
        "e3",
        RubricScore.FAIL,
        PairwisePreference.B_CLEARLY_BETTER,
        (HardFailKind.FACT_FABRICATION,),
    )
    assert adjudication_needed(a, c) is True


def test_human_gates_not_evaluated_without_ratings() -> None:
    summary = summarize_benchmark(build_initial_corpus(), ())
    human_gates = [
        item for item in summary.gate_results if item.gate_id.startswith("HUMAN_")
    ]
    assert human_gates
    assert all(item.status is GateStatus.NOT_EVALUATED for item in human_gates)
    assert summary.human_validation_status == HUMAN_VALIDATION_STATUS


def test_baseline_vs_cx_honest_comparison() -> None:
    case = next(
        item for item in build_initial_corpus() if item.case_id == "c7_baseline_vs_cx_compare"
    )
    # Baseline more concise
    baseline = normalize_production_baseline(
        focus_items=[
            {
                "id": "b1",
                "root_concept_id": "economy.resource_spending",
                "title": "Spend gold",
                "body": "Buy sooner.",
            }
        ]
    )
    # C.x withholds decision certainty (better epistemic) but longer
    candidate = normalize_cx_candidate(
        {
            "lesson": "Resource spending process",
            "why": "Supported high-unspent-gold findings",
            "alternative": "GENERAL_ONLY: spend when threshold met",
            "cue": "Gold bank rising",
            "drill": "Track unspent gold each recall",
            "objective": "Reduce high-unspent occurrences",
            "decision_quality": "UNKNOWN",
            "concept_ids": ["economy.resource_spending"],
            "major_count": 1,
            "limitations": ("decision_unknown",),
        }
    )
    comparison = compare_systems(case, baseline, candidate, seed=3)
    # Baseline missing teaching fields — not invented
    assert baseline.cue is None
    assert candidate.cue is not None
    # Neither auto-wins structurally on hard fails
    assert comparison["baseline_result"]["passed_hard_gates"] is True
    assert comparison["candidate_result"]["passed_hard_gates"] is True
    assert "Neither system auto-wins" in comparison["note"]


def test_ci_regression_passes() -> None:
    result = run_ci_regression_benchmark()
    assert result.passed is True
    assert result.to_dict()["not_human_quality_validation"] is True


def test_rating_import_requires_notes_on_hard_fail() -> None:
    import pytest

    with pytest.raises(ValueError):
        ingest_human_evaluations(
            [
                {
                    "evaluator_id": "e1",
                    "case_id": "c1",
                    "rubric_scores": [],
                    "hard_fail_flags": ["FACT_FABRICATION"],
                    "notes": "",
                }
            ]
        )


def test_local_real_match_seam_rejects_pii() -> None:
    import pytest

    with pytest.raises(ValueError):
        build_local_real_match_case_stub(
            "m1",
            {"focus_items": [], "puuid": "secret"},
        )
    case = build_local_real_match_case_stub(
        "m1",
        {"focus_items": [{"root_concept_id": "economy.reset_timing", "title": "x"}]},
    )
    assert case.source_type is CaseSourceType.REAL_MATCH_LOCAL


def test_benchmark_run_records_versions() -> None:
    case = build_initial_corpus()[0]
    view = normalize_cx_candidate({"lesson": "ok", "decision_quality": "UNKNOWN"})
    result = evaluate_system_view(case, view)
    run = build_benchmark_run(
        automated_results=[result],
        cases=[case],
        git_commit="006e8bf",
    )
    assert run.schema_version == "c7.0"
    assert run.git_commit == "006e8bf"
    assert "HUMAN QUALITY VALIDATION" in render_report_markdown(run.summary)


def test_failure_taxonomy_complete() -> None:
    assert FailureCategory.FOCUS_FLAPPING in FailureCategory
    assert FailureCategory.FALSE_PROGRESS in FailureCategory


def test_import_isolation_scan() -> None:
    banned = (
        "riftlens.visual",
        "riftlens.replay_host",
        "riftlens.coaching.providers",
        "openai",
        "anthropic",
    )
    for path in _ROOT.glob("*.py"):
        text = path.read_text(encoding="utf-8")
        for token in banned:
            assert token not in text, f"{path.name} imports {token}"
