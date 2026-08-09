from __future__ import annotations

import pytest
from riftlens.domain.enums import EvidenceKind, Severity, Source
from riftlens.domain.evidence import Evidence
from riftlens.domain.finding import Finding
from riftlens.domain.ids import new_ulid


def _evidence() -> Evidence:
    return Evidence(
        kind=EvidenceKind.FACT,
        label="test",
        value={"ok": True},
        source=Source.RIOT_TIMELINE,
        t_ms=1000,
        confidence=1.0,
    )


def test_finding_requires_non_empty_evidence() -> None:
    with pytest.raises(ValueError, match="at least one Evidence"):
        Finding(
            id=new_ulid(),
            rule_id="T-001",
            rule_version=1,
            concept_id="LANING",
            t_ms=0,
            severity=Severity.LOW,
            confidence=1.0,
            title="empty",
            evidence=(),
        )


def test_finding_accepts_evidence() -> None:
    finding = Finding(
        id=new_ulid(),
        rule_id="T-001",
        rule_version=1,
        concept_id="LANING",
        t_ms=0,
        severity=Severity.LOW,
        confidence=1.0,
        title="ok",
        evidence=(_evidence(),),
    )
    assert finding.evidence[0].label == "test"
