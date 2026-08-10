from __future__ import annotations

from collections.abc import Callable, Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Protocol

from riftlens.domain.replay_errors import ReplayError, ReplayErrorCode
from riftlens.replay_host.lcu.port import LcuReplayPort, NullLcuReplayPort
from riftlens.replay_host.windows.install_locator import LeagueInstall

STRATEGY_LCU_WATCH = "lcu_watch"
STRATEGY_DIRECT_EXE = "direct_exe"
STRATEGY_SHELL_OPEN = "shell_open"
STRATEGY_USER_ASSISTED = "user_assisted"

DEFAULT_STRATEGY_ORDER = (
    STRATEGY_LCU_WATCH,
    STRATEGY_DIRECT_EXE,
    STRATEGY_SHELL_OPEN,
    STRATEGY_USER_ASSISTED,
)


class ProcessHandle(Protocol):
    """A process RiftLens may own. Teardown must not scan by image name."""

    pid: int

    def poll(self) -> int | None:
        """Return exit code when finished, else None."""

    def terminate(self) -> None:
        """Terminate only this handle's pid."""


class ProcessOps(Protocol):
    """OS launch primitives. Tests inject fakes; production uses windows.process."""

    def spawn_direct(
        self, install: LeagueInstall, rofl_path: Path, *, platform_id: str | None
    ) -> ProcessHandle:
        """Spawn League of Legends.exe with the R.0 argument vector."""

    def shell_open(self, rofl_path: Path) -> None:
        """Open the .rofl via the OS file association."""

    def pid_is_running(self, pid: int) -> bool:
        """Return True when ``pid`` still exists."""


@dataclass(frozen=True)
class LaunchAttempt:
    """One strategy outcome. ``skipped`` is not a failure."""

    strategy: str
    ok: bool
    skipped: bool = False
    owns_process: bool = False
    pid: int | None = None
    handle: ProcessHandle | None = None
    error: ReplayError | None = None
    detail: str = ""


@dataclass(frozen=True)
class LaunchContext:
    """Inputs shared by every launch strategy. Assumes the .rofl was already validated."""

    rofl_path: Path
    install: LeagueInstall
    platform_id: str | None
    game_id: int | None
    lcu: LcuReplayPort
    processes: ProcessOps
    allow_user_assisted: bool = True


class LaunchStrategy(Protocol):
    """One step in the launch chain."""

    name: str

    def attempt(self, ctx: LaunchContext) -> LaunchAttempt:
        """Try this strategy once. Must not raise for expected unavailability."""


class LcuWatchStrategy:
    """Optional undocumented LCU watch. Skip unless the port was feature-probed."""

    name = STRATEGY_LCU_WATCH

    def attempt(self, ctx: LaunchContext) -> LaunchAttempt:
        if not ctx.lcu.is_available():
            return LaunchAttempt(
                strategy=self.name, ok=False, skipped=True, detail="lcu_not_available"
            )
        try:
            ctx.lcu.watch_replay(game_id=ctx.game_id, rofl_path=ctx.rofl_path)
        except ReplayError as exc:
            return LaunchAttempt(strategy=self.name, ok=False, skipped=False, error=exc)
        return LaunchAttempt(
            strategy=self.name, ok=True, owns_process=False, detail="lcu_watch_accepted"
        )


class DirectExeStrategy:
    """R.0-proven ``League of Legends.exe <rofl> -GameBaseDir=...`` spawn."""

    name = STRATEGY_DIRECT_EXE

    def attempt(self, ctx: LaunchContext) -> LaunchAttempt:
        try:
            handle = ctx.processes.spawn_direct(
                ctx.install, ctx.rofl_path, platform_id=ctx.platform_id
            )
        except ReplayError as exc:
            return LaunchAttempt(strategy=self.name, ok=False, error=exc)
        if handle.poll() is not None:
            return LaunchAttempt(
                strategy=self.name,
                ok=False,
                owns_process=True,
                pid=handle.pid,
                handle=handle,
                error=ReplayError(
                    ReplayErrorCode.LAUNCH_REJECTED,
                    details={"reason": "process_exited_immediately", "pid": handle.pid},
                ),
            )
        return LaunchAttempt(
            strategy=self.name,
            ok=True,
            owns_process=True,
            pid=handle.pid,
            handle=handle,
            detail="spawned_direct_exe",
        )


class ShellOpenStrategy:
    """OS file-association open. No reliable pid, so RiftLens does not own teardown."""

    name = STRATEGY_SHELL_OPEN

    def attempt(self, ctx: LaunchContext) -> LaunchAttempt:
        try:
            ctx.processes.shell_open(ctx.rofl_path)
        except ReplayError as exc:
            return LaunchAttempt(strategy=self.name, ok=False, error=exc)
        return LaunchAttempt(
            strategy=self.name, ok=True, owns_process=False, detail="shell_open_issued"
        )


class UserAssistedStrategy:
    """Terminal fallback: wait for the user to open the replay. Always works if enabled."""

    name = STRATEGY_USER_ASSISTED

    def attempt(self, ctx: LaunchContext) -> LaunchAttempt:
        if not ctx.allow_user_assisted:
            return LaunchAttempt(
                strategy=self.name, ok=False, skipped=True, detail="user_assisted_disabled"
            )
        return LaunchAttempt(
            strategy=self.name,
            ok=True,
            owns_process=False,
            detail="waiting_for_user_to_open_replay",
        )


def default_strategies() -> tuple[LaunchStrategy, ...]:
    """Return the amendment chain with R.0 direct-exe inserted before shell-open."""
    return (
        LcuWatchStrategy(),
        DirectExeStrategy(),
        ShellOpenStrategy(),
        UserAssistedStrategy(),
    )


def run_launch_chain(
    ctx: LaunchContext,
    strategies: Sequence[LaunchStrategy] | None = None,
    *,
    on_attempt: Callable[[LaunchAttempt], None] | None = None,
) -> tuple[LaunchAttempt, tuple[LaunchAttempt, ...]]:
    """Try strategies in order. First ``ok`` wins; skipped entries are not fatal."""
    chain = tuple(strategies) if strategies is not None else default_strategies()
    attempts: list[LaunchAttempt] = []
    for strategy in chain:
        result = strategy.attempt(ctx)
        attempts.append(result)
        if on_attempt is not None:
            on_attempt(result)
        if result.ok:
            return result, tuple(attempts)
    last_error = next((item.error for item in reversed(attempts) if item.error is not None), None)
    failure = LaunchAttempt(
        strategy="none",
        ok=False,
        error=last_error
        or ReplayError(
            ReplayErrorCode.LAUNCH_FAILED,
            details={"reason": "all_strategies_failed"},
        ),
        detail="all_strategies_failed",
    )
    return failure, tuple(attempts)


def windows_process_ops() -> ProcessOps:
    """Adapter over ``windows.process``. Imported lazily so tests can avoid spawning."""
    from riftlens.replay_host.windows import process as winproc

    class _WindowsProcessOps:
        def spawn_direct(
            self, install: LeagueInstall, rofl_path: Path, *, platform_id: str | None
        ) -> ProcessHandle:
            return winproc.spawn_direct_exe(install, rofl_path, platform_id=platform_id)

        def shell_open(self, rofl_path: Path) -> None:
            winproc.shell_open_rofl(rofl_path)

        def pid_is_running(self, pid: int) -> bool:
            return winproc.pid_is_running(pid)

    return _WindowsProcessOps()


def null_lcu() -> LcuReplayPort:
    """Return the default unavailable LCU port."""
    return NullLcuReplayPort()
