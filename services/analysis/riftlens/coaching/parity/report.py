"""Deterministic human reports for the RP.0 CLI."""

from __future__ import annotations

from riftlens.coaching.parity.capabilities import all_capabilities, capability_by_id
from riftlens.coaching.parity.cases import (
    BASELINE_CHAMPION,
    BASELINE_MATCH_ID,
    BASELINE_PARTICIPANT_ID,
    BASELINE_ROLE,
    build_vladimir_baseline_cases,
)
from riftlens.coaching.parity.models import (
    DEFAULT_ACCEPTANCE_POLICY,
    PARITY_SCHEMA_VERSION,
    MatrixCell,
    ParityCapability,
)
from riftlens.coaching.parity.references import (
    MATRIX_SYSTEM_ORDER,
    all_reference_systems,
    assert_vendor_claims_not_demonstrated,
    notes_for_capability,
)
from riftlens.coaching.parity.roadmap import ROADMAP_TRACKS, next_track, top_gaps
from riftlens.coaching.parity.sources import all_input_sources

_HEADER = (
    "==================================================",
    "RIFTLENS RP.0 REFERENCE PARITY",
    f"schema={PARITY_SCHEMA_VERSION}",
    "C.7 remains the coaching quality/safety benchmark.",
    "HUMAN QUALITY VALIDATION = NOT YET PERFORMED",
    "==================================================",
)


def format_clock_ms(t_ms: int) -> str:
    """Format game-clock milliseconds as M:SS or H:MM:SS."""
    total_s = max(0, int(t_ms)) // 1000
    if total_s >= 3600:
        hours, rem = divmod(total_s, 3600)
        minutes, seconds = divmod(rem, 60)
        return f"{hours}:{minutes:02d}:{seconds:02d}"
    minutes, seconds = divmod(total_s, 60)
    return f"{minutes}:{seconds:02d}"


def _display(system_id: str) -> str:
    for item in all_reference_systems():
        if item.system_id == system_id:
            return item.display_name
    return system_id


def render_matrix() -> str:
    """Capability × reference-system matrix plus RiftLens status."""
    assert_vendor_claims_not_demonstrated()
    lines = list(_HEADER)
    lines.append("")
    header = (
        "Capability",
        *(_display(item) for item in MATRIX_SYSTEM_ORDER),
        "RiftLens today",
        "Primary blocker",
        "Proposed RP track",
    )
    lines.append(" | ".join(header))
    lines.append(" | ".join("---" for _ in header))
    for cap in all_capabilities():
        notes = {
            note.system_id: note.matrix_cell().value
            for note in notes_for_capability(cap.capability_id)
        }
        cells = [notes.get(item, MatrixCell.UNKNOWN.value) for item in MATRIX_SYSTEM_ORDER]
        lines.append(
            " | ".join(
                [
                    cap.capability_id,
                    *cells,
                    cap.riftlens_status.value,
                    cap.primary_blocker.replace(" | ", " / "),
                    cap.proposed_rp_track,
                ]
            )
        )
    lines.append("")
    lines.append(
        "Matrix cells: DEMONSTRATED / CLAIMED / PARTIAL / UNKNOWN / N/A. "
        "VENDOR_CLAIM never serializes as DEMONSTRATED."
    )
    return "\n".join(lines) + "\n"


def _gap_block(index: int, cap: ParityCapability) -> list[str]:
    refs = notes_for_capability(cap.capability_id)
    claim_bits = [
        f"{note.system_id}={note.matrix_cell().value}/{note.evidence_level.value}"
        for note in refs
        if note.matrix_cell() is not MatrixCell.NA
    ]
    return [
        f"{index}. {cap.capability_id}",
        f"RiftLens: {cap.riftlens_status.value}",
        f"Priority: {cap.priority().value} (score={cap.priority_score()})",
        f"Reference evidence: {', '.join(claim_bits[:6])}",
        "Missing:",
        *[f"  - {item}" for item in cap.missing_inputs],
        "Unlocks:",
        *[f"  - {item}" for item in (cap.unlocks or ("(none)",))],
        f"Proposed track: {cap.proposed_rp_track}",
        f"Blocker: {cap.primary_blocker}",
        "",
    ]


