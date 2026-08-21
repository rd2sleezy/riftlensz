"""Teaching readiness evaluation against playbooks and capability gates."""

from __future__ import annotations

from collections.abc import Sequence

from riftlens.coaching.concepts.capabilities import capability_for
from riftlens.coaching.concepts.models import CapabilityStatus
from riftlens.coaching.teaching.models import (
    AlternativeCertainty,
    Measurability,
    ReasonCode,
    TeachingReadiness,
    TeachingSpecificity,
)
from riftlens.coaching.teaching.playbooks import (
    BLOCKED_TEACHING_CONCEPTS,
    get_concept_playbook,
    implemented_playbook_ids,
)


def evaluate_teaching_readiness(
    concept_ids: Sequence[str] | None = None,
) -> tuple[TeachingReadiness, ...]:
    """Return readiness rows for requested (or all implemented + blocked) concepts."""
    if concept_ids is None:
        ids = list(implemented_playbook_ids()) + sorted(BLOCKED_TEACHING_CONCEPTS)
    else:
        ids = list(concept_ids)

    rows: list[TeachingReadiness] = []
    for concept_id in ids:
        playbook = get_concept_playbook(concept_id)
        if concept_id in BLOCKED_TEACHING_CONCEPTS or playbook is None:
            limitations: list[str] = []
            if concept_id == "wave.management":
                limitations.append("CAP-WAVE-ACTION")
            elif concept_id == "mechanics.execution":
                limitations.append("CAP-MECHANICAL-EXECUTION")
            elif concept_id == "combat.summoner_usage":
                limitations.append("CAP-SUMMONER-USAGE")
            elif concept_id == "risk.information_discipline":
                limitations.append("CAP-JUNGLE-INFORMATION")
            rows.append(
                TeachingReadiness(
                    concept_id=concept_id,
                    playbook_exists=False,
                    teaching_specificity_supported=TeachingSpecificity.UNAVAILABLE,
                    alternative_level=AlternativeCertainty.UNAVAILABLE,
                    recognition_cue_available=False,
                    drill_available=False,
                    objective_measurability=Measurability.NOT_MEASURABLE,
                    capability_limitations=tuple(limitations),
                    forbidden_claims=(
                        "FREEZE_RECOMMENDATION",
                        "SLOW_PUSH_RECOMMENDATION",
                        "MECHANICAL_CORRECTION",
                        "FLASH_CORRECTION",
                        "WARD_QUALITY_CLAIM",
                    ),
                    reason_codes=(
                        ReasonCode("PLAYBOOK_UNAVAILABLE_OR_BLOCKED", concept_id),
                    ),
                )
            )
            continue

        caps: list[str] = []
        for cap_id in playbook.required_capabilities:
            cap = capability_for(cap_id)
            if cap is not None and cap.readiness is CapabilityStatus.BLOCKED:
                caps.append(cap_id)

        rows.append(
            TeachingReadiness(
                concept_id=concept_id,
                playbook_exists=True,
                teaching_specificity_supported=playbook.max_specificity,
                alternative_level=playbook.alternative_certainty,
                recognition_cue_available=True,
                drill_available=True,
                objective_measurability=playbook.objective_template.measurability,
                capability_limitations=tuple(caps),
                forbidden_claims=playbook.forbidden_claims,
                reason_codes=(ReasonCode("PLAYBOOK_CURATED", concept_id),),
            )
        )
    return tuple(rows)
