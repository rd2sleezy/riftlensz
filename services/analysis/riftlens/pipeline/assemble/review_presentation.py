from __future__ import annotations

import json
from collections.abc import Mapping, Sequence
from pathlib import Path
from typing import Any

from riftlens.domain.evidence import Evidence
from riftlens.domain.finding import Finding
from riftlens.domain.observation.to_evidence import evidence_origin_label
from riftlens.domain.review import CoachingItem, MetricSnapshot, Review, format_mmss
from riftlens.domain.sync_map import SyncMap, seek_target

UNPAIRED_FIXTURE_WARNING = (
    "Fixture A/B/C are copies of one unpaired match+timeline dump. "
    "match.json and timeline.json are not the same real game. "
    "Treat identity, lane matchups, and some metrics as limited."
)
_QUARANTINED_KEYS = ("goldPerSecond", "healthRegen")


def review_to_presentation(
    review: Review,
    *,
    sync_map: SyncMap | None = None,
    media: Mapping[str, Any] | None = None,
    fixture_id: str | None = None,
) -> dict[str, Any]:
    """Serialize an H.8 Review for the desktop UI. Does not reread Riot JSON."""
    warning = UNPAIRED_FIXTURE_WARNING if review.unpaired_match_timeline else None
    findings = [_finding_json(item) for item in review.findings]
    finding_by_id = {item.id: item for item in review.findings}
    return {
        "id": review.id,
        "player_id": review.player_id,
        "match_id": review.match_id,
        "participant_id": review.participant_id,
        "champion": review.champion,
        "role": review.role.value,
        "rank": review.rank,
        "patch": review.patch,
        "duration_ms": review.duration_ms,
        "result": review.result,
        "rule_pack_version": review.rule_pack_version,
        "engine_version": review.engine_version,
        "llm_provider": review.llm_provider,
        "llm_model": review.llm_model,
        "llm_prompt_version": review.llm_prompt_version,
        "llm_fallback": review.llm_fallback,
        "status": review.status,
        "summary_text": review.summary_text,
        "unpaired_match_timeline": review.unpaired_match_timeline,
        "fixture_warning": warning,
        "fixture_id": fixture_id,
        "created_at": review.created_at,
        "completed_at": review.completed_at,
        "focus_items": [_item_json(item, finding_by_id, sync_map) for item in review.focus_items],
        "secondary_items": [
            _item_json(item, finding_by_id, sync_map) for item in review.secondary_items
        ],
        "strengths": [_item_json(item, finding_by_id, sync_map) for item in review.strengths],
        "metrics": [_metric_json(item) for item in review.metrics],
        "findings": findings,
        "sync_map": None if sync_map is None else sync_map.to_dict(),
        "media": None if media is None else dict(media),
        "overall_scores": dict(review.overall_scores or {}),
    }


def review_summary(payload: Mapping[str, Any]) -> dict[str, Any]:
    """Return list-card fields from a presentation payload."""
    return {
        "id": payload["id"],
        "player_id": payload.get("player_id"),
        "match_id": payload["match_id"],
        "participant_id": payload["participant_id"],
        "champion": payload["champion"],
        "role": payload["role"],
        "rank": payload.get("rank"),
        "patch": payload.get("patch"),
        "duration_ms": payload["duration_ms"],
        "result": payload.get("result"),
        "status": payload.get("status"),
        "unpaired_match_timeline": bool(payload.get("unpaired_match_timeline")),
        "fixture_warning": payload.get("fixture_warning"),
        "fixture_id": payload.get("fixture_id"),
        "created_at": payload.get("created_at"),
        "focus_count": len(payload.get("focus_items") or []),
        "has_sync": payload.get("sync_map") is not None,
    }


def save_review_presentation(data_dir: Path, payload: Mapping[str, Any]) -> Path:
    """Write presentation JSON under ``data_dir/reviews``. Assumes data_dir is writable."""
    folder = Path(data_dir) / "reviews"
    folder.mkdir(parents=True, exist_ok=True)
    path = folder / f"{payload['id']}.json"
    path.write_text(json.dumps(payload, indent=2, sort_keys=True), encoding="utf-8")
    return path


