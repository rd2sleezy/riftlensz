from __future__ import annotations

from collections.abc import Callable, Sequence
from pathlib import Path

from riftlens.domain.replay_errors import ReplayError, ReplayErrorCode
from riftlens.replay_host.api.models import ReplayPlayback
from riftlens.replay_host.launch_strategies import ProcessHandle
from riftlens.replay_host.windows.install_locator import LeagueInstall
from riftlens.rofl.validation import ROFL_MAGICS


class FakeClock:
    """Monotonic clock that advances only when ``sleep`` is called."""

    def __init__(self, start: float = 0.0) -> None:
        self.t = start
        self.sleeps: list[float] = []
        self.on_sleep: Callable[[float], None] | None = None

    def monotonic(self) -> float:
        return self.t

    def sleep(self, seconds: float) -> None:
        self.sleeps.append(seconds)
        self.t += seconds
        if self.on_sleep is not None:
            self.on_sleep(seconds)


class FakeProcessHandle:
    """In-memory process handle. Terminate affects only this instance."""

    def __init__(self, pid: int, *, running: bool = True) -> None:
        self.pid = pid
        self.running = running
        self.terminated = False
        self.poll_count = 0

    def poll(self) -> int | None:
        self.poll_count += 1
        return None if self.running else 0

    def terminate(self) -> None:
        self.terminated = True
        self.running = False


class FakeProcessOps:
    """Configurable launcher. Unrelated handles are never terminated by the supervisor."""

    def __init__(
        self,
        *,
        direct: FakeProcessHandle | ReplayError | None = None,
        shell_error: ReplayError | None = None,
        running_pids: set[int] | None = None,
    ) -> None:
        self.direct: FakeProcessHandle | ReplayError | None = (
            direct if direct is not None else FakeProcessHandle(4242)
        )
        self.shell_error = shell_error
        self.running_pids = running_pids if running_pids is not None else set()
        self.direct_calls = 0
        self.shell_calls = 0
        self.unrelated = FakeProcessHandle(9999)
        self.running_pids.add(9999)

    def spawn_direct(
        self, install: LeagueInstall, rofl_path: Path, *, platform_id: str | None
    ) -> ProcessHandle:
        self.direct_calls += 1
        if isinstance(self.direct, ReplayError):
            raise self.direct
        assert self.direct is not None
        self.running_pids.add(self.direct.pid)
        return self.direct

    def shell_open(self, rofl_path: Path) -> None:
        self.shell_calls += 1
        if self.shell_error is not None:
            raise self.shell_error

    def pid_is_running(self, pid: int) -> bool:
        handle = self.direct
        if isinstance(handle, FakeProcessHandle) and handle.pid == pid:
            return handle.running
        if pid == self.unrelated.pid:
            return self.unrelated.running
        return pid in self.running_pids and pid not in {0}


class FakeLcu:
    """Optional LCU double. Unavailable unless ``available`` is set."""

    def __init__(
        self,
        *,
        available: bool = False,
        phase: str | None = None,
        watch_error: ReplayError | None = None,
    ) -> None:
        self._available = available
        self._phase = phase
        self.watch_error = watch_error
        self.watch_calls = 0

    def is_available(self) -> bool:
        return self._available

    def gameflow_phase(self) -> str | None:
        return self._phase

    def watch_replay(self, *, game_id: int | None, rofl_path: Path) -> None:
        self.watch_calls += 1
        if self.watch_error is not None:
            raise self.watch_error


class FakeLiveProbe:
    def __init__(self, reachable: bool = False) -> None:
        self.reachable = reachable

    def gamestats_reachable(self) -> bool:
        return self.reachable


class ScriptedTransport:
    """Playback sequence. Callables are evaluated when reached."""

    def __init__(
        self,
        gets: Sequence[ReplayPlayback | ReplayError | Callable[[], ReplayPlayback | ReplayError]],
        *,
        process_id: int | None = 14520,
        set_result: ReplayPlayback | None = None,
    ) -> None:
        self.gets = list(gets)
        self.index = 0
        self.process_id = process_id
        self.set_calls: list[dict[str, object]] = []
        self.set_result = set_result

    def get_playback(self) -> ReplayPlayback:
        if not self.gets:
            raise ReplayError(ReplayErrorCode.REPLAY_API_UNAVAILABLE, details={"reason": "empty"})
        item: ReplayPlayback | ReplayError | Callable[[], ReplayPlayback | ReplayError]
        if self.index < len(self.gets):
            item = self.gets[self.index]
            self.index += 1
        else:
            item = self.gets[-1]
        if callable(item):
            item = item()
        if isinstance(item, ReplayError):
            raise item
        return item

    def set_playback(
        self,
        *,
        paused: bool | None = None,
        time: float | None = None,
        speed: float | None = None,
        readback: bool = True,
    ) -> ReplayPlayback | None:
        self.set_calls.append(
            {"paused": paused, "time": time, "speed": speed, "readback": readback}
        )
        if self.set_result is not None:
            return self.set_result
        if self.index < len(self.gets):
            return self.get_playback()
        last = self.gets[-1]
        if callable(last):
            last = last()
        if isinstance(last, ReplayError):
            raise last
        if paused is False:
            return ReplayPlayback(
                length=last.length,
                paused=False,
                seeking=False,
                speed=last.speed,
                time=last.time,
            )
        return last

    def get_game_process_id(self) -> int | None:
        return self.process_id


def playback(
    *,
    length: float = 1902.97,
    paused: bool = False,
    seeking: bool = False,
    speed: float = 1.0,
    time: float = 2.0,
) -> ReplayPlayback:
    return ReplayPlayback(length=length, paused=paused, seeking=seeking, speed=speed, time=time)


def unavailable(reason: str = "connect_failed") -> ReplayError:
    return ReplayError(ReplayErrorCode.REPLAY_API_UNAVAILABLE, details={"reason": reason})


def write_tiny_rofl(path: Path) -> Path:
    path.write_bytes(ROFL_MAGICS[0] + b"\x00" * 128)
    return path
