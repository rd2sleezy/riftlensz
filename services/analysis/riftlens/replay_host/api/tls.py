from __future__ import annotations

import ssl
from pathlib import Path
from urllib.parse import urlparse

from riftlens.domain.replay_errors import ReplayError, ReplayErrorCode

DEFAULT_REPLAY_API_ORIGIN = "https://127.0.0.1:2999"
ALLOWED_HOSTS = frozenset({"127.0.0.1"})
_WINDOWS_CA = Path(__file__).resolve().parents[1] / "windows" / "riotgames.pem"


def riot_ca_path() -> Path:
    """Return the vendored Riot Games root certificate. Assumes it ships with the package."""
    local = Path(__file__).resolve().with_name("riotgames.pem")
    if local.is_file():
        return local
    return _WINDOWS_CA


def replay_api_ssl_context(ca_file: str | Path | None = None) -> ssl.SSLContext:
    """Build a TLS context that pins Riot's CA and never sets ``verify=False``."""
    pem = Path(ca_file) if ca_file is not None else riot_ca_path()
    if not pem.is_file():
        raise ReplayError(
            ReplayErrorCode.REPLAY_API_TLS,
            details={"reason": "ca_missing", "path": str(pem)},
        )
    ctx = ssl.create_default_context(cafile=str(pem))
    ctx.verify_mode = ssl.CERT_REQUIRED
    # League serves 127.0.0.1 with a cert that is not hostname-issued for loopback.
    ctx.check_hostname = False
    # Python 3.13+/OpenSSL 3.x enables X509_STRICT, which rejects Riot's leaf
    # (missing Authority Key Identifier). Still pin the Riot CA; never verify=False.
    strict = getattr(ssl, "VERIFY_X509_STRICT", 0)
    if strict:
        ctx.verify_flags &= ~strict
    return ctx


def assert_loopback_origin(origin: str) -> None:
    """Reject non-loopback or non-HTTPS origins. Assumes ``origin`` is caller-supplied."""
    parsed = urlparse(origin)
    if (
        parsed.scheme != "https"
        or parsed.hostname not in ALLOWED_HOSTS
        or parsed.path not in {"", "/"}
    ):
        raise ReplayError(
            ReplayErrorCode.REPLAY_API_UNAVAILABLE,
            details={"reason": "invalid_origin", "origin": origin},
        )
