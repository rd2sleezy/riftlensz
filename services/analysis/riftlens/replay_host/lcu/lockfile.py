from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from riftlens.domain.replay_errors import ReplayError, ReplayErrorCode

_REDACTED = "***"


@dataclass(frozen=True)
class LcuLockfile:
    """Parsed League Client lockfile. Password is held in memory only and never logged."""

    name: str
    pid: int
    port: int
    protocol: str
    password: str
    path: Path

    def origin(self) -> str:
        """Return loopback origin. Assumes the lockfile port is local-only."""
        return f"{self.protocol}://127.0.0.1:{self.port}"

    def redacted_dict(self) -> dict[str, object]:
        """Return a log-safe mapping. Password is always redacted."""
        return {
            "name": self.name,
            "pid": self.pid,
            "port": self.port,
            "protocol": self.protocol,
            "password": _REDACTED,
            "path": str(self.path),
        }


def parse_lcu_lockfile(text: str, *, path: Path) -> LcuLockfile:
    """Parse ``name:pid:port:password:protocol``. Raises when the shape is unusable."""
    parts = text.strip().split(":")
    if len(parts) < 5:
        raise ReplayError(
            ReplayErrorCode.LAUNCH_FAILED,
            details={"reason": "lockfile_malformed", "path": str(path)},
        )
    name, pid_raw, port_raw, password, protocol = parts[0], parts[1], parts[2], parts[3], parts[4]
    try:
        pid = int(pid_raw)
        port = int(port_raw)
    except ValueError as exc:
        raise ReplayError(
            ReplayErrorCode.LAUNCH_FAILED,
            details={"reason": "lockfile_not_numeric", "path": str(path)},
        ) from exc
    if port <= 0 or port > 65535 or pid <= 0:
        raise ReplayError(
            ReplayErrorCode.LAUNCH_FAILED,
            details={"reason": "lockfile_out_of_range", "path": str(path)},
        )
    if protocol.lower() not in {"https", "http"}:
        raise ReplayError(
            ReplayErrorCode.LAUNCH_FAILED,
            details={"reason": "lockfile_bad_protocol", "path": str(path)},
        )
    return LcuLockfile(
        name=name,
        pid=pid,
        port=port,
        protocol=protocol.lower(),
        password=password,
        path=path,
    )


def read_lcu_lockfile(path: str | Path) -> LcuLockfile | None:
    """Return a lockfile if present and parseable. Missing file is None, not an error."""
    lock_path = Path(path)
    if not lock_path.is_file():
        return None
    try:
        text = lock_path.read_text(encoding="utf-8")
    except OSError:
        return None
    try:
        return parse_lcu_lockfile(text, path=lock_path)
    except ReplayError:
        return None
