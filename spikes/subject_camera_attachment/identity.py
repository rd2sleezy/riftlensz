"""Participant → Replay API selection mapping (spike-only; fail-closed).

Champion-name attachment is not participant identity. A selection token is
usable for a subject only when it uniquely reverse-maps to that pid.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from enum import StrEnum


class SelectionIdentifierKind(StrEnum):
    """How a selection string was derived from MATCH-V5 / LCD identity."""

    CHAMPION_DISPLAY = "champion_display"
    RIOT_DISPLAY = "riot_display"
    RIOT_DISPLAY_TAGGED = "riot_display_tagged"
    SUMMONER = "summoner"
    PARTICIPANT_ID_STRING = "participant_id_string"


class MappingStatus(StrEnum):
    """Whether pid → selection → pid is proven, not merely requested."""

    UNIQUE = "unique"
    AMBIGUOUS = "ambiguous"
    UNRESOLVED = "unresolved"
    FAIL_CLOSED = "fail_closed"


@dataclass(frozen=True)
class RosterEntry:
    """One MATCH-V5 participant used for selection uniqueness checks."""

    participant_id: int
    champion_name: str
    riot_id_game_name: str | None = None
    riot_id_tagline: str | None = None
    summoner_name: str | None = None


@dataclass(frozen=True)
class SelectionCandidate:
    """One identifier that may be POSTed as ``selectionName``."""

    kind: SelectionIdentifierKind
    value: str
    participant_id: int
    unique: bool


@dataclass(frozen=True)
class SubjectSelectionPlan:
    """Fail-closed plan for attaching to ``participant_id``."""

    participant_id: int
    status: MappingStatus
    preferred: tuple[SelectionCandidate, ...]
    rejected_reason: str | None = None

    @property
    def attach_allowed(self) -> bool:
        return self.status is MappingStatus.UNIQUE and bool(self.preferred)


def _norm(value: str | None) -> str:
    return "" if value is None else value.strip().casefold()


def _nonempty(value: str | None) -> str | None:
    text = (value or "").strip()
    return text or None


def roster_tokens(entry: RosterEntry) -> tuple[str, ...]:
    """Return casefolded identity tokens for reverse lookup."""
    tokens: list[str] = []
    for raw in (
        entry.champion_name,
        entry.riot_id_game_name,
        entry.summoner_name,
    ):
        n = _norm(raw)
        if n:
            tokens.append(n)
    tagged = riot_tagged(entry)
    if tagged is not None:
        tokens.append(_norm(tagged))
    return tuple(dict.fromkeys(tokens))


def riot_tagged(entry: RosterEntry) -> str | None:
    """Return ``gameName#tagline`` when both parts exist."""
    name = _nonempty(entry.riot_id_game_name)
    tag = _nonempty(entry.riot_id_tagline)
    if name is None or tag is None:
        return None
    return f"{name}#{tag}"


def reverse_lookup(roster: Sequence[RosterEntry], name: str) -> tuple[RosterEntry, ...]:
    """Match a Replay API selection string against roster tokens (case-insensitive)."""
    needle = _norm(name)
    if not needle:
        return ()
    return tuple(entry for entry in roster if needle in roster_tokens(entry))


def token_is_unique(roster: Sequence[RosterEntry], name: str) -> bool:
    """Return True when ``name`` reverse-maps to exactly one participant."""
    return len(reverse_lookup(roster, name)) == 1


def champion_duplicate_pids(roster: Sequence[RosterEntry], champion_name: str) -> tuple[int, ...]:
    """Return pids sharing ``champion_name`` (case-insensitive)."""
    needle = _norm(champion_name)
    return tuple(
        entry.participant_id for entry in roster if _norm(entry.champion_name) == needle
    )


def candidates_for(entry: RosterEntry, roster: Sequence[RosterEntry]) -> tuple[SelectionCandidate, ...]:
    """Build selection candidates in preference order. Uniqueness is per-token."""
    out: list[SelectionCandidate] = []
    tagged = riot_tagged(entry)
    values: list[tuple[SelectionIdentifierKind, str | None]] = [
        (SelectionIdentifierKind.RIOT_DISPLAY, _nonempty(entry.riot_id_game_name)),
        (SelectionIdentifierKind.RIOT_DISPLAY_TAGGED, tagged),
        (SelectionIdentifierKind.SUMMONER, _nonempty(entry.summoner_name)),
        (SelectionIdentifierKind.CHAMPION_DISPLAY, _nonempty(entry.champion_name)),
        (SelectionIdentifierKind.PARTICIPANT_ID_STRING, str(entry.participant_id)),
    ]
    seen: set[str] = set()
    for kind, value in values:
        if value is None:
            continue
        key = _norm(value)
        if key in seen:
            continue
        seen.add(key)
        out.append(
            SelectionCandidate(
                kind=kind,
                value=value,
                participant_id=entry.participant_id,
                unique=token_is_unique(roster, value),
            )
        )
    return tuple(out)


def plan_subject_selection(
    roster: Sequence[RosterEntry],
    participant_id: int,
) -> SubjectSelectionPlan:
    """Return attach identifiers that uniquely reverse-map to ``participant_id``.

    Duplicate champion names fail closed for champion-display tokens. A unique
    riot/summoner token may still be allowed. Participant-id strings are never
    preferred: they are listed only for live probing.
    """
    entry = next((item for item in roster if item.participant_id == participant_id), None)
    if entry is None:
        return SubjectSelectionPlan(
            participant_id=participant_id,
            status=MappingStatus.UNRESOLVED,
            preferred=(),
            rejected_reason="participant_not_in_roster",
        )
    all_candidates = candidates_for(entry, roster)
    usable = tuple(
        item
        for item in all_candidates
        if item.unique and item.kind is not SelectionIdentifierKind.PARTICIPANT_ID_STRING
    )
    champ_pids = champion_duplicate_pids(roster, entry.champion_name)
    if len(champ_pids) > 1 and not usable:
        return SubjectSelectionPlan(
            participant_id=participant_id,
            status=MappingStatus.FAIL_CLOSED,
            preferred=(),
            rejected_reason="duplicate_champion_no_unique_player_token",
        )
    if not usable:
        return SubjectSelectionPlan(
            participant_id=participant_id,
            status=MappingStatus.AMBIGUOUS,
            preferred=(),
            rejected_reason="no_unique_selection_token",
        )
    return SubjectSelectionPlan(
        participant_id=participant_id,
        status=MappingStatus.UNIQUE,
        preferred=usable,
    )


def classify_readback(
    *,
    roster: Sequence[RosterEntry],
    intended_pid: int,
    requested: str,
    resolved: str,
    camera_attached: bool,
) -> MappingStatus:
    """Classify POST selection → GET read-back against the intended pid.

    A sticky previous selection does not count as accepting an invalid request.
    """
    if not camera_attached:
        return MappingStatus.UNRESOLVED
    if not resolved.strip():
        return MappingStatus.UNRESOLVED
    if requested.strip():
        requested_matches = reverse_lookup(roster, requested)
        if not requested_matches:
            return MappingStatus.UNRESOLVED
        if len(requested_matches) > 1:
            return MappingStatus.AMBIGUOUS
        if requested_matches[0].participant_id != intended_pid:
            return MappingStatus.FAIL_CLOSED
    matches = reverse_lookup(roster, resolved)
    if len(matches) == 0:
        return MappingStatus.UNRESOLVED
    if len(matches) > 1:
        return MappingStatus.AMBIGUOUS
    if matches[0].participant_id != intended_pid:
        return MappingStatus.FAIL_CLOSED
    return MappingStatus.UNIQUE
