"""Resume remaining camera strategies after first successful C_path capture."""

from __future__ import annotations

import json
import os
import sys
import time
from pathlib import Path
from typing import Any

SPIKE_ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(SPIKE_ROOT))

# Import spike helpers by loading run_spike as module path.
import run_spike as spike  # noqa: E402
from riftlens.config import default_captures_dir  # noqa: E402
from riftlens.domain.capture import CaptureMode  # noqa: E402
from riftlens.domain.clock_map import ClockConfidence, ClockMap, ClockMode  # noqa: E402
from riftlens.domain.ids import new_ulid  # noqa: E402
from riftlens.replay_host.capture.recording import run_capture  # noqa: E402
from riftlens.replay_host.mac.game_config import enable_mac_replay_api  # noqa: E402
from riftlens.replay_host.mac.host import MacReplayHost  # noqa: E402
from riftlens.replay_host.mac.install_locator import locate_league_install_mac  # noqa: E402

C_CAPTURE = (
    Path.home()
    / ".riftlens/captures/NA1_5620410094/camspike_01KZZBA8Y3VQ06YTAB4GTSJHH1"
)
PARTIAL = SPIKE_ROOT / "artifacts" / "camera_spike_partial_probes.json"


def _ensure_session(host: MacReplayHost) -> Any:
    ready = spike._wait_active(host)
    if ready.is_active:
        return host.recording_client()
    try:
        host.close_session()
    except Exception:  # noqa: BLE001
        pass
    host.open_session(str(spike.ROFL))
    ready = spike._wait_active(host)
    if not ready.is_active:
        raise SystemExit(f"session not active: {ready.phase} {ready.error}")
    return host.recording_client()


