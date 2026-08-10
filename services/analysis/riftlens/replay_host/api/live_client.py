from __future__ import annotations

from typing import Any

from pydantic import BaseModel, TypeAdapter, ValidationError

from riftlens.domain.replay_errors import ReplayError, ReplayErrorCode
from riftlens.replay_host.api.models import EventData, GameStats, PlayerListEntry
from riftlens.replay_host.api.tls import DEFAULT_REPLAY_API_ORIGIN
from riftlens.replay_host.api.transport import LoopbackHttpsClient

_PLAYER_LIST = TypeAdapter(list[PlayerListEntry])


class LiveClientDataClient:
    """Typed Live Client Data transport. Optional endpoints return None instead of raising."""

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

    def get_gamestats(self) -> GameStats:
        """GET ``/liveclientdata/gamestats``. Raises informational LCD errors, never crashes."""
        payload = _lcd_request(self._http, "/liveclientdata/gamestats")
        return _validate_lcd(GameStats, payload, "/liveclientdata/gamestats")

    def get_eventdata(self) -> EventData:
        """GET ``/liveclientdata/eventdata``. Events may be empty early in a replay."""
        payload = _lcd_request(self._http, "/liveclientdata/eventdata")
        return _validate_lcd(EventData, payload, "/liveclientdata/eventdata")

    def get_playerlist(self) -> list[PlayerListEntry]:
        """GET ``/liveclientdata/playerlist``. R.0 observed an array payload."""
        payload = _lcd_request(self._http, "/liveclientdata/playerlist")
        try:
            return _PLAYER_LIST.validate_python(payload)
        except ValidationError as exc:
            raise ReplayError(
                ReplayErrorCode.LIVE_CLIENT_DATA_UNAVAILABLE,
                details={"reason": "invalid_schema", "path": "/liveclientdata/playerlist"},
            ) from exc

    def get_activeplayername(self) -> str | None:
        """GET ``/liveclientdata/activeplayername``. Missing/4xx is None, not fatal."""
        payload = _optional_lcd(self._http, "/liveclientdata/activeplayername")
        if payload is None:
            return None
        if isinstance(payload, str):
            return payload
        return str(payload)

    def get_activeplayer(self) -> dict[str, Any] | None:
        """GET ``/liveclientdata/activeplayer``. R.0 returned HTTP 400 during replay."""
        return _optional_lcd(self._http, "/liveclientdata/activeplayer")


def _lcd_request(http: LoopbackHttpsClient, path: str) -> Any:
    """GET a required LCD path. Maps transport failures to informational LCD errors."""
    try:
        return http.request_json("GET", path)
    except ReplayError as exc:
        if exc.code is ReplayErrorCode.REPLAY_API_TLS:
            raise
        raise ReplayError(
            ReplayErrorCode.LIVE_CLIENT_DATA_UNAVAILABLE,
            details={"path": path, **dict(exc.details)},
        ) from exc


def _optional_lcd(http: LoopbackHttpsClient, path: str) -> Any | None:
    """GET an optional LCD path. 4xx/unavailable become None; TLS still raises."""
    try:
        return http.request_json("GET", path, retry_transient=False)
    except ReplayError as exc:
        if exc.code is ReplayErrorCode.REPLAY_API_TLS:
            raise
        status = exc.details.get("status")
        if status in {400, 404} or exc.code is ReplayErrorCode.REPLAY_API_UNAVAILABLE:
            return None
        return None


def _validate_lcd[TModel: BaseModel](model: type[TModel], payload: Any, path: str) -> TModel:
    """Validate required LCD JSON. Assumes ``payload`` was already decoded."""
    try:
        return model.model_validate(payload)
    except ValidationError as exc:
        raise ReplayError(
            ReplayErrorCode.LIVE_CLIENT_DATA_UNAVAILABLE,
            details={"reason": "invalid_schema", "path": path, "error": exc.errors()},
        ) from exc
