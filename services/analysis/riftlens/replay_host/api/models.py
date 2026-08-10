from __future__ import annotations

from typing import Any

from pydantic import BaseModel, ConfigDict, Field

from riftlens.domain.gameplay_source import PlaybackState


class ReplayPlayback(BaseModel):
    """Observed ``GET /replay/playback`` shape from R.0. Times are seconds, not ms."""

    model_config = ConfigDict(extra="ignore")

    length: float
    paused: bool
    seeking: bool
    speed: float
    time: float

    def to_playback_state(self) -> PlaybackState:
        """Return the R.1 domain snapshot. Assumes seconds convert by *1000 rounding."""
        return PlaybackState(
            t_source_ms=max(0, int(round(self.time * 1000.0))),
            length_ms=max(0, int(round(self.length * 1000.0))),
            paused=self.paused,
            seeking=self.seeking,
            speed_milli=max(0, int(round(self.speed * 1000.0))),
        )


class ReplayGame(BaseModel):
    """Observed ``GET /replay/game`` shape. Only ``processID`` was present in R.0."""

    model_config = ConfigDict(extra="allow")

    processID: int | None = None


class ReplayRecording(BaseModel):
    """Observed ``GET /replay/recording`` keys. Types follow Riot's documented recording object."""

    model_config = ConfigDict(extra="allow")

    codec: str | None = None
    currentTime: float | None = None
    endTime: float | None = None
    enforceFrameRate: bool | None = None
    framesPerSecond: float | None = None
    height: int | None = None
    lossless: bool | None = None
    path: str | None = None
    recording: bool | None = None
    replaySpeed: float | None = None
    startTime: float | None = None
    width: int | None = None


class ReplayRender(BaseModel):
    """``GET /replay/render`` surface. R.0 truncated at 66 keys; extras are allowed."""

    model_config = ConfigDict(extra="allow")

    cameraMode: str | None = None
    cameraPosition: Any = None
    cameraRotation: Any = None
    fogOfWar: bool | None = None
    fieldOfView: float | None = None


class ReplaySequence(BaseModel):
    """``GET /replay/sequence`` surface. R.0 listed 29 keys; extras are allowed."""

    model_config = ConfigDict(extra="allow")

    playbackSpeed: float | None = None
    cameraPosition: Any = None
    cameraRotation: Any = None


class GameStats(BaseModel):
    """Observed ``GET /liveclientdata/gamestats`` keys from R.0."""

    model_config = ConfigDict(extra="allow")

    gameTime: float
    gameMode: str | None = None
    mapName: str | None = None
    mapNumber: int | None = None
    mapTerrain: str | None = None


class LiveEvent(BaseModel):
    """One Live Client event. Only ``Events`` was observed at the wrapper; extras allowed."""

    model_config = ConfigDict(extra="allow")

    EventTime: float | None = None
    EventName: str | None = None
    EventID: int | None = None


class EventData(BaseModel):
    """Observed ``GET /liveclientdata/eventdata`` wrapper."""

    model_config = ConfigDict(extra="allow")

    Events: list[LiveEvent] = Field(default_factory=list)


class PlayerListEntry(BaseModel):
    """One ``playerlist`` element. R.0 only recorded that the payload is an array."""

    model_config = ConfigDict(extra="allow")


class ActivePlayerError(BaseModel):
    """R.0 ``activeplayer`` HTTP 400 body keys during replay."""

    model_config = ConfigDict(extra="allow")

    errorCode: str | None = None
    httpStatus: int | None = None
    message: str | None = None
    implementationDetails: str | None = None
