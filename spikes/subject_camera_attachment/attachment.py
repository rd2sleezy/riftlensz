"""Attachment request/read-back and seek/reattach ranking (spike-only)."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from enum import StrEnum
from typing import Any

from identity import MappingStatus, RosterEntry, classify_readback
from render_state import RenderAttachment, parse_render


class AttachRequestStatus(StrEnum):
    """Whether POST /replay/render stuck the requested attachment."""

    ACCEPTED = "accepted"
    REJECTED = "rejected"
    STICKY_UNCHANGED = "sticky_unchanged"
    PARTIAL = "partial"


class ReattachSequence(StrEnum):
    """Deterministic restore orders to try after seek."""

    ATTACH_THEN_SEEK = "attach_then_seek"
    SEEK_THEN_ATTACH = "seek_then_attach"
    SEEK_WAIT_ATTACH = "seek_wait_attach"


@dataclass(frozen=True)
class AttachAttempt:
    """One POST selection/attach trial and its GET read-back."""

    label: str
    patch: dict[str, Any]
    requested_name: str
    resolved: RenderAttachment
    request_status: AttachRequestStatus
    mapping_status: MappingStatus
    intended_pid: int | None


def attach_patch(
    selection_name: str,
    *,
    camera_attached: bool = True,
    camera_mode: str | None = None,
) -> dict[str, Any]:
    """Return the POST body for a subject-attachment attempt."""
    patch: dict[str, Any] = {
        "selectionName": selection_name,
        "cameraAttached": bool(camera_attached),
    }
    if camera_mode is not None:
        patch["cameraMode"] = camera_mode
    return patch


def classify_request(
    *,
    requested_name: str,
    requested_attached: bool,
    before: RenderAttachment,
    after: RenderAttachment,
) -> AttachRequestStatus:
    """Compare requested selection/attach flags to read-back."""
    name_stuck = after.selection_name == requested_name
    attached_stuck = after.camera_attached is requested_attached
    if requested_attached and attached_stuck and after.selection_name:
        if name_stuck or after.selection_name != before.selection_name:
            return AttachRequestStatus.ACCEPTED
        return AttachRequestStatus.PARTIAL
    if not requested_attached:
        if attached_stuck and (name_stuck or after.selection_name == ""):
            return AttachRequestStatus.ACCEPTED
        if after.selection_name == before.selection_name and after.camera_attached is True:
            return AttachRequestStatus.STICKY_UNCHANGED
        return AttachRequestStatus.PARTIAL
    if after.selection_name == before.selection_name and after.camera_attached is before.camera_attached:
        return AttachRequestStatus.REJECTED
    return AttachRequestStatus.PARTIAL


def evaluate_attempt(
    *,
    label: str,
    patch: Mapping[str, Any],
    before: Mapping[str, Any],
    after: Mapping[str, Any],
    roster: Sequence[RosterEntry],
    intended_pid: int | None,
) -> AttachAttempt:
    """Parse before/after render payloads into an attach attempt record."""
    requested_name = str(patch.get("selectionName", ""))
    requested_attached = bool(patch.get("cameraAttached", False))
    resolved = parse_render(after)
    request_status = classify_request(
        requested_name=requested_name,
        requested_attached=requested_attached,
        before=parse_render(before),
        after=resolved,
    )
    mapping = MappingStatus.UNRESOLVED
    if intended_pid is not None and requested_attached:
        mapping = classify_readback(
            roster=roster,
            intended_pid=intended_pid,
            requested=requested_name,
            resolved=resolved.selection_name,
            camera_attached=bool(resolved.camera_attached),
        )
    return AttachAttempt(
        label=label,
        patch=dict(patch),
        requested_name=requested_name,
        resolved=resolved,
        request_status=request_status,
        mapping_status=mapping,
        intended_pid=intended_pid,
    )


def rank_reattach_sequences(
    *,
    attach_survives_seek: bool,
    seek_clears_attach: bool,
    seek_then_attach_works: bool,
    seek_wait_attach_works: bool,
) -> tuple[ReattachSequence, ...]:
    """Rank restore sequences from observed seek/attach behavior.

    Prefer the shortest sequence that keeps a verified attachment.
    """
    ranked: list[ReattachSequence] = []
    if attach_survives_seek:
        ranked.append(ReattachSequence.ATTACH_THEN_SEEK)
    if seek_then_attach_works:
        ranked.append(ReattachSequence.SEEK_THEN_ATTACH)
    if seek_wait_attach_works and (
        not seek_then_attach_works or seek_clears_attach
    ):
        ranked.append(ReattachSequence.SEEK_WAIT_ATTACH)
    if not ranked and seek_clears_attach:
        ranked.append(ReattachSequence.SEEK_THEN_ATTACH)
    # De-dupe while preserving order.
    seen: set[ReattachSequence] = set()
    out: list[ReattachSequence] = []
    for item in ranked:
        if item in seen:
            continue
        seen.add(item)
        out.append(item)
    return tuple(out)


def nearest_participant(
    camera_xy: tuple[float, float],
    positions: Mapping[int, tuple[float, float]],
) -> tuple[int, float] | None:
    """Return (pid, distance) of the GST participant nearest the camera ground point."""
    best: tuple[int, float] | None = None
    for pid, pos in positions.items():
        dist = ((camera_xy[0] - pos[0]) ** 2 + (camera_xy[1] - pos[1]) ** 2) ** 0.5
        if best is None or dist < best[1]:
            best = (int(pid), float(dist))
    return best
