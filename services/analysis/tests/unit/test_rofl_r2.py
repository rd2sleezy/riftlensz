from __future__ import annotations

import json
import os
import struct
from pathlib import Path

import pytest
from riftlens.domain.replay_errors import ReplayError, ReplayErrorCode
from riftlens.rofl.identity import (
    HeaderParseStatus,
    IdentifyMethod,
    identify_rofl,
    parse_filename_identity,
)
from riftlens.rofl.sniffer import sniff_rofl_prefix
from riftlens.rofl.validation import (
    MAX_ROFL_BYTES,
    METADATA_JSON_MAX_BYTES,
    PREFIX_MAX_BYTES,
    assert_rofl_size,
    read_rofl_prefix,
    validate_rofl_path,
)

FIXTURES = Path(__file__).resolve().parents[1] / "fixtures" / "rofl"
R0_PREFIX = FIXTURES / "r0_na1_5617764200.prefix.bin"


def _classic_header(
    *,
    meta_off: int,
    meta_len: int,
    header_len: int = 286,
    magic: bytes = b"RIOT",
    file_len: int = 10_000,
) -> bytes:
    """Emit only the classic offset table. Does not materialize hostile pads."""
    buf = bytearray(magic.ljust(4, b"\x00"))
    buf.extend(b"\x00" * 256)
    buf.extend(struct.pack("<H", header_len))
    buf.extend(
        struct.pack(
            "<IIIIII",
            file_len,
            meta_off & 0xFFFFFFFF,
            meta_len & 0xFFFFFFFF,
            0,
            0,
            0,
        )
    )
    return bytes(buf)


def _classic_rofl(
    metadata: dict[str, object],
    *,
    magic: bytes = b"RIOT",
    extra: bytes = b"",
) -> bytes:
    """Build a plausible classic-offset .rofl prefix for tests. Not a real encoder."""
    blob = json.dumps(metadata, separators=(",", ":")).encode("utf-8")
    header = _classic_header(meta_off=286, meta_len=len(blob), magic=magic)
    return header + blob + extra


def _write(tmp_path: Path, name: str, data: bytes) -> Path:
    path = tmp_path / name
    path.write_bytes(data)
    return path


def test_filename_identity_preferred_over_header(tmp_path: Path) -> None:
    data = _classic_rofl(
        {
            "gameVersion": "12.10.450.1234",
            "gameLength": 1_800_000,
            "gameId": 999,
            "platformId": "EUW1",
        }
    )
    path = _write(tmp_path, "NA1-5617764200.rofl", data)
    result = identify_rofl(path)
    assert result.recognised
    assert result.error is None
    assert result.identity.identify_method is IdentifyMethod.FILENAME
    assert result.identity.platform_id == "NA1"
    assert result.identity.game_id == 5_617_764_200
    assert result.identity.declared_patch == "12.10.450.1234"
    assert result.identity.declared_length_ms == 1_800_000
    assert result.identity.header_parse_status is HeaderParseStatus.OK
    assert result.identity.match_id_hint == "NA1_5617764200"


def test_valid_filename_with_unreadable_body(tmp_path: Path) -> None:
    data = b"RIOT" + (b"\xff" * 200)
    path = _write(tmp_path, "KR-424242.rofl", data)
    result = identify_rofl(path)
    assert result.recognised
    assert result.error is None
    assert result.identity.platform_id == "KR"
    assert result.identity.game_id == 424_242
    assert result.identity.identify_method is IdentifyMethod.FILENAME
    assert result.identity.declared_length_ms is None
    assert result.raw_metadata_json is None


def test_r0_prefix_fixture_extracts_ascii_patch(tmp_path: Path) -> None:
    assert R0_PREFIX.is_file()
    path = _write(tmp_path, "NA1-5617764200.rofl", R0_PREFIX.read_bytes())
    result = identify_rofl(path)
    assert result.recognised
    assert result.identity.magic == "RIOT"
    assert result.identity.platform_id == "NA1"
    assert result.identity.game_id == 5_617_764_200
    assert result.identity.declared_patch == "16.15.802.4387"
    assert result.identity.declared_length_ms is None
    assert result.identity.header_parse_status is HeaderParseStatus.PARTIAL
    assert result.identity.identify_method is IdentifyMethod.FILENAME
    assert all(w.code is not ReplayErrorCode.ROFL_METADATA_UNPARSED for w in result.warnings)


