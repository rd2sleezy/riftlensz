from __future__ import annotations

from dataclasses import dataclass

from riftlens.domain.gameplay_source import GameplaySource, SourceCapability
from riftlens.replay_host.port import ReplayHostPort
from riftlens.replay_host.session import ReplaySessionSnapshot


@dataclass
class RoflGameplaySource:
    """Live native-replay controller. Clock conversion stays in GameplaySourceService."""

    source: GameplaySource
    host: ReplayHostPort

    def capabilities(self) -> frozenset[SourceCapability]:
        """Return advertised runtime capabilities. Assumes the descriptor was resolved."""
        return self.source.capabilities

    def session(self) -> ReplaySessionSnapshot:
        """Return the in-memory host session. Persisted audit rows are not live."""
        return self.host.get_state()
