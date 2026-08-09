from __future__ import annotations

import re
from dataclasses import dataclass
from enum import StrEnum
from pathlib import Path

from riftlens.domain.replay_errors import ReplayError, ReplayErrorCode
from riftlens.rofl.sniffer import HeaderSniff, sniff_rofl_prefix
from riftlens.rofl.validation import PREFIX_MAX_BYTES, read_rofl_prefix, validate_rofl_path

_FILENAME_RE = re.compile(
    r"^(?P<platform>[A-Za-z0-9]{2,10})-(?P<game_id>\d{1,20})\.rofl$",
    re.IGNORECASE,
)
_MAX_GAME_ID = (2**63) - 1


class IdentifyMethod(StrEnum):
    """How platformId/gameId were established. LCU and user picker are later work orders."""

    FILENAME = "filename"
    HEADER = "header"
    NONE = "none"


class HeaderParseStatus(StrEnum):
    """Outcome of bounded header sniffing. ``failed`` is never fatal to identification."""

    OK = "ok"
    PARTIAL = "partial"
    FAILED = "failed"
    SKIPPED = "skipped"


@dataclass(frozen=True)
class FilenameIdentity:
    """Filename-convention fields. Either both present or the parse missed."""

    platform_id: str | None
    game_id: int | None


@dataclass(frozen=True)
class RoflIdentity:
    """Best-effort .rofl identity. Every extracted field may be None."""

    platform_id: str | None
    game_id: int | None
    declared_patch: str | None
    declared_length_ms: int | None
    identify_method: IdentifyMethod
    header_parse_status: HeaderParseStatus
    file_size_bytes: int | None = None
    magic: str | None = None

    @property
    def match_id_hint(self) -> str | None:
        """Return ``PLATFORM_gameId`` when both parts exist. Does not query MATCH-V5."""
        if self.platform_id and self.game_id is not None:
            return f"{self.platform_id}_{self.game_id}"
        return None


@dataclass(frozen=True)
class RoflIdentificationResult:
    """Validate + identify outcome. ``error`` is set only for fatal path/magic failures."""

    recognised: bool
    identity: RoflIdentity
    error: ReplayError | None
    warnings: tuple[ReplayError, ...]
    raw_metadata_json: str | None = None

    def to_dict(self) -> dict[str, object]:
        """Return a JSON-ready mapping. Assumes the result was already constructed."""
        error = self.error
        return {
            "recognised": self.recognised,
            "identity": {
                "platform_id": self.identity.platform_id,
                "game_id": self.identity.game_id,
                "declared_patch": self.identity.declared_patch,
                "declared_length_ms": self.identity.declared_length_ms,
                "identify_method": self.identity.identify_method.value,
                "header_parse_status": self.identity.header_parse_status.value,
                "file_size_bytes": self.identity.file_size_bytes,
                "magic": self.identity.magic,
                "match_id_hint": self.identity.match_id_hint,
            },
            "error": None
            if error is None
            else {"code": error.code.value, "message": str(error), "details": dict(error.details)},
            "warnings": [
                {"code": item.code.value, "message": str(item), "details": dict(item.details)}
                for item in self.warnings
            ],
            "raw_metadata_json": self.raw_metadata_json,
        }


def parse_filename_identity(name: str) -> FilenameIdentity:
    """Return platformId/gameId from ``PLATFORM-gameId.rofl``. Assumes ``name`` is a basename."""
    match = _FILENAME_RE.fullmatch(Path(name).name)
    if match is None:
        return FilenameIdentity(platform_id=None, game_id=None)
    game_id = int(match.group("game_id"))
    if game_id <= 0 or game_id > _MAX_GAME_ID:
        return FilenameIdentity(platform_id=None, game_id=None)
    return FilenameIdentity(platform_id=match.group("platform").upper(), game_id=game_id)


