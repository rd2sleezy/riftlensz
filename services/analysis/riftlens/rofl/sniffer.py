from __future__ import annotations

import json
import re
import struct
from dataclasses import dataclass
from json import JSONDecoder
from typing import Any

from riftlens.domain.replay_errors import ReplayErrorCode
from riftlens.rofl.validation import METADATA_JSON_MAX_BYTES, ROFL_MAGICS

_ASCII_PATCH_WINDOW = 512
_ASCII_PATCH_RE = re.compile(rb"(?<![\d.])(\d{1,2}\.\d{1,2}\.\d{1,5}\.\d{1,6})(?![\d.])")
_CLASSIC_MIN_BYTES = 286
_CLASSIC_HEADER_LEN_MIN = 280
_CLASSIC_HEADER_LEN_MAX = 4096
_JSON_SCAN_ATTEMPTS = 32
_MAX_GAME_ID = (2**63) - 1
_MAX_MATCH_MS = 5 * 60 * 60 * 1000
_JSON_DECODER = JSONDecoder()


@dataclass(frozen=True)
class HeaderSniff:
    """Pure prefix sniff. Every field is optional; parse failure is never an exception."""

    magic: str | None
    looks_like_rofl: bool
    declared_patch: str | None
    declared_length_ms: int | None
    game_id: int | None
    platform_id: str | None
    parse_status: str
    raw_metadata_json: str | None
    warning_codes: tuple[ReplayErrorCode, ...]


def sniff_rofl_prefix(data: bytes) -> HeaderSniff:
    """Sniff a bounded prefix. Never raises, never reads past ``len(data)``."""
    try:
        return _sniff_rofl_prefix(data)
    except Exception:  # noqa: BLE001 — fuzzed headers must degrade
        return _failed_sniff(_magic_text(data[:4]) if data else None)


def _sniff_rofl_prefix(data: bytes) -> HeaderSniff:
    """Run magic + optional metadata hypotheses. Assumes ``data`` is already bounded."""
    magic = _magic_text(data[:4]) if len(data) >= 4 else (_magic_text(data) if data else None)
    looks_like = len(data) >= 4 and data[:4] in ROFL_MAGICS
    if not looks_like:
        return HeaderSniff(
            magic=magic,
            looks_like_rofl=False,
            declared_patch=None,
            declared_length_ms=None,
            game_id=None,
            platform_id=None,
            parse_status="skipped",
            raw_metadata_json=None,
            warning_codes=(),
        )
    classic = _try_classic_metadata(data)
    scanned = None if classic.status == "ok" else _try_json_scan(data)
    ascii_patch = _try_ascii_patch(data)
    metadata = classic.fields if classic.status == "ok" else scanned
    warning_codes = classic.warnings
    if metadata is None and scanned is None and classic.status == "failed":
        warning_codes = classic.warnings
    elif metadata is None and classic.status != "failed":
        # ASCII-only enrichment is expected on modern 16.x files (R.0).
        warning_codes = ()
    patch = _coalesce_patch(metadata, ascii_patch)
    length_ms = metadata.declared_length_ms if metadata is not None else None
    parse_status = _status_for(classic.status, metadata, patch, length_ms)
    if parse_status == "failed" and ReplayErrorCode.ROFL_METADATA_UNPARSED not in warning_codes:
        warning_codes = (*warning_codes, ReplayErrorCode.ROFL_METADATA_UNPARSED)
    if classic.status == "ok":
        raw_json = classic.raw_json
    elif metadata is not None:
        raw_json = metadata.raw_json
    else:
        raw_json = None
    return HeaderSniff(
        magic=magic,
        looks_like_rofl=True,
        declared_patch=patch,
        declared_length_ms=length_ms,
        game_id=metadata.game_id if metadata is not None else None,
        platform_id=metadata.platform_id if metadata is not None else None,
        parse_status=parse_status,
        raw_metadata_json=raw_json,
        warning_codes=warning_codes,
    )


@dataclass(frozen=True)
class _MetaFields:
    declared_patch: str | None
    declared_length_ms: int | None
    game_id: int | None
    platform_id: str | None
    raw_json: str | None