def load_review_presentation(data_dir: Path, review_id: str) -> dict[str, Any] | None:
    """Return a saved presentation dict, or None when missing."""
    path = Path(data_dir) / "reviews" / f"{review_id}.json"
    if not path.is_file():
        return None
    parsed: object = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(parsed, dict):
        return None
    return parsed


def list_review_presentations(
    data_dir: Path,
    *,
    include_fixtures: bool = False,
) -> list[dict[str, Any]]:
    """Return summaries for saved presentations, newest first.

    Fixture trial reviews (NA1_fixture_*) are excluded from the normal production list
    unless ``include_fixtures`` is True (developer/E2E tooling).
    """
    folder = Path(data_dir) / "reviews"
    if not folder.is_dir():
        return []
    summaries: list[dict[str, Any]] = []
    for path in folder.glob("*.json"):
        try:
            parsed: object = json.loads(path.read_text(encoding="utf-8"))
        except json.JSONDecodeError:
            continue
        if not isinstance(parsed, dict) or "id" not in parsed:
            continue
        if not include_fixtures and _is_fixture_trial_presentation(parsed):
            continue
        summaries.append(review_summary(parsed))
    summaries.sort(key=lambda item: int(item.get("created_at") or 0), reverse=True)
    return summaries


def purge_fixture_trial_presentations(data_dir: Path) -> int:
    """Delete on-disk fixture trial review JSON only. Returns the number removed.

    Safe for developers clearing old demo clutter. Never deletes non-fixture reviews.
    """
    folder = Path(data_dir) / "reviews"
    if not folder.is_dir():
        return 0
    removed = 0
    for path in list(folder.glob("*.json")):
        try:
            parsed: object = json.loads(path.read_text(encoding="utf-8"))
        except json.JSONDecodeError:
            continue
        if isinstance(parsed, dict) and _is_fixture_trial_presentation(parsed):
            path.unlink(missing_ok=True)
            removed += 1
    return removed


def is_fixture_trial_presentation(payload: Mapping[str, Any]) -> bool:
    """Public helper: True for NA1_fixture_* trial/demo reviews."""
    return _is_fixture_trial_presentation(payload)


def _is_fixture_trial_presentation(payload: Mapping[str, Any]) -> bool:
    """True for NA1_fixture_* trial reviews (Pyke fixtures used during early UI trials)."""
    fixture_id = payload.get("fixture_id")
    if isinstance(fixture_id, str) and fixture_id.startswith("NA1_fixture_"):
        return True
    match_id = payload.get("match_id")
    return isinstance(match_id, str) and match_id.startswith("NA1_fixture_")


def is_quarantined_key(name: str) -> bool:
    """Return True when a field must not be presented as a proven fact."""
    lowered = name.lower()
    return any(key.lower() in lowered for key in _QUARANTINED_KEYS)


def _item_json(
    item: CoachingItem,
    findings: Mapping[str, Finding],
    sync_map: SyncMap | None,
) -> dict[str, Any]:
    stamps = [_timestamp_json(t_ms, sync_map) for t_ms in item.evidence_timestamps_ms]
    return {
        "id": item.id,
        "root_concept_id": item.root_concept_id,
        "rank": item.rank,
        "is_focus": item.is_focus,
        "is_strength": item.is_strength,
        "issue_type": item.issue_type.value,
        "impact_score": item.impact_score,
        "gold_equivalent": item.gold_equivalent,
        "occurrences": item.occurrences,
        "confidence": item.confidence,
        "certainty": item.certainty,
        "title": item.title,
        "body": item.body,
        "the_fix": item.the_fix,
        "next_game_check": item.next_game_check,
        "exemplar_finding_id": item.exemplar_finding_id,
        "finding_ids": list(item.finding_ids),
        "evidence_timestamps_ms": list(item.evidence_timestamps_ms),
        "timestamps": stamps,
        "grouping_reason": item.grouping_reason,
        "cluster_id": item.cluster_id,
        "cost_summary": item.cost_summary,
        "explanation_source": item.explanation_source,
        "llm_fallback": item.llm_fallback,
        "exemplar": _exemplar_preview(item.exemplar_finding_id, findings),
    }


