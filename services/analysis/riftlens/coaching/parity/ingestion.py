"""Manual competitor-output ingestion. No scraping, no undocumented APIs."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from riftlens.coaching.parity.models import (
    PARITY_SCHEMA_VERSION,
    ReferenceEvidenceLevel,
)
from riftlens.coaching.parity.privacy import PrivacyError, assert_no_sensitive

MAX_PARAPHRASE_CHARS = 500
ALLOWED_EVIDENCE = frozenset(
    {
        ReferenceEvidenceLevel.DEMONSTRATED,
        ReferenceEvidenceLevel.VENDOR_CLAIM,
        ReferenceEvidenceLevel.HUMAN_REFERENCE,
        ReferenceEvidenceLevel.UNKNOWN,
    }
)


@dataclass(frozen=True)
class ManualCompetitorReference:
    """User-entered short paraphrase of a competitor output on a situation."""

    reference_id: str
    system_id: str
    product_version: str | None
    observed_on: str
    t_ms: int | None
    paraphrase: str
    evidence_level: ReferenceEvidenceLevel
    confidence: float
    provenance_note: str
    screenshot_ref: str | None = None
    case_id: str | None = None

    def to_dict(self) -> dict[str, Any]:
        payload = {
            "schema_version": PARITY_SCHEMA_VERSION,
            "reference_id": self.reference_id,
            "system_id": self.system_id,
            "product_version": self.product_version,
            "observed_on": self.observed_on,
            "t_ms": self.t_ms,
            "paraphrase": self.paraphrase,
            "evidence_level": self.evidence_level.value,
            "confidence": self.confidence,
            "provenance_note": self.provenance_note,
            "screenshot_ref": self.screenshot_ref,
            "case_id": self.case_id,
        }
        assert_no_sensitive(payload, context=self.reference_id)
        return payload


def record_manual_reference(
    *,
    reference_id: str,
    system_id: str,
    paraphrase: str,
    observed_on: str,
    evidence_level: ReferenceEvidenceLevel | str = ReferenceEvidenceLevel.VENDOR_CLAIM,
    confidence: float = 0.5,
    t_ms: int | None = None,
    product_version: str | None = None,
    provenance_note: str = "manual_user_entry",
    screenshot_ref: str | None = None,
    case_id: str | None = None,
) -> ManualCompetitorReference:
    """Validate and store a short competitor paraphrase.

    Does not fetch URLs, log in, or read undocumented APIs.
    Screenshot refs are local path strings only — bytes are not stored.
    """
    if isinstance(evidence_level, str):
        evidence_level = ReferenceEvidenceLevel(evidence_level)
    if evidence_level not in ALLOWED_EVIDENCE:
        raise ValueError(f"unsupported evidence_level {evidence_level!r}")
    text = paraphrase.strip()
    if not text:
        raise ValueError("paraphrase is required")
    if len(text) > MAX_PARAPHRASE_CHARS:
        raise ValueError(
            f"paraphrase exceeds {MAX_PARAPHRASE_CHARS} chars; store a short paraphrase"
        )
    if not 0.0 <= confidence <= 1.0:
        raise ValueError("confidence must be in [0, 1]")
    if screenshot_ref is not None and screenshot_ref.startswith(("http://", "https://")):
        raise ValueError("screenshot_ref must be a local path, not a URL scrape")
    record = ManualCompetitorReference(
        reference_id=reference_id,
        system_id=system_id,
        product_version=product_version,
        observed_on=observed_on,
        t_ms=t_ms,
        paraphrase=text,
        evidence_level=evidence_level,
        confidence=confidence,
        provenance_note=provenance_note,
        screenshot_ref=screenshot_ref,
        case_id=case_id,
    )
    record.to_dict()
    return record


def reject_automated_ingest_request(kind: str) -> None:
    """Explicit refusal seam for scraping / login automation / private APIs."""
    raise PrivacyError(
        f"RP.0 refuses automated ingest kind={kind!r}; use record_manual_reference"
    )
