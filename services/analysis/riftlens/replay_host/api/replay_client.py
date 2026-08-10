from __future__ import annotations

from collections.abc import Mapping
from typing import Any

from pydantic import BaseModel, ValidationError

from riftlens.domain.replay_errors import ReplayError, ReplayErrorCode
from riftlens.replay_host.api.models import (
    ReplayGame,
    ReplayPlayback,
    ReplayRecording,
    ReplayRender,
    ReplaySequence,
)
from riftlens.replay_host.api.tls import DEFAULT_REPLAY_API_ORIGIN
from riftlens.replay_host.api.transport import LoopbackHttpsClient


class ReplayApiClient:
    """Typed Replay API transport. Does not launch, seek-verify, or own a session lifecycle."""

    def __init__(
        self,
        origin: str = DEFAULT_REPLAY_API_ORIGIN,
        *,
        ca_file: str | None = None,
        timeout_s: float = 5.0,
        connect_timeout_s: float = 2.0,
        max_retries: int = 2,
    ) -> None:
        self._http = LoopbackHttpsClient(
            origin,
            ca_file=ca_file,
            timeout_s=timeout_s,
            connect_timeout_s=connect_timeout_s,
            max_retries=max_retries,
        )

    def get_game(self) -> ReplayGame:
        """GET ``/replay/game``. Assumes a replay process may expose only ``processID``."""
        return _validate(ReplayGame, self._http.request_json("GET", "/replay/game"), "/replay/game")

    def get_playback(self) -> ReplayPlayback:
        """GET ``/replay/playback``. Raises ``PLAYBACK_UNREADABLE`` when the schema drifts."""
        payload = self._http.request_json("GET", "/replay/playback")
        try:
            return ReplayPlayback.model_validate(payload)
        except ValidationError as exc:
            raise ReplayError(
                ReplayErrorCode.PLAYBACK_UNREADABLE,
                details={"reason": "invalid_schema", "error": exc.errors()},
            ) from exc

    def set_playback(
        self,
        *,
        paused: bool | None = None,
        time: float | None = None,
        speed: float | None = None,
        readback: bool = True,
    ) -> ReplayPlayback | None:
        """POST any subset of ``{paused, time, speed}``. Does not wait for seek completion."""
        body: dict[str, bool | float] = {}
        if paused is not None:
            body["paused"] = paused
        if time is not None:
            body["time"] = time
        if speed is not None:
            body["speed"] = speed
        if not body:
            raise ValueError("set_playback requires at least one of paused, time, speed")
        self._http.request_json("POST", "/replay/playback", json_body=body)
        if not readback:
            return None
        return self.get_playback()

    def get_render(self) -> ReplayRender:
        """GET ``/replay/render``. Transport only — does not change the camera."""
        return _validate(
            ReplayRender, self._http.request_json("GET", "/replay/render"), "/replay/render"
        )

    def set_render(self, patch: Mapping[str, Any]) -> ReplayRender:
        """POST ``/replay/render`` with caller-supplied fields. No camera policy is applied."""
        self._http.request_json("POST", "/replay/render", json_body=dict(patch))
        return self.get_render()

    def get_recording(self) -> ReplayRecording:
        """GET ``/replay/recording``. Does not start or stop a capture."""
        return _validate(
            ReplayRecording,
            self._http.request_json("GET", "/replay/recording"),
            "/replay/recording",
        )

    def set_recording(self, patch: Mapping[str, Any]) -> ReplayRecording:
        """POST ``/replay/recording``. Orchestration belongs to R.10, not this client."""
        self._http.request_json("POST", "/replay/recording", json_body=dict(patch))
        return self.get_recording()

    def get_sequence(self) -> ReplaySequence:
        """GET ``/replay/sequence``. Sequence choreography is out of MVP scope."""
        return _validate(
            ReplaySequence,
            self._http.request_json("GET", "/replay/sequence"),
            "/replay/sequence",
        )

    def set_sequence(self, patch: Mapping[str, Any]) -> ReplaySequence:
        """POST ``/replay/sequence``. Transport only."""
        self._http.request_json("POST", "/replay/sequence", json_body=dict(patch))
        return self.get_sequence()

    def try_get_json(self, path: str) -> Any | None:
        """GET an optional/unsupported path. 400/404/405 become None; TLS still raises."""
        try:
            return self._http.request_json("GET", path, retry_transient=False)
        except ReplayError as exc:
            if exc.code is ReplayErrorCode.REPLAY_API_TLS:
                raise
            if exc.details.get("status") in {400, 404, 405}:
                return None
            raise


def _validate[TModel: BaseModel](model: type[TModel], payload: Any, path: str) -> TModel:
    """Validate ``payload`` as ``model``. Assumes transport already returned decoded JSON."""
    try:
        return model.model_validate(payload)
    except ValidationError as exc:
        raise ReplayError(
            ReplayErrorCode.REPLAY_API_UNAVAILABLE,
            details={"reason": "invalid_schema", "path": path, "error": exc.errors()},
        ) from exc
