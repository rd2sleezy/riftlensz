from __future__ import annotations

from riftlens.rofl.identity import (
    FilenameIdentity,
    HeaderParseStatus,
    IdentifyMethod,
    RoflIdentificationResult,
    RoflIdentity,
    identify_rofl,
    parse_filename_identity,
)
from riftlens.rofl.sniffer import HeaderSniff, sniff_rofl_prefix
from riftlens.rofl.validation import (
    MAX_ROFL_BYTES,
    METADATA_JSON_MAX_BYTES,
    MIN_ROFL_BYTES,
    PREFIX_MAX_BYTES,
    ROFL_MAGICS,
    assert_rofl_size,
    read_rofl_prefix,
    validate_rofl_path,
)

__all__ = [
    "MAX_ROFL_BYTES",
    "METADATA_JSON_MAX_BYTES",
    "MIN_ROFL_BYTES",
    "PREFIX_MAX_BYTES",
    "ROFL_MAGICS",
    "FilenameIdentity",
    "HeaderParseStatus",
    "HeaderSniff",
    "IdentifyMethod",
    "RoflIdentificationResult",
    "RoflIdentity",
    "assert_rofl_size",
    "identify_rofl",
    "parse_filename_identity",
    "read_rofl_prefix",
    "sniff_rofl_prefix",
    "validate_rofl_path",
]
