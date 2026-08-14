"""Real Mac acceptance: install discovery + open + three coaching seeks.

Uses the existing linked replay for NA1_5620410094. Does not re-import.
Writes JSON beside this script. Requires the live League client on this Mac.
"""

from __future__ import annotations

import json
import time
from pathlib import Path

from riftlens.domain.clock_map import ClockMap
from riftlens.domain.sync_map import SEEK_LEAD_IN_MS
from riftlens.replay_host.mac.game_config import enable_mac_replay_api, read_mac_replay_api_state
from riftlens.replay_host.mac.host import MacReplayHost
from riftlens.replay_host.mac.install_locator import locate_league_install_mac
from riftlens.replay_host.session import ReplaySessionPhase

ROFL = Path("/Users/rylanddunn/Documents/League of Legends/Replays/NA1-5620410094.rofl")
REVIEW = Path.home() / ".riftlens-integrate-ui-r1/reviews/01KZWSX7ZSADJD58K10MASN1BX.json"
OUT = Path(__file__).resolve().parent / "mac_install_seek_acceptance.json"
MATCH_ID = "NA1_5620410094"
DURATION_MS = 2_478_000
LEAD_IN_MS = SEEK_LEAD_IN_MS


def _focus_targets() -> list[dict[str, object]]:
    payload = json.loads(REVIEW.read_text(encoding="utf-8"))
    assert payload.get("match_id") == MATCH_ID
    assert payload.get("fixture_id") in (None, "")
    assert payload.get("sync_map") is None
    targets: list[dict[str, object]] = []
    for index, item in enumerate(payload["focus_items"][:3], start=1):
        exemplar = item["exemplar"]
        targets.append(
            {
                "index": index,
                "title": item["title"],
                "expected_t_ms": int(exemplar["t_ms"]),
                "t_mmss": exemplar.get("t_mmss"),
            }
        )
    return targets


def main() -> None:
    report: dict[str, object] = {
        "match_id": MATCH_ID,
        "rofl": str(ROFL),
        "review_id": REVIEW.name.replace(".json", ""),
        "lead_in_ms": LEAD_IN_MS,
    }
    located = locate_league_install_mac()
    report["locate"] = {
        "ok": located.install is not None,
        "error": None
        if located.error is None
        else {
            "code": located.error.code.value,
            "message": str(located.error),
            "details": dict(located.error.details),
        },
        "attempts": list(located.attempts),
        "root": None if located.install is None else str(located.install.root),
        "game_dir": None if located.install is None else str(located.install.game_dir),
        "game_exe": None if located.install is None else str(located.install.game_exe),
        "game_cfg": None if located.install is None else str(located.install.game_cfg),
        "game_cfg_existed_before_enable": None
        if located.install is None
        else located.install.game_cfg.is_file(),
    }
    if located.install is None:
        OUT.write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
        raise SystemExit(1)

    enable = enable_mac_replay_api(located.install, consent=True)
    state = read_mac_replay_api_state(located.install)
    report["enable_replay_api"] = {
        "ok": enable.ok,
        "changed": enable.primary.changed,
        "game_cfg_exists": located.install.game_cfg.is_file(),
        "enable_replay_api": state.enable_replay_api,
        "path": str(located.install.game_cfg),
    }
    if not enable.ok or not state.enable_replay_api:
        OUT.write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
        raise SystemExit(2)

    host = MacReplayHost()
    env = host.check_environment()
    report["environment"] = {
        "install_found": env.install_found,
        "error": None
        if env.error is None
        else {"code": env.error.code.value, "message": str(env.error)},
        "warning_codes": [w.code.value for w in env.warnings],
    }

    open_snap = host.open_session(str(ROFL))
    report["open"] = {
        "phase": open_snap.phase.value,
        "error": None
        if open_snap.error is None
        else {
            "code": open_snap.error.code.value,
            "message": str(open_snap.error),
            "details": dict(open_snap.error.details),
        },
    }

    deadline = time.monotonic() + 180.0
    phases: list[str] = [open_snap.phase.value]
    ready = open_snap
    while time.monotonic() < deadline:
        ready = host.poll_health()
        phases.append(ready.phase.value)
        # READY is the verified API gate; PLAYING/PAUSED/SEEKING are post-ready active.
        if ready.is_active:
            break
        if ready.phase is ReplaySessionPhase.FAILED:
            break
        time.sleep(1.0)
    report["startup"] = {
        "final_phase": ready.phase.value,
        "phases_seen": list(dict.fromkeys(phases)),
        "error": None
        if ready.error is None
        else {
            "code": ready.error.code.value,
            "message": str(ready.error),
            "details": dict(ready.error.details),
        },
        "replay_connected": ready.is_active,
        "session_reached_ready": ready.phase
        in {
            ReplaySessionPhase.READY,
            ReplaySessionPhase.PLAYING,
            ReplaySessionPhase.PAUSED,
            ReplaySessionPhase.SEEKING,
        },
    }
    if not ready.is_active:
        try:
            host.close_session()
        finally:
            OUT.write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
        raise SystemExit(3)

    clock = ClockMap.identity(duration_ms=DURATION_MS, verified=True)
    seeks: list[dict[str, object]] = []
    for target in _focus_targets():
        expected = int(target["expected_t_ms"])
        outcome = host.reveal(
            expected,
            clock,
            lead_in_ms=LEAD_IN_MS,
            match_duration_ms=DURATION_MS,
        )
        landed = outcome.landed_source_ms
        target_source = outcome.target_source_ms
        delta_vs_expected = None if landed is None else int(landed) - expected
        delta_vs_target = (
            None
            if landed is None or target_source is None
            else int(landed) - int(target_source)
        )
        seeks.append(
            {
                "index": target["index"],
                "title": target["title"],
                "expected_t_ms": expected,
                "t_mmss": target["t_mmss"],
                "lead_in_ms": LEAD_IN_MS,
                "target_source_ms": target_source,
                "landed_source_ms": landed,
                "delta_vs_expected_ms": delta_vs_expected,
                "delta_vs_target_ms": delta_vs_target,
                "ok": outcome.ok,
                "error": None
                if outcome.error is None
                else {
                    "code": outcome.error.code.value,
                    "message": str(outcome.error),
                    "details": dict(outcome.error.details),
                },
            }
        )
        time.sleep(1.0)
    report["seeks"] = seeks
    report["ok"] = all(bool(item["ok"]) for item in seeks)
    report["sync_map_involved"] = False
    report["fixture_involved"] = False

    try:
        host.close_session()
    finally:
        OUT.write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(report, indent=2))
    raise SystemExit(0 if report["ok"] else 4)


if __name__ == "__main__":
    main()