def _finding_json(finding: Finding) -> dict[str, Any]:
    return {
        "id": finding.id,
        "rule_id": finding.rule_id,
        "rule_version": finding.rule_version,
        "concept_id": finding.concept_id,
        "t_ms": finding.t_ms,
        "t_end_ms": finding.t_end_ms,
        "t_mmss": format_mmss(finding.t_ms),
        "severity": finding.severity.value,
        "confidence": finding.confidence,
        "title": finding.title,
        "gold_equivalent": finding.gold_equivalent,
        "outcome": finding.outcome,
        "map_x": finding.map_x,
        "map_y": finding.map_y,
        "explanation": finding.explanation,
        "alternative": finding.alternative,
        "explanation_source": finding.explanation_source,
        "suppressed": finding.suppressed,
        "suppressed_by": finding.suppressed_by,
        "evidence": [_evidence_json(item) for item in finding.evidence],
    }


def _evidence_json(item: Evidence) -> dict[str, Any]:
    quarantined = is_quarantined_key(item.label) or _value_mentions_quarantine(item.value)
    provenance = None
    if item.provenance is not None:
        provenance = {
            "producer": item.provenance.producer,
            "producer_version": item.provenance.producer_version,
            "upstream": list(item.provenance.upstream),
        }
    return {
        "kind": item.kind.value,
        "label": item.label,
        "value": item.value,
        "source": item.source.value,
        "origin_label": evidence_origin_label(item.source),
        "t_ms": item.t_ms,
        "confidence": item.confidence,
        "provenance": provenance,
        "quarantined": quarantined,
    }


def _metric_json(item: MetricSnapshot) -> dict[str, Any]:
    detail = dict(item.detail or {})
    quarantined = is_quarantined_key(item.metric_id) or any(
        is_quarantined_key(str(key)) for key in detail
    )
    return {
        "metric_id": item.metric_id,
        "value": item.value,
        "unit": item.unit,
        "phase": item.phase,
        "confidence": item.confidence,
        "baseline_percentile": item.baseline_percentile,
        "sample_context": item.sample_context,
        "detail": detail,
        "quarantined": quarantined,
    }


def _timestamp_json(t_ms: int, sync_map: SyncMap | None) -> dict[str, Any]:
    target = seek_target(sync_map, t_ms)
    return {
        "t_ms": t_ms,
        "t_mmss": format_mmss(t_ms),
        "t_video_ms": target.t_video_ms,
        "seek_video_ms": target.seek_video_ms,
        "covered": target.covered,
        "uncertain": target.uncertain,
        "reason": target.reason,
    }


def _exemplar_preview(
    finding_id: str | None, findings: Mapping[str, Finding]
) -> dict[str, Any] | None:
    if finding_id is None:
        return None
    finding = findings.get(finding_id)
    if finding is None:
        return None
    return {
        "id": finding.id,
        "t_ms": finding.t_ms,
        "t_mmss": format_mmss(finding.t_ms),
        "severity": finding.severity.value,
        "confidence": finding.confidence,
        "title": finding.title,
    }


def _value_mentions_quarantine(value: object) -> bool:
    if isinstance(value, str):
        return is_quarantined_key(value)
    if isinstance(value, Mapping):
        return any(
            is_quarantined_key(str(key)) or _value_mentions_quarantine(item)
            for key, item in value.items()
        )
    if isinstance(value, Sequence) and not isinstance(value, (str, bytes)):
        return any(_value_mentions_quarantine(item) for item in value)
    return False
