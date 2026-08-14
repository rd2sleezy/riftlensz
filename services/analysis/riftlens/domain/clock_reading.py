"""H.9.1 clock OCR reading types. Pure domain — no OpenCV / video I/O."""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class ClockReading:
    """One sampled video frame's game-clock estimate.

    ``t_video_ms`` is presentation time from the media timeline (PTS-based).
    ``t_game_ms`` is HUD clock time since 00:00, or None when unreadable/non-game.
    """

    t_video_ms: int
    t_game_ms: int | None
    confidence: float
    in_game: bool = False
    raw_text: str = ""
    reason: str = ""

    def __post_init__(self) -> None:
        if isinstance(self.t_video_ms, bool) or not isinstance(self.t_video_ms, int):
            raise TypeError("t_video_ms must be int")
        if self.t_game_ms is not None and (
            isinstance(self.t_game_ms, bool) or not isinstance(self.t_game_ms, int)
        ):
            raise TypeError("t_game_ms must be int | None")
        if not (0.0 <= float(self.confidence) <= 1.0):
            raise ValueError("confidence must be in [0, 1]")

    @property
    def is_readable(self) -> bool:
        """True when a game-clock value was produced with positive confidence."""
        return self.t_game_ms is not None and self.confidence > 0.0

    def to_dict(self) -> dict[str, object]:
        return {
            "t_video_ms": self.t_video_ms,
            "t_game_ms": self.t_game_ms,
            "confidence": self.confidence,
            "in_game": self.in_game,
            "raw_text": self.raw_text,
            "reason": self.reason,
        }