@dataclass(frozen=True)
class _ClassicAttempt:
    status: str  # ok | failed | skipped
    fields: _MetaFields | None
    raw_json: str | None
    warnings: tuple[ReplayErrorCode, ...]


def _try_classic_metadata(data: bytes) -> _ClassicAttempt:
    """Hypothesis: RIOT/ROFL + 256-byte signature + little-endian offset table.

    Not an authority. Followed only when lengths look plausible and stay in-prefix.
    """
    if len(data) < _CLASSIC_MIN_BYTES:
        return _ClassicAttempt("skipped", None, None, ())
    header_len = struct.unpack_from("<H", data, 260)[0]
    file_len, meta_off, meta_len, _ph_off, _ph_len, _payload_off = struct.unpack_from(
        "<IIIIII", data, 262
    )
    if not _classic_plausible(header_len, file_len, meta_off, meta_len):
        return _ClassicAttempt("skipped", None, None, ())
    if meta_len > METADATA_JSON_MAX_BYTES:
        return _ClassicAttempt(
            "failed",
            None,
            None,
            (ReplayErrorCode.ROFL_METADATA_UNPARSED,),
        )
    blob = _bounded_slice(data, meta_off, meta_len)
    if blob is None:
        return _ClassicAttempt(
            "failed",
            None,
            None,
            (ReplayErrorCode.ROFL_METADATA_UNPARSED,),
        )
    parsed = _parse_metadata_object(blob)
    if parsed is None:
        return _ClassicAttempt(
            "failed",
            None,
            None,
            (ReplayErrorCode.ROFL_METADATA_UNPARSED,),
        )
    return _ClassicAttempt("ok", parsed, parsed.raw_json, ())


def _classic_plausible(header_len: int, file_len: int, meta_off: int, meta_len: int) -> bool:
    """Return True when the offset table looks intentional rather than random bytes."""
    if header_len < _CLASSIC_HEADER_LEN_MIN or header_len > _CLASSIC_HEADER_LEN_MAX:
        return False
    if meta_len == 0 or meta_off < 4:
        return False
    if file_len != 0 and file_len < header_len:
        return False
    return True


def _try_json_scan(data: bytes) -> _MetaFields | None:
    """Scan the prefix for an ASCII JSON object. Ignores ``{`` bytes inside binary."""
    start = 0
    for _ in range(_JSON_SCAN_ATTEMPTS):
        idx = data.find(b"{", start)
        if idx < 0:
            return None
        if _looks_like_ascii_json_start(data, idx):
            window = data[idx : idx + METADATA_JSON_MAX_BYTES]
            parsed = _parse_metadata_object(window)
            if parsed is not None:
                return parsed
        start = idx + 1
    return None


def _try_ascii_patch(data: bytes) -> str | None:
    """Return a 4-part version string from the first 512 bytes, as R.0 observed."""
    window = data[:_ASCII_PATCH_WINDOW]
    match = _ASCII_PATCH_RE.search(window)
    if match is None:
        return None
    return match.group(1).decode("ascii")


def _looks_like_ascii_json_start(data: bytes, idx: int) -> bool:
    """Return True when bytes after ``idx`` look like JSON, not random binary."""
    sample = data[idx : idx + 32]
    if len(sample) < 2 or sample[0:1] != b"{":
        return False
    printable = sum(1 for byte in sample if 32 <= byte < 127 or byte in (9, 10, 13))
    return printable * 4 >= len(sample) * 3


def _parse_metadata_object(blob: bytes) -> _MetaFields | None:
    """Parse one JSON object from ``blob``. Assumes size is already capped."""
    text = _ascii_json_text(blob)
    if text is None:
        return None
    try:
        obj, _end = _JSON_DECODER.raw_decode(text)
    except (ValueError, RecursionError, MemoryError):
        return None
    if not isinstance(obj, dict):
        return None
    raw = json.dumps(obj, ensure_ascii=True, separators=(",", ":"))
    if len(raw) > METADATA_JSON_MAX_BYTES:
        raw = raw[:METADATA_JSON_MAX_BYTES]
    return _fields_from_json(obj, raw)


def _ascii_json_text(blob: bytes) -> str | None:
    """Decode a JSON slice as UTF-8/ASCII. Binary blobs return None."""
    try:
        text = blob.decode("utf-8")
    except UnicodeDecodeError:
        try:
            text = blob.decode("ascii")
        except UnicodeDecodeError:
            return None
    stripped = text.lstrip()
    if not stripped.startswith("{"):
        return None
    return stripped