def main() -> int:
    if os.environ.get("RIFTLENS_CAMERA_SPIKE") != "1":
        print("SKIP")
        return 0
    death_pos = spike.death_position(spike.MATCH, spike.DEATH_T_MS, spike.PID)
    summoner = spike.summoner_display_name(spike.MATCH, spike.PID)
    gst = spike.gst_from_db(spike.MATCH)

    # Seed probe facts from the first run's terminal observations.
    probes = {
        "accepted_camera_modes": ["top", "path", "fps"],
        "camera_mode_probes": [
            {"requested": "top", "readback": "top", "accepted": True},
            {"requested": "path", "readback": "path", "accepted": True},
            {"requested": "fps", "readback": "fps", "accepted": True},
        ],
        "direct_subject_targeting": {
            "selection_name_accepts_champion": True,
            "selection_name_resolves_to_summoner": "immynator",
            "cameraAttached_works": True,
            "no_participant_id_field": True,
        },
        "world_position_tests": [
            {
                "label": "path_plus_position",
                "ground_distance_to_death": 0.0,
                "position_applied": True,
            },
            {
                "label": "top_plus_position",
                "ground_distance_to_death": 13127.0,
                "position_applied": False,
            },
        ],
        "directed_camera_behavior": [
            {"label": "seek_while_top", "ground_distance_to_death": 13127.0},
            {"label": "seek_while_path_at_death", "ground_distance_to_death": 0.0},
        ],
    }
    PARTIAL.parent.mkdir(parents=True, exist_ok=True)
    PARTIAL.write_text(json.dumps(probes, indent=2) + "\n", encoding="utf-8")

    located = locate_league_install_mac()
    enable_mac_replay_api(located.install, consent=True)
    host = MacReplayHost()
    host.open_session(str(spike.ROFL))
    client = _ensure_session(host)
    assert client is not None

    playback = client.get_playback()
    length_ms = max(1, int(round(float(playback.length) * 1000.0)))
    clock = ClockMap(
        mode=ClockMode.IDENTITY,
        source_start_ms=0,
        source_end_ms=length_ms,
        offset_ms=0,
        confidence=ClockConfidence.GOOD,
        verified=True,
    )
    source_id = new_ulid()
    start_ms = spike.DEATH_T_MS - spike.PAD_BEFORE_MS
    end_ms = spike.DEATH_T_MS + spike.PAD_AFTER_MS

    strategy_runs: list[dict[str, Any]] = []
    # Re-analyze successful C capture.
    if C_CAPTURE.is_dir():
        print("REANALYZE C", C_CAPTURE, flush=True)
        analysis = spike._analyze(C_CAPTURE, gst=gst, death_t_ms=spike.DEATH_T_MS)
        webms = list(C_CAPTURE.glob("*.webm"))
        frames = []
        if webms:
            frames = spike._extract_frames(
                webms[0], spike.FRAMES / "C_path_gst_position", {0, 30, 60, 90, 120}
            )
        strategy_runs.append(
            {
                "strategy": "C_path_gst_position",
                "capture_ok": True,
                "capture_id": C_CAPTURE.name.replace("camspike_", ""),
                "capture_dir": str(C_CAPTURE),
                "applied": {
                    "ground_distance_to_death": 0.0,
                    "patch": {
                        "cameraMode": "path",
                        "cameraPosition": {
                            "x": death_pos["x"],
                            "y": 1910.0,
                            "z": death_pos["y"],
                        },
                    },
                },
                "frames": frames,
                "analysis": analysis,
                "reused_prior_capture": True,
            }
        )
        print(
            "C",
            analysis["v4_status"],
            analysis["v5_status"],
            analysis["track_count"],
            analysis["confirmed_detections"],
            flush=True,
        )

    remaining = ["A_directed_top", "D_attach_selection_champion", "B_seek_wait_top"]
    for strategy in remaining:
        print("STRATEGY", strategy, flush=True)
        try:
            if not host.poll_health().is_active:
                client = _ensure_session(host)
            assert client is not None
            seek_res = spike._await_seek(client, start_ms / 1000.0)
            applied = spike.apply_strategy(
                client, strategy, death_pos=death_pos, summoner=summoner
            )
            time.sleep(1.5)
            capture_id = new_ulid()
            capture_dir = default_captures_dir() / spike.MATCH / f"camspike_{capture_id}"
            capture_dir.mkdir(parents=True, exist_ok=True)
            sticky = spike._CameraStickyClient(client, applied["patch"])
            t_cap = time.perf_counter()
            result = run_capture(
                client=sticky,
                clock=clock,
                capture_id=capture_id,
                start_game_ms=start_ms,
                end_game_ms=end_ms,
                directory=capture_dir,
                mode=CaptureMode.CLIP,
                timeout_s=600.0,
            )
            capture_s = round(time.perf_counter() - t_cap, 2)
            entry: dict[str, Any] = {
                "strategy": strategy,
                "seek": seek_res,
                "applied": applied,
                "capture_ok": result.ok,
                "capture_error": None if result.error is None else str(result.error),
                "capture_runtime_s": capture_s,
                "capture_id": capture_id,
                "capture_dir": str(capture_dir),
            }
            if result.ok:
                spike._write_manifest(
                    capture_dir,
                    capture_id=capture_id,
                    source_id=source_id,
                    clock=clock,
                    clock_map_id=new_ulid(),
                    artifacts=result.artifacts,
                    start_game_ms=start_ms,
                    end_game_ms=end_ms,
                    camera_note=f"spike strategy={strategy}",
                )
                webms = list(capture_dir.glob("*.webm"))
                if webms:
                    entry["frames"] = spike._extract_frames(
                        webms[0], spike.FRAMES / strategy, {0, 30, 60, 90}
                    )
                entry["analysis"] = spike._analyze(
                    capture_dir, gst=gst, death_t_ms=spike.DEATH_T_MS
                )
                print(
                    " ",
                    entry["analysis"]["v4_status"],
                    "tracks",
                    entry["analysis"]["track_count"],
                    "det",
                    entry["analysis"]["confirmed_detections"],
                    flush=True,
                )
            strategy_runs.append(entry)
        except Exception as exc:  # noqa: BLE001
            print("STRATEGY_FAIL", strategy, exc, flush=True)
            strategy_runs.append({"strategy": strategy, "capture_ok": False, "error": str(exc)})
            try:
                client = _ensure_session(host)
            except Exception as reopen_exc:  # noqa: BLE001
                print("REOPEN_FAIL", reopen_exc, flush=True)
                break

    def score(run: dict[str, Any]) -> tuple[int, int, int, int]:
        a = run.get("analysis") or {}
        prox = run.get("applied") or {}
        near = 1 if (prox.get("ground_distance_to_death") or 1e9) < 2000 else 0
        return (
            int(a.get("confirmed_detections") or 0),
            int(a.get("track_count") or 0),
            int(a.get("longest_track_ms") or 0),
            near,
        )

    ranked = sorted(strategy_runs, key=score, reverse=True)
    useful = any(score(r)[0] >= 3 and score(r)[1] >= 2 for r in strategy_runs if r.get("capture_ok"))
    verdict = "CAMERA_CONTROL_SUPPORTED" if useful else "CAMERA_CONTROL_PARTIAL"

    # Optional alt with best strategy if C wasn't enough for LIKELY (still success on camera).
    best = ranked[0] if ranked else None
    alt_entry = None
    if best and host.poll_health().is_active and (best.get("analysis") or {}).get("v4_status") == "UNKNOWN":
        # Still try attach strategy on primary if not already best; skip extra death if C already useful.
        pass

    report = {
        "match_id": spike.MATCH,
        "subject_pid": spike.PID,
        "subject_champion": spike.SUBJECT,
        "death_t_ms": spike.DEATH_T_MS,
        "death_position_riot": death_pos,
        "summoner_display_name": summoner,
        **probes,
        "strategy_runs_primary": strategy_runs,
        "strategy_ranking": [
            {
                "strategy": r["strategy"],
                "score": list(score(r)),
                "capture_ok": r.get("capture_ok"),
                "analysis": r.get("analysis"),
                "ground_distance_to_death": (r.get("applied") or {}).get(
                    "ground_distance_to_death"
                ),
            }
            for r in ranked
        ],
        "strategy_run_alternate": alt_entry,
        "research_verdict": verdict,
        "baseline_fountain_capture": {
            "capture_id": "01KZZAGC6QZ8FWB61KQYDX4VVY",
            "confirmed_detections": 1,
            "track_count": 1,
            "v4_status": "UNKNOWN",
        },
    }
    try:
        host.close_session()
    except Exception:  # noqa: BLE001
        pass
    spike.OUT.parent.mkdir(parents=True, exist_ok=True)
    spike.OUT.write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
    print("VERDICT", verdict, flush=True)
    print("wrote", spike.OUT, flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
