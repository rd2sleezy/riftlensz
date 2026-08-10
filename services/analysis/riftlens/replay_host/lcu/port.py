from __future__ import annotations

from pathlib import Path
from typing import Protocol

from riftlens.domain.replay_errors import ReplayError, ReplayErrorCode

_LIVE_PHASES = frozenset(
    {
        "InProgress",
        "ChampSelect",
        "ReadyCheck",
        "Matchmaking",
        "Reconnect",
        "GameStart",
        "CheckedIntoTournament",
        "WaitingForStats",
    }
)


class LcuReplayPort(Protocol):
    """Optional, feature-probed LCU surface. Never the only launch path."""

    def is_available(self) -> bool:
        """Return True only when lockfile + replay watch were actually probed OK."""

    def gameflow_phase(self) -> str | None:
        """Return gameflow phase when known. None means uncertain, not idle."""

    def watch_replay(self, *, game_id: int | None, rofl_path: Path) -> None:
        """Ask the client to play ``game_id``. Raises ``ReplayError`` on failure."""


class NullLcuReplayPort:
    """Default LCU: absent. Strategies skip; live-game detection stays uncertain."""

    def is_available(self) -> bool:
        """LCU watch is not load-bearing and is unavailable until probed."""
        return False

    def gameflow_phase(self) -> str | None:
        """No LCU means phase is unknown, not 'idle'."""
        return None

    def watch_replay(self, *, game_id: int | None, rofl_path: Path) -> None:
        """Refuse rather than pretend undocumented watch endpoints exist."""
        raise ReplayError(
            ReplayErrorCode.LAUNCH_FAILED,
            details={"reason": "lcu_unavailable", "path": str(rofl_path)},
        )


def is_live_gameflow_phase(phase: str | None) -> bool:
    """Return True only for confidently in-game / in-queue phases."""
    if phase is None:
        return False
    return phase in _LIVE_PHASES