def _fields_from_json(obj: dict[str, Any], raw: str) -> _MetaFields:
    """Pull identity fields from top-level keys only. Does not walk stats payloads."""
    version = _as_patch(_lookup(obj, "gameVersion", "game_version", "version"))
    length_ms = _as_length_ms(_lookup(obj, "gameLength", "game_length", "gameLengthMs"))
    game_id = _as_game_id(_lookup(obj, "gameId", "game_id"))
    platform = _as_platform(_lookup(obj, "platformId", "platform_id", "platformID"))
    return _MetaFields(
        declared_patch=version,
        declared_length_ms=length_ms,
        game_id=game_id,
        platform_id=platform,
        raw_json=raw,
    )


def _lookup(obj: dict[str, Any], *names: str) -> Any:
    """Return the first matching key, case-insensitive. Assumes keys are strings."""
    lower = {str(key).lower(): value for key, value in obj.items()}
    for name in names:
        if name.lower() in lower:
            return lower[name.lower()]
    return None


def _as_patch(value: Any) -> str | None:
    """Return a short patch/version string. Rejects huge or non-stringy values."""
    if isinstance(value, str) and 0 < len(value) <= 64:
        return value.strip() or None
    return None


def _as_length_ms(value: Any) -> int | None:
    """Return a plausible match length in ms. Seconds-sized values are converted."""
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return None
    number = int(value)
    if 60_000 <= number <= _MAX_MATCH_MS:
        return number
    if 30 <= number <= 18_000:
        return number * 1000
    return None


def _as_game_id(value: Any) -> int | None:
    """Return a positive game id that fits a signed BIGINT."""
    if isinstance(value, bool):
        return None
    if isinstance(value, int):
        number = value
    elif isinstance(value, str) and value.isdigit():
        number = int(value)
    else:
        return None
    if 0 < number <= _MAX_GAME_ID:
        return number
    return None


def _as_platform(value: Any) -> str | None:
    """Return an uppercase platform id such as ``NA1``."""
    if isinstance(value, str) and re.fullmatch(r"[A-Za-z0-9]{2,10}", value):
        return value.upper()
    return None


def _coalesce_patch(metadata: _MetaFields | None, ascii_patch: str | None) -> str | None:
    """Prefer structured JSON version, then the R.0 ASCII scan."""
    if metadata is not None and metadata.declared_patch:
        return metadata.declared_patch
    return ascii_patch


def _status_for(
    classic_status: str,
    metadata: _MetaFields | None,
    patch: str | None,
    length_ms: int | None,
) -> str:
    """Classify header parse quality. ``failed`` stays non-fatal for callers."""
    if classic_status == "failed" and metadata is None and patch is None:
        return "failed"
    if metadata is not None and (patch or length_ms is not None or metadata.game_id is not None):
        if metadata.declared_patch and metadata.declared_length_ms is not None:
            return "ok"
        return "partial"
    if patch:
        return "partial"
    if classic_status == "failed":
        return "failed"
    return "skipped"


def _bounded_slice(data: bytes, offset: int, length: int) -> bytes | None:
    """Return ``data[offset:offset+length]`` or None. Never seeks; rejects wrap/OOB."""
    if offset < 0 or length < 0:
        return None
    end = offset + length
    if end < offset or offset > len(data) or end > len(data):
        return None
    return data[offset:end]


def _magic_text(raw: bytes) -> str | None:
    """Return a short Latin-1 magic preview. Assumes at most a few bytes."""
    if not raw:
        return None
    return raw[:4].decode("latin-1")


def _failed_sniff(magic: str | None) -> HeaderSniff:
    """Return a failed sniff after an unexpected exception inside the sniffer."""
    return HeaderSniff(
        magic=magic,
        looks_like_rofl=magic in {"RIOT", "ROFL"},
        declared_patch=None,
        declared_length_ms=None,
        game_id=None,
        platform_id=None,
        parse_status="failed",
        raw_metadata_json=None,
        warning_codes=(ReplayErrorCode.ROFL_METADATA_UNPARSED,),
    )