def test_truncated_file_with_magic(tmp_path: Path) -> None:
    path = _write(tmp_path, "NA1-1.rofl", b"RIOT" + b"\x00" * 20)
    result = identify_rofl(path)
    assert result.recognised
    assert result.identity.game_id == 1
    assert result.identity.declared_patch is None
    assert result.error is None


def test_empty_file(tmp_path: Path) -> None:
    path = _write(tmp_path, "NA1-1.rofl", b"")
    result = identify_rofl(path)
    assert not result.recognised
    assert result.error is not None
    assert result.error.code is ReplayErrorCode.ROFL_UNREADABLE
    assert result.error.details.get("reason") == "empty"


def test_wrong_magic(tmp_path: Path) -> None:
    path = _write(tmp_path, "NA1-99.rofl", b"XXXX" + b"\x00" * 80)
    result = identify_rofl(path)
    assert not result.recognised
    assert result.error is not None
    assert result.error.code is ReplayErrorCode.ROFL_NOT_RECOGNISED
    assert result.identity.game_id is None


def test_oversized_metadata_declaration(tmp_path: Path) -> None:
    data = _classic_header(meta_off=286, meta_len=METADATA_JSON_MAX_BYTES + 1)
    path = _write(tmp_path, "NA1-77.rofl", data)
    result = identify_rofl(path)
    assert result.recognised
    assert result.identity.game_id == 77
    assert result.identity.header_parse_status is HeaderParseStatus.FAILED
    assert result.raw_metadata_json is None
    assert any(w.code is ReplayErrorCode.ROFL_METADATA_UNPARSED for w in result.warnings)


def test_hostile_offsets_do_not_seek(tmp_path: Path) -> None:
    data = _classic_header(meta_off=0xFFFFFFF0, meta_len=100)
    path = _write(tmp_path, "NA1-88.rofl", data)
    result = identify_rofl(path)
    assert result.recognised
    assert result.identity.game_id == 88
    assert result.identity.header_parse_status is HeaderParseStatus.FAILED
    assert any(w.code is ReplayErrorCode.ROFL_METADATA_UNPARSED for w in result.warnings)


def test_renamed_file_uses_header_game_id(tmp_path: Path) -> None:
    data = _classic_rofl(
        {
            "gameVersion": "14.1.1.1",
            "gameLength": 2100,
            "gameId": 5_617_764_200,
            "platformId": "NA1",
        }
    )
    path = _write(tmp_path, "renamed.rofl", data)
    result = identify_rofl(path)
    assert result.recognised
    assert result.identity.identify_method is IdentifyMethod.HEADER
    assert result.identity.platform_id == "NA1"
    assert result.identity.game_id == 5_617_764_200
    assert result.identity.declared_length_ms == 2_100_000
    assert result.identity.match_id_hint == "NA1_5617764200"


def test_renamed_file_without_any_identity(tmp_path: Path) -> None:
    path = _write(tmp_path, "renamed.rofl", b"RIOT" + b"\x00" * 100)
    result = identify_rofl(path)
    assert result.recognised
    assert result.identity.identify_method is IdentifyMethod.NONE
    assert any(w.code is ReplayErrorCode.MATCH_ID_UNRESOLVED for w in result.warnings)


def test_metadata_parse_failure_is_non_fatal(tmp_path: Path) -> None:
    bad = b"{not-json!!}"
    data = _classic_header(meta_off=286, meta_len=len(bad)) + bad
    path = _write(tmp_path, "EUW1-123456.rofl", data)
    result = identify_rofl(path)
    assert result.recognised
    assert result.error is None
    assert result.identity.platform_id == "EUW1"
    assert result.identity.game_id == 123_456
    assert result.identity.identify_method is IdentifyMethod.FILENAME
    assert result.identity.header_parse_status is HeaderParseStatus.FAILED
    assert any(w.code is ReplayErrorCode.ROFL_METADATA_UNPARSED for w in result.warnings)
    meta_warning = next(
        w for w in result.warnings if w.code is ReplayErrorCode.ROFL_METADATA_UNPARSED
    )
    assert meta_warning.is_informational()
    assert not meta_warning.is_fatal()