def render_gaps() -> str:
    """Ranked TOP PARITY GAPS report."""
    lines = list(_HEADER)
    lines.extend(["", "TOP PARITY GAPS", ""])
    gaps = top_gaps()
    for index, cap in enumerate(gaps, start=1):
        lines.extend(_gap_block(index, cap))
    nxt = next_track()
    lines.extend(
        [
            f"NEXT TRACK: {nxt.track_id} — {nxt.name}",
            "Do not start this track from RP.0 automatically.",
            "",
        ]
    )
    return "\n".join(lines)


def render_baseline() -> str:
    """Vladimir PILOT_SELF_REVIEW summary. No PUUID or summoner name."""
    lines = list(_HEADER)
    lines.extend(
        [
            "",
            "BASELINE CASE (PILOT_SELF_REVIEW — not independent expert validation)",
            f"Match: {BASELINE_MATCH_ID}",
            f"Participant: {BASELINE_PARTICIPANT_ID}",
            f"Champion: {BASELINE_CHAMPION}",
            f"Role: {BASELINE_ROLE}",
            "",
        ]
    )
    for case in build_vladimir_baseline_cases():
        human = case.human_adjudication
        rl = case.riftlens_output
        clock = case.clock_label
        if case.t_ms is not None and "–" not in clock:
            clock = f"{clock} ({format_clock_ms(case.t_ms)} / {case.t_ms} ms)"
        lines.append(f"## {case.case_id}  {clock}  {case.subject}")
        lines.append(f"Human: {human.verdict.value}  [{human.label}]")
        lines.append(f"Human reason: {human.reason}")
        if human.reason_code:
            lines.append(f"Human reason_code: {human.reason_code}")
        if rl is not None:
            lines.append(f"RiftLens: {rl.paraphrase}")
            if rl.reason_code:
                lines.append(f"RiftLens reason_code: {rl.reason_code}")
        lines.append(f"Missing: {', '.join(case.missing_inputs) or '(none)'}")
        lines.append(f"Notes: {case.notes}")
        lines.append("")
    return "\n".join(lines)


def render_roadmap() -> str:
    """Tracks with dependencies and acceptance policy."""
    lines = list(_HEADER)
    lines.extend(["", "ROADMAP", ""])
    for track in ROADMAP_TRACKS:
        mark = "  << NEXT" if track.next else ""
        deps = ", ".join(track.depends_on) or "(none)"
        lines.append(f"{track.track_id} {track.name}{mark}")
        lines.append(f"  depends_on: {deps}")
        lines.append(f"  unlocks: {', '.join(track.unlocks_capabilities)}")
        lines.append(f"  {track.rationale}")
        lines.append("")
    policy = DEFAULT_ACCEPTANCE_POLICY
    lines.extend(
        [
            "ACCEPTANCE POLICY",
            "READY requires: " + "; ".join(policy.ready_requires),
            "READY forbids: " + "; ".join(policy.ready_forbids),
            "REFERENCE-COMPARABLE requires: "
            + "; ".join(policy.reference_comparable_requires),
            policy.provisional_note,
            "",
        ]
    )
    return "\n".join(lines)


def render_sources() -> str:
    """Input-source dependency table."""
    lines = list(_HEADER)
    lines.extend(["", "EVIDENCE SOURCE MAP", ""])
    header = (
        "input",
        "MATCH",
        "TIMELINE",
        "ROFL",
        "video",
        "HUD",
        "OCR",
        "detect",
        "track",
        "minimap",
        "VLM",
        "derived",
        "LCD",
        "manual",
    )
    lines.append(" | ".join(header))
    lines.append(" | ".join("---" for _ in header))
    for row in all_input_sources():
        payload = row.to_dict()
        lines.append(
            " | ".join(
                [
                    payload["input_id"],
                    payload["RIOT_MATCH"],
                    payload["RIOT_TIMELINE"],
                    payload["ROFL_METADATA"],
                    payload["video_frames"],
                    payload["HUD_CV"],
                    payload["OCR"],
                    payload["object_detection"],
                    payload["tracking"],
                    payload["minimap"],
                    payload["VLM"],
                    payload["derived_temporal"],
                    payload["live_client"],
                    payload["manual_annotation"],
                ]
            )
        )
        lines.append(f"  {row.notes}")
    lines.append("")
    return "\n".join(lines)


def render_capability(capability_id: str) -> str:
    """One capability dump, or a missing-id message."""
    cap = capability_by_id(capability_id)
    if cap is None:
        return f"unknown capability {capability_id}\n"
    return "\n".join(f"{key}: {value}" for key, value in cap.to_dict().items()) + "\n"