def identify_rofl(path: str | Path) -> RoflIdentificationResult:
    """Validate and identify a .rofl path. Never raises for malformed file contents."""
    try:
        resolved, size_bytes = validate_rofl_path(Path(path))
        prefix = read_rofl_prefix(resolved, max_bytes=PREFIX_MAX_BYTES)
        if len(prefix) > PREFIX_MAX_BYTES:
            prefix = prefix[:PREFIX_MAX_BYTES]
        sniff = sniff_rofl_prefix(prefix)
        filename = parse_filename_identity(resolved.name)
        return _combine(sniff, filename, size_bytes)
    except ReplayError as exc:
        return _fatal_result(exc)
    except Exception as exc:  # noqa: BLE001 — adversarial files must not escape
        return _fatal_result(
            ReplayError(
                ReplayErrorCode.ROFL_UNREADABLE,
                details={"reason": "unexpected", "error": type(exc).__name__},
            )
        )


def _combine(
    sniff: HeaderSniff,
    filename: FilenameIdentity,
    size_bytes: int,
) -> RoflIdentificationResult:
    """Merge filename then header enrichment. Assumes sniffing already bounded its reads."""
    if not sniff.looks_like_rofl:
        error = ReplayError(
            ReplayErrorCode.ROFL_NOT_RECOGNISED,
            details={"reason": "magic_mismatch", "magic": sniff.magic},
        )
        return RoflIdentificationResult(
            recognised=False,
            identity=_empty_identity(size_bytes, sniff.magic),
            error=error,
            warnings=(),
            raw_metadata_json=None,
        )
    platform_id = filename.platform_id or sniff.platform_id
    game_id = filename.game_id if filename.game_id is not None else sniff.game_id
    if filename.game_id is not None:
        method = IdentifyMethod.FILENAME
    elif sniff.game_id is not None:
        method = IdentifyMethod.HEADER
    else:
        method = IdentifyMethod.NONE
    warnings = _warnings_from_sniff(sniff, method)
    identity = RoflIdentity(
        platform_id=platform_id,
        game_id=game_id,
        declared_patch=sniff.declared_patch,
        declared_length_ms=sniff.declared_length_ms,
        identify_method=method,
        header_parse_status=HeaderParseStatus(sniff.parse_status),
        file_size_bytes=size_bytes,
        magic=sniff.magic,
    )
    return RoflIdentificationResult(
        recognised=True,
        identity=identity,
        error=None,
        warnings=warnings,
        raw_metadata_json=sniff.raw_metadata_json,
    )


def _warnings_from_sniff(sniff: HeaderSniff, method: IdentifyMethod) -> tuple[ReplayError, ...]:
    """Return non-fatal issues. Assumes recognition already succeeded."""
    warnings: list[ReplayError] = []
    for code in sniff.warning_codes:
        warnings.append(ReplayError(code, details={"parse_status": sniff.parse_status}))
    if method is IdentifyMethod.NONE:
        warnings.append(
            ReplayError(
                ReplayErrorCode.MATCH_ID_UNRESOLVED,
                details={"suggested_action": "ask_user_to_pick_match"},
            )
        )
    return tuple(warnings)


def _empty_identity(size_bytes: int | None, magic: str | None) -> RoflIdentity:
    """Return an empty identity. Assumes the file was not recognised as a replay."""
    return RoflIdentity(
        platform_id=None,
        game_id=None,
        declared_patch=None,
        declared_length_ms=None,
        identify_method=IdentifyMethod.NONE,
        header_parse_status=HeaderParseStatus.SKIPPED,
        file_size_bytes=size_bytes,
        magic=magic,
    )


def _fatal_result(error: ReplayError) -> RoflIdentificationResult:
    """Wrap a fatal path error. Assumes identification must not continue."""
    return RoflIdentificationResult(
        recognised=False,
        identity=_empty_identity(
            size_bytes=_detail_int(error, "size_bytes"),
            magic=None,
        ),
        error=error,
        warnings=(),
        raw_metadata_json=None,
    )


def _detail_int(error: ReplayError, key: str) -> int | None:
    """Return an int detail or None. Assumes details are untrusted."""
    value = error.details.get(key)
    return value if isinstance(value, int) else None