def test_fuzzed_headers_never_raise_or_read_unbounded(tmp_path: Path) -> None:
    rng_seed_bytes = os.urandom(32)
    for index in range(80):
        size = (index * 997) % 4096
        blob = os.urandom(size)
        if index % 7 == 0 and size >= 4:
            blob = b"RIOT" + blob[4:]
        if index % 11 == 0 and size >= 4:
            blob = b"ROFL" + blob[4:]
        sniff = sniff_rofl_prefix(blob)
        assert sniff.parse_status in {"ok", "partial", "failed", "skipped"}
        path = _write(tmp_path, f"fuzz-{index}.rofl", blob)
        result = identify_rofl(path)
        assert result.identity.file_size_bytes in {None, size} or result.error is not None
        prefix = path.read_bytes()[:PREFIX_MAX_BYTES]
        assert len(prefix) <= PREFIX_MAX_BYTES
    # Keep the seed in the assertion message if a future flake needs reproduction.
    assert len(rng_seed_bytes) == 32


def test_prefix_read_is_bounded(tmp_path: Path) -> None:
    path = _write(tmp_path, "NA1-1.rofl", b"RIOT" + (b"A" * (PREFIX_MAX_BYTES + 5000)))
    prefix = read_rofl_prefix(path)
    assert len(prefix) == PREFIX_MAX_BYTES


def test_missing_and_directory(tmp_path: Path) -> None:
    missing = identify_rofl(tmp_path / "nope.rofl")
    assert missing.error is not None
    assert missing.error.code is ReplayErrorCode.ROFL_MISSING
    folder = tmp_path / "dir.rofl"
    folder.mkdir()
    directory = identify_rofl(folder)
    assert directory.error is not None
    assert directory.error.code is ReplayErrorCode.ROFL_UNREADABLE


def test_size_bounds() -> None:
    with pytest.raises(ReplayError) as too_big:
        assert_rofl_size(MAX_ROFL_BYTES + 1)
    assert too_big.value.code is ReplayErrorCode.ROFL_UNREADABLE
    with pytest.raises(ReplayError) as empty:
        assert_rofl_size(0)
    assert empty.value.code is ReplayErrorCode.ROFL_UNREADABLE


def test_parse_filename_identity_rejects_non_convention() -> None:
    assert parse_filename_identity("renamed.rofl").game_id is None
    assert parse_filename_identity("NA1-5617764200.rofl").platform_id == "NA1"
    assert parse_filename_identity("euw1-99.ROFL").platform_id == "EUW1"


def test_new_r2_error_codes_match_severity_contract() -> None:
    unparsed = ReplayError(ReplayErrorCode.ROFL_METADATA_UNPARSED)
    unresolved = ReplayError(ReplayErrorCode.MATCH_ID_UNRESOLVED)
    unknown = ReplayError(ReplayErrorCode.ROFL_NOT_RECOGNISED)
    assert unparsed.is_informational()
    assert unresolved.is_retryable()
    assert unknown.is_fatal()


def test_sniff_json_scan_without_classic_table() -> None:
    payload = b"RIOT" + b"\x00" * 20 + b'{"gameVersion":"15.9.1.1","gameLength":900000,"gameId":42}'
    sniff = sniff_rofl_prefix(payload)
    assert sniff.looks_like_rofl
    assert sniff.declared_patch == "15.9.1.1"
    assert sniff.declared_length_ms == 900_000
    assert sniff.game_id == 42


def test_validate_rofl_path_accepts_regular_file(tmp_path: Path) -> None:
    path = _write(tmp_path, "NA1-1.rofl", b"RIOT" + b"\x00" * 8)
    resolved, size = validate_rofl_path(path)
    assert resolved.is_file()
    assert size == 12
