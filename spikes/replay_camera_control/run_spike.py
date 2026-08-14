"""Replay camera control spike against NA1_5620410094 (macOS, Replay API only).

Set RIFTLENS_CAMERA_SPIKE=1. Uses production MacReplayHost + ClockMap + R.10 capture.
Does not mutate production camera policy.
"""

from __future__ import annotations

import json
import os
import sqlite3
import sys
import time
from collections.abc import Mapping
from pathlib import Path
from typing import Any

# Allow importing sibling spike helpers when run from services/analysis.
SPIKE_ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(SPIKE_ROOT))

from coords import (  # noqa: E402
    camera_position_to_riot_xy,
    ground_distance,
    riot_xy_to_camera_position,
)
from riftlens.config import Settings, default_captures_dir  # noqa: E402
from riftlens.domain.capture import (  # noqa: E402
    CAPTURE_ENGINE_VERSION,
    CAPTURE_MANIFEST_NAME,
    CaptureArtifactSpec,
    CaptureManifest,
    CaptureMode,
    CaptureStatus,
    RetentionClass,
)
from riftlens.domain.clock_map import ClockConfidence, ClockMap, ClockMode  # noqa: E402
from riftlens.domain.enums import DataTier, FactKind, Role, Source, Team  # noqa: E402
from riftlens.domain.fact import Fact, Provenance, SubjectRef  # noqa: E402
from riftlens.domain.ids import new_ulid  # noqa: E402
from riftlens.domain.timeline import GameStateTimeline, ParticipantInfo  # noqa: E402
from riftlens.replay_host.capture.recording import run_capture  # noqa: E402
from riftlens.replay_host.mac.game_config import enable_mac_replay_api  # noqa: E402
from riftlens.replay_host.mac.host import MacReplayHost  # noqa: E402
from riftlens.replay_host.mac.install_locator import locate_league_install_mac  # noqa: E402
from riftlens.replay_host.session import ReplaySessionPhase  # noqa: E402
from riftlens.visual.v4_analyze import analyze_capture_dir_v4  # noqa: E402
from riftlens.visual.v5_analyze import refine_v4_result  # noqa: E402

MATCH = "NA1_5620410094"
PID = 6
SUBJECT = "Vladimir"
DEATH_T_MS = 839_881
ALT_DEATH_T_MS = 1_062_798
PAD_BEFORE_MS = 10_000
PAD_AFTER_MS = 7_000
ROFL = Path.home() / "Documents" / "League of Legends" / "Replays" / "NA1-5620410094.rofl"
OUT = SPIKE_ROOT / "artifacts" / "camera_spike_report.json"
FRAMES = SPIKE_ROOT / "artifacts" / "frames"

# Candidate cameraMode strings (Replay API / community / HUD labels).
MODE_CANDIDATES = (
    "top",
    "path",
    "fps",
    "fpscam",
    "free",
    "directed",
    "follow",
    "attached",
    "first",
    "firstperson",
)


def _wait_active(host: MacReplayHost, *, timeout_s: float = 180.0) -> object:
    deadline = time.monotonic() + timeout_s
    ready = host.poll_health()
    while time.monotonic() < deadline:
        ready = host.poll_health()
        if ready.is_active:
            return ready
        if ready.phase is ReplaySessionPhase.FAILED:
            return ready
        time.sleep(1.0)
    return ready


def _await_seek(client: Any, target_s: float, *, timeout_s: float = 90.0) -> dict[str, Any]:
    t0 = time.perf_counter()
    deadline = time.monotonic() + timeout_s
    last: dict[str, Any] = {}
    posted = False
    while time.monotonic() < deadline:
        try:
            if not posted:
                client.set_playback(paused=True, time=float(target_s), readback=False)
                posted = True
            pb = client.get_playback()
        except Exception as exc:  # noqa: BLE001 — spike probe
            last = {"error": str(exc), "elapsed_s": round(time.perf_counter() - t0, 3)}
            time.sleep(0.5)
            continue
        last = {
            "time": pb.time,
            "seeking": pb.seeking,
            "paused": pb.paused,
            "elapsed_s": round(time.perf_counter() - t0, 3),
        }
        if (not pb.seeking) and abs(float(pb.time) - float(target_s)) <= 1.5:
            last["landed"] = True
            return last
        time.sleep(0.25)
    last["landed"] = False
    return last


def _render_dict(render: Any) -> dict[str, Any]:
    if hasattr(render, "model_dump"):
        return render.model_dump()
    return dict(render)


def _interesting_render(raw: dict[str, Any]) -> dict[str, Any]:
    keys = (
        "cameraMode",
        "cameraAttached",
        "cameraPosition",
        "cameraRotation",
        "fieldOfView",
        "fogOfWar",
        "selectionName",
        "selectionOffset",
        "cameraLockX",
        "cameraLockY",
        "cameraLockZ",
        "cameraMoveSpeed",
        "cameraLookSpeed",
    )
    return {k: raw.get(k) for k in keys if k in raw}


def death_position(match_id: str, death_t_ms: int, pid: int) -> dict[str, float]:
    con = sqlite3.connect(Settings().db_path)
    con.row_factory = sqlite3.Row
    row = con.execute(
        "SELECT payload, pos_x, pos_y FROM timeline_event "
        "WHERE match_id=? AND type='CHAMPION_KILL' AND victim_id=? AND t_ms=?",
        (match_id, pid, death_t_ms),
    ).fetchone()
    frame = con.execute(
        "SELECT pos_x, pos_y FROM participant_frame "
        "WHERE match_id=? AND participant_id=? AND t_ms BETWEEN ? AND ? "
        "ORDER BY ABS(t_ms - ?) LIMIT 1",
        (match_id, pid, death_t_ms - 90_000, death_t_ms + 5_000, death_t_ms),
    ).fetchone()
    name_row = con.execute(
        "SELECT champion_name FROM match_participation WHERE match_id=? AND participant_id=?",
        (match_id, pid),
    ).fetchone()
    con.close()
    x = y = None
    if row and row["payload"]:
        try:
            payload = json.loads(row["payload"])
            pos = payload.get("position") or {}
            x, y = float(pos["x"]), float(pos["y"])
        except (json.JSONDecodeError, KeyError, TypeError, ValueError):
            x = y = None
    if x is None and row is not None and row["pos_x"] is not None:
        x, y = float(row["pos_x"]), float(row["pos_y"])
    if x is None and frame is not None:
        x, y = float(frame["pos_x"]), float(frame["pos_y"])
    if x is None or y is None:
        raise SystemExit(f"no position for death {death_t_ms}")
    return {
        "x": x,
        "y": y,
        "champion": str(name_row["champion_name"] if name_row else SUBJECT),
    }


def summoner_display_name(match_id: str, pid: int) -> str | None:
    con = sqlite3.connect(Settings().db_path)
    row = con.execute(
        "SELECT stats_json FROM match_participation WHERE match_id=? AND participant_id=?",
        (match_id, pid),
    ).fetchone()
    con.close()
    if not row or not row[0]:
        return None
    try:
        stats = json.loads(row[0])
    except json.JSONDecodeError:
        return None
    name = stats.get("riotIdGameName") or stats.get("summonerName")
    return str(name) if name else None


def gst_from_db(match_id: str) -> GameStateTimeline:
    con = sqlite3.connect(Settings().db_path)
    con.row_factory = sqlite3.Row
    match_row = con.execute(
        "SELECT match_id, game_version, queue_id, game_duration_ms FROM match WHERE match_id=?",
        (match_id,),
    ).fetchone()
    parts = con.execute(
        "SELECT participant_id, champion_name, team_id, team_position "
        "FROM match_participation WHERE match_id=?",
        (match_id,),
    ).fetchall()
    kills = con.execute(
        "SELECT t_ms, killer_id, victim_id, payload FROM timeline_event "
        "WHERE match_id=? AND type='CHAMPION_KILL' ORDER BY t_ms",
        (match_id,),
    ).fetchall()
    con.close()
    participants: dict[int, ParticipantInfo] = {}
    for row in parts:
        role_raw = str(row["team_position"] or "UNKNOWN").upper()
        try:
            role = Role(role_raw)
        except ValueError:
            role = Role.UNKNOWN
        participants[int(row["participant_id"])] = ParticipantInfo(
            participant_id=int(row["participant_id"]),
            champion=str(row["champion_name"] or "Unknown"),
            role=role,
            team=Team(int(row["team_id"])),
            puuid=f"db-{row['participant_id']}",
        )
    gst = GameStateTimeline(
        match_id=match_id,
        patch=str(match_row["game_version"] or "unknown"),
        queue_id=int(match_row["queue_id"] or 420),
        duration_ms=int(match_row["game_duration_ms"] or 0),
        participants=participants,
        available_data_tiers=frozenset({DataTier.RIOT_ONLY, DataTier.RIOT_DERIVED}),
    )
    provenance = Provenance(producer="camera-spike", producer_version=1)
    facts: list[Fact] = []
    for row in kills:
        payload: dict[str, object] = {
            "killerId": row["killer_id"],
            "victimId": row["victim_id"],
        }
        raw = row["payload"]
        if isinstance(raw, str) and raw:
            try:
                loaded = json.loads(raw)
            except json.JSONDecodeError:
                loaded = {}
            if isinstance(loaded, dict):
                if loaded.get("assistingParticipantIds") is not None:
                    payload["assistingParticipantIds"] = loaded["assistingParticipantIds"]
                if isinstance(loaded.get("position"), dict):
                    payload["position"] = loaded["position"]
        facts.append(
            Fact(
                t_ms=int(row["t_ms"]),
                kind=FactKind.CHAMPION_KILL,
                subject=SubjectRef(kind="participant", id=row["victim_id"]),
                payload=payload,
                source=Source.RIOT_TIMELINE,
                confidence=1.0,
                provenance=provenance,
            )
        )
    gst.add_facts(facts)
    return gst


def _write_manifest(
    directory: Path,
    *,
    capture_id: str,
    source_id: str,
    clock: ClockMap,
    clock_map_id: str,
    artifacts: tuple[CaptureArtifactSpec, ...],
    start_game_ms: int,
    end_game_ms: int,
    camera_note: str,
) -> CaptureManifest:
    start_source = clock.game_to_source(start_game_ms)
    end_source = clock.game_to_source(end_game_ms)
    manifest = CaptureManifest(
        capture_id=capture_id,
        source_id=source_id,
        match_id=MATCH,
        clock_map_id=clock_map_id,
        mode=CaptureMode.CLIP,
        codec="webm",
        fps=30.0,
        requested_start_game_ms=start_game_ms,
        requested_end_game_ms=end_game_ms,
        start_source_ms=0 if start_source is None else int(start_source),
        end_source_ms=0 if end_source is None else int(end_source),
        retention=RetentionClass.EPHEMERAL,
        status=CaptureStatus.COMPLETE,
        created_at_ms=int(time.time() * 1000),
        clock_confidence=clock.confidence.value,
        clock_verified=bool(clock.verified),
        review_id=None,
        completed_at_ms=int(time.time() * 1000),
        camera_controlled=True,
        engine_version=CAPTURE_ENGINE_VERSION,
        artifacts=artifacts,
    )
    path = directory / CAPTURE_MANIFEST_NAME
    path.write_text(json.dumps(manifest.to_dict(), indent=2) + "\n", encoding="utf-8")
    # Spike-only sidecar note (not a production schema field).
    (directory / "camera_spike_note.txt").write_text(camera_note + "\n", encoding="utf-8")
    return manifest


def _extract_frames(webm: Path, out_dir: Path, indices: set[int]) -> list[str]:
    import cv2

    out_dir.mkdir(parents=True, exist_ok=True)
    cap = cv2.VideoCapture(str(webm))
    saved: list[str] = []
    n = 0
    while True:
        ok, frame = cap.read()
        if not ok:
            break
        if n in indices:
            path = out_dir / f"frame_{n:04d}.jpg"
            cv2.imwrite(str(path), frame, [int(cv2.IMWRITE_JPEG_QUALITY), 80])
            saved.append(str(path.relative_to(SPIKE_ROOT)))
        n += 1
    cap.release()
    return saved


def _analyze(
    capture_dir: Path,
    *,
    gst: GameStateTimeline,
    death_t_ms: int,
) -> dict[str, Any]:
    subject = gst.participants[PID]
    t0 = time.perf_counter()
    v4 = analyze_capture_dir_v4(
        capture_dir,
        subject_pid=PID,
        subject_champion=SUBJECT,
        capture_review_pid=PID,
        gst=gst,
        subject_team=subject.team,
    )
    v4_wall = time.perf_counter() - t0
    t0 = time.perf_counter()
    v5 = refine_v4_result(v4)
    v5_wall = time.perf_counter() - t0
    tracks = []
    longest = 0
    for tr in v4.tracks:
        dur = tr.last_seen_game_t_ms - tr.first_seen_game_t_ms
        longest = max(longest, dur)
        tracks.append(
            {
                "track_id": tr.track_id,
                "kind": tr.kind.value,
                "obs": tr.observation_count,
                "duration_ms": dur,
                "team": tr.team_estimate.value,
            }
        )
    useful = 0
    total = 0
    for frame in getattr(v4, "frames", []) or []:
        total += 1
        cov = getattr(frame, "viewport_coverage", None)
        if cov is not None and str(getattr(cov, "value", cov)) == "USEFUL":
            useful += 1
    # Fallback: informative_frames / analyzed_frames when frame list absent.
    if total == 0 and v4.timing.analyzed_frames:
        total = v4.timing.analyzed_frames
        useful = v4.informative_frames
    assert v5.v5 is not None
    return {
        "death_t_ms": death_t_ms,
        "v4_status": v4.correlation.status.value,
        "v4_confidence": v4.correlation.confidence,
        "v4_track_id": v4.correlation.track_id,
        "v5_status": v5.correlation.status.value,
        "v5_confidence": v5.correlation.confidence,
        "v5_identity_change": v5.v5.identity_change,
        "v5_cues": [] if v5.v5.bundle is None else [c.to_dict() for c in v5.v5.bundle.cues],
        "tracks": tracks,
        "track_count": len(tracks),
        "longest_track_ms": longest,
        "confirmed_detections": v4.confirmed_detections,
        "informative_frames": v4.informative_frames,
        "analyzed_frames": v4.timing.analyzed_frames,
        "useful_fraction": None if total == 0 else round(useful / total, 3),
        "runtime": {
            "v4_wall_s": round(v4_wall, 3),
            "v5_refine_s": round(v5_wall, 4),
            "detect_ms": round(v4.timing.detect_ms, 1),
            "continuity_ms": round(v5.continuity_ms, 3),
        },
    }


def apply_strategy(client: Any, name: str, *, death_pos: dict[str, float], summoner: str | None) -> dict[str, Any]:
    """Apply one camera strategy; return before/after render snapshot."""
    before = _interesting_render(_render_dict(client.get_render()))
    patch: dict[str, Any] = {}
    if name == "A_directed_top":
        patch = {"cameraMode": "top", "cameraAttached": False}
    elif name == "B_seek_wait_top":
        patch = {"cameraMode": "top", "cameraAttached": False}
    elif name == "C_path_gst_position":
        cam = riot_xy_to_camera_position(death_pos["x"], death_pos["y"])
        patch = {
            "cameraMode": "path",
            "cameraAttached": False,
            "cameraPosition": cam,
            "cameraRotation": {"x": 0, "y": 56, "z": 0},
            "fieldOfView": 40,
        }
    elif name == "D_attach_selection_champion":
        patch = {
            "cameraMode": "path",
            "cameraAttached": True,
            "selectionName": SUBJECT,
        }
    elif name == "D2_attach_selection_summoner":
        patch = {
            "cameraMode": "path",
            "cameraAttached": True,
            "selectionName": summoner or SUBJECT,
        }
    elif name == "E_path_then_top":
        cam = riot_xy_to_camera_position(death_pos["x"], death_pos["y"])
        client.set_render(
            {
                "cameraMode": "path",
                "cameraAttached": False,
                "cameraPosition": cam,
            }
        )
        time.sleep(0.5)
        patch = {"cameraMode": "top"}
    else:
        raise ValueError(name)
    try:
        after_obj = client.set_render(patch)
        after = _interesting_render(_render_dict(after_obj))
        err = None
    except Exception as exc:  # noqa: BLE001
        after = _interesting_render(_render_dict(client.get_render()))
        err = str(exc)
    # Settle briefly and re-read.
    time.sleep(1.0)
    settled = _interesting_render(_render_dict(client.get_render()))
    mapped = camera_position_to_riot_xy(settled.get("cameraPosition"))
    dist = None
    if mapped is not None:
        dist = round(ground_distance(mapped, (death_pos["x"], death_pos["y"])), 1)
    return {
        "strategy": name,
        "patch": patch,
        "before": before,
        "after_post": after,
        "settled": settled,
        "error": err,
        "ground_distance_to_death": dist,
        "mode_changed": before.get("cameraMode") != settled.get("cameraMode"),
        "position_changed": before.get("cameraPosition") != settled.get("cameraPosition"),
        "attached_changed": before.get("cameraAttached") != settled.get("cameraAttached"),
        "selection_changed": before.get("selectionName") != settled.get("selectionName"),
    }


class _CameraStickyClient:
    """Replay API client wrapper: re-apply render patch after seek (spike-only)."""

    def __init__(self, inner: Any, patch: Mapping[str, Any]) -> None:
        self._inner = inner
        self._patch = dict(patch)

    def get_recording(self) -> Any:
        return self._inner.get_recording()

    def set_recording(self, patch: Mapping[str, Any]) -> Any:
        # Ensure camera is set immediately before encode starts.
        try:
            self._inner.set_render(self._patch)
        except Exception:  # noqa: BLE001
            pass
        return self._inner.set_recording(patch)

    def get_playback(self) -> Any:
        return self._inner.get_playback()

    def set_playback(
        self,
        *,
        paused: bool | None = None,
        time: float | None = None,
        speed: float | None = None,
        readback: bool = True,
    ) -> Any:
        result = self._inner.set_playback(
            paused=paused, time=time, speed=speed, readback=readback
        )
        if time is not None:
            try:
                self._inner.set_render(self._patch)
            except Exception:  # noqa: BLE001
                pass
        return result

    def get_render(self) -> Any:
        return self._inner.get_render()

    def set_render(self, patch: Mapping[str, Any]) -> Any:
        return self._inner.set_render(patch)


def main() -> int:
    if os.environ.get("RIFTLENS_CAMERA_SPIKE") != "1":
        print("SKIP: set RIFTLENS_CAMERA_SPIKE=1")
        return 0
    if not ROFL.is_file():
        print("FAIL missing", ROFL)
        return 2

    death_pos = death_position(MATCH, DEATH_T_MS, PID)
    summoner = summoner_display_name(MATCH, PID)
    print("death_pos", death_pos, "summoner", summoner, flush=True)

    located = locate_league_install_mac()
    if located.install is None:
        print("FAIL no League install")
        return 3
    enable_mac_replay_api(located.install, consent=True)

    host = MacReplayHost()
    open_snap = host.open_session(str(ROFL))
    print("OPEN", open_snap.phase.value, open_snap.error, flush=True)
    ready = _wait_active(host)
    print("READY", ready.phase.value, ready.error, flush=True)
    report: dict[str, Any] = {
        "match_id": MATCH,
        "subject_pid": PID,
        "subject_champion": SUBJECT,
        "death_t_ms": DEATH_T_MS,
        "death_position_riot": death_pos,
        "summoner_display_name": summoner,
        "rofl": str(ROFL),
    }
    if not ready.is_active:
        report["error"] = "session_not_active"
        OUT.parent.mkdir(parents=True, exist_ok=True)
        OUT.write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
        return 4

    client = host.recording_client()
    assert client is not None

    # --- Phase 1: schema / OpenAPI ---
    raw_render = _render_dict(client.get_render())
    report["render_schema_keys"] = sorted(raw_render.keys())
    report["render_sample"] = _interesting_render(raw_render)
    openapi: dict[str, Any] = {"paths": {}}
    for path in ("/swagger/v3/openapi.json", "/swagger/v2/swagger.json", "/openapi.json"):
        try:
            doc = client.try_get_json(path)
        except Exception as exc:  # noqa: BLE001
            openapi["paths"][path] = {"error": str(exc)}
            continue
        if isinstance(doc, dict):
            openapi["paths"][path] = {"ok": True, "top_keys": sorted(doc.keys())[:30]}
            # Extract render schema if present.
            components = doc.get("components") or doc.get("definitions") or {}
            paths = doc.get("paths") or {}
            render_path = paths.get("/replay/render") or paths.get("replay/render")
            openapi["render_path"] = render_path
            openapi["component_keys"] = (
                sorted(components.keys())[:80] if isinstance(components, dict) else None
            )
            break
        openapi["paths"][path] = {"ok": False}
    report["openapi"] = openapi

    # --- Phase 2: camera mode enum probes ---
    mode_results: list[dict[str, Any]] = []
    baseline_mode = raw_render.get("cameraMode")
    for mode in MODE_CANDIDATES:
        try:
            client.set_render({"cameraMode": mode})
            time.sleep(0.3)
            got = _render_dict(client.get_render()).get("cameraMode")
            mode_results.append(
                {
                    "requested": mode,
                    "readback": got,
                    "accepted": got == mode,
                }
            )
            print("MODE", mode, "->", got, flush=True)
        except Exception as exc:  # noqa: BLE001
            mode_results.append({"requested": mode, "error": str(exc), "accepted": False})
    # Restore baseline.
    try:
        client.set_render({"cameraMode": baseline_mode or "top"})
    except Exception:  # noqa: BLE001
        pass
    report["camera_mode_probes"] = mode_results
    report["accepted_camera_modes"] = [m["requested"] for m in mode_results if m.get("accepted")]

    # --- Phase 3: selection / attach ---
    selection_tests: list[dict[str, Any]] = []
    for label, patch in (
        ("attach_true_only", {"cameraAttached": True}),
        ("selection_Vladimir", {"selectionName": "Vladimir", "cameraAttached": True}),
        ("selection_immynator", {"selectionName": summoner or "immynator", "cameraAttached": True}),
        ("selection_empty", {"selectionName": "", "cameraAttached": False}),
    ):
        try:
            before = _interesting_render(_render_dict(client.get_render()))
            client.set_render(patch)
            time.sleep(0.5)
            after = _interesting_render(_render_dict(client.get_render()))
            selection_tests.append(
                {
                    "label": label,
                    "patch": patch,
                    "before": before,
                    "after": after,
                    "selection_stuck": after.get("selectionName") == patch.get("selectionName"),
                    "attached_stuck": after.get("cameraAttached") == patch.get("cameraAttached"),
                }
            )
            print("SEL", label, after.get("selectionName"), after.get("cameraAttached"), flush=True)
        except Exception as exc:  # noqa: BLE001
            selection_tests.append({"label": label, "error": str(exc)})
    report["selection_attach_tests"] = selection_tests
    report["direct_subject_targeting"] = {
        "api_fields_present": {
            "selectionName": "selectionName" in raw_render,
            "cameraAttached": "cameraAttached" in raw_render,
        },
        "selection_name_accepts_champion": any(
            t.get("label") == "selection_Vladimir" and t.get("selection_stuck") for t in selection_tests
        ),
        "selection_name_accepts_summoner": any(
            t.get("label") == "selection_immynator" and t.get("selection_stuck") for t in selection_tests
        ),
        "note": (
            "No participant-id follow field observed on Mac GET /replay/render. "
            "selectionName + cameraAttached are the only candidate subject-target hooks."
        ),
    }

    # --- Phase 4: world position control ---
    seek = _await_seek(client, DEATH_T_MS / 1000.0 - 10.0)
    report["seek_before_position_test"] = seek
    cam = riot_xy_to_camera_position(death_pos["x"], death_pos["y"])
    world_tests: list[dict[str, Any]] = []
    for label, patch in (
        ("position_only_keep_mode", {"cameraPosition": cam}),
        (
            "path_plus_position",
            {
                "cameraMode": "path",
                "cameraAttached": False,
                "cameraPosition": cam,
                "cameraRotation": {"x": 0, "y": 56, "z": 0},
            },
        ),
        (
            "top_plus_position",
            {
                "cameraMode": "top",
                "cameraAttached": False,
                "cameraPosition": cam,
            },
        ),
    ):
        try:
            before = _interesting_render(_render_dict(client.get_render()))
            client.set_render(patch)
            time.sleep(1.0)
            after = _interesting_render(_render_dict(client.get_render()))
            mapped = camera_position_to_riot_xy(after.get("cameraPosition"))
            dist = (
                None
                if mapped is None
                else round(ground_distance(mapped, (death_pos["x"], death_pos["y"])), 1)
            )
            world_tests.append(
                {
                    "label": label,
                    "patch": patch,
                    "before_mode": before.get("cameraMode"),
                    "after_mode": after.get("cameraMode"),
                    "after_position": after.get("cameraPosition"),
                    "ground_distance_to_death": dist,
                    "position_applied": dist is not None and dist < 500.0,
                }
            )
            print("WORLD", label, "dist", dist, "mode", after.get("cameraMode"), flush=True)
        except Exception as exc:  # noqa: BLE001
            world_tests.append({"label": label, "error": str(exc)})
    report["world_position_tests"] = world_tests

    # --- Phase 5: Directed/top seek behavior ---
    directed_behavior: list[dict[str, Any]] = []
    for label, setup in (
        ("seek_while_top", {"cameraMode": "top", "cameraAttached": False}),
        ("seek_while_path_at_death", None),
    ):
        if setup is not None:
            client.set_render(setup)
        else:
            client.set_render(
                {
                    "cameraMode": "path",
                    "cameraAttached": False,
                    "cameraPosition": cam,
                }
            )
        time.sleep(0.5)
        before_seek = _interesting_render(_render_dict(client.get_render()))
        seek_res = _await_seek(client, (DEATH_T_MS - 5_000) / 1000.0)
        time.sleep(2.0)  # stabilization window
        after_seek = _interesting_render(_render_dict(client.get_render()))
        mapped = camera_position_to_riot_xy(after_seek.get("cameraPosition"))
        dist = (
            None
            if mapped is None
            else round(ground_distance(mapped, (death_pos["x"], death_pos["y"])), 1)
        )
        directed_behavior.append(
            {
                "label": label,
                "before_seek": before_seek,
                "seek": seek_res,
                "after_seek_plus_2s": after_seek,
                "ground_distance_to_death": dist,
            }
        )
        print("DIR", label, "dist", dist, flush=True)
    report["directed_camera_behavior"] = directed_behavior

    # --- Phase 6: strategy ranking captures (primary death) ---
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
    gst = gst_from_db(MATCH)
    source_id = new_ulid()
    start_ms = DEATH_T_MS - PAD_BEFORE_MS
    end_ms = DEATH_T_MS + PAD_AFTER_MS

    # Prefer strategies that moved camera near death in probes.
    strategies = [
        "C_path_gst_position",
        "A_directed_top",
        "D_attach_selection_champion",
        "B_seek_wait_top",
    ]
    strategy_runs: list[dict[str, Any]] = []
    for strategy in strategies:
        print("STRATEGY", strategy, flush=True)
        seek_res = _await_seek(client, start_ms / 1000.0)
        settle_t0 = time.perf_counter()
        applied = apply_strategy(client, strategy, death_pos=death_pos, summoner=summoner)
        # Extra settle for capture.
        time.sleep(1.5)
        stabilize_s = round(time.perf_counter() - settle_t0, 3)
        capture_id = new_ulid()
        capture_dir = default_captures_dir() / MATCH / f"camspike_{capture_id}"
        capture_dir.mkdir(parents=True, exist_ok=True)
        t_cap = time.perf_counter()
        sticky = _CameraStickyClient(client, applied["patch"])
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
            "stabilize_s": stabilize_s,
            "capture_ok": result.ok,
            "capture_error": None if result.error is None else str(result.error),
            "capture_runtime_s": capture_s,
            "capture_id": capture_id,
            "capture_dir": str(capture_dir),
        }
        if result.ok:
            _write_manifest(
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
                entry["frames"] = _extract_frames(
                    webms[0], FRAMES / strategy, {0, 30, 60, 90, 120}
                )
            entry["analysis"] = _analyze(capture_dir, gst=gst, death_t_ms=DEATH_T_MS)
            print(
                "  v4",
                entry["analysis"]["v4_status"],
                "tracks",
                entry["analysis"]["track_count"],
                "det",
                entry["analysis"]["confirmed_detections"],
                flush=True,
            )
        strategy_runs.append(entry)
        # Reopen if API died during capture.
        health = host.poll_health()
        if not health.is_active:
            print("REOPEN", health.phase.value, flush=True)
            try:
                host.close_session()
            except Exception:  # noqa: BLE001
                pass
            host.open_session(str(ROFL))
            ready = _wait_active(host)
            if not ready.is_active:
                break
            client = host.recording_client()
            assert client is not None

    report["strategy_runs_primary"] = strategy_runs

    # Rank by detections + tracks + proximity.
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
    report["strategy_ranking"] = [
        {
            "strategy": r["strategy"],
            "score": list(score(r)),
            "capture_ok": r.get("capture_ok"),
            "analysis": r.get("analysis"),
            "ground_distance_to_death": (r.get("applied") or {}).get("ground_distance_to_death"),
        }
        for r in ranked
    ]

    # Optional secondary death with best strategy only if primary still weak.
    best = ranked[0] if ranked else None
    primary_weak = best is None or score(best)[0] < 3
    if primary_weak and client is not None and host.poll_health().is_active:
        alt_pos = death_position(MATCH, ALT_DEATH_T_MS, PID)
        strat = (best or {}).get("strategy") or "C_path_gst_position"
        print("ALT", ALT_DEATH_T_MS, strat, alt_pos, flush=True)
        a_start, a_end = ALT_DEATH_T_MS - PAD_BEFORE_MS, ALT_DEATH_T_MS + PAD_AFTER_MS
        _await_seek(client, a_start / 1000.0)
        applied = apply_strategy(client, strat, death_pos=alt_pos, summoner=summoner)
        time.sleep(1.5)
        capture_id = new_ulid()
        capture_dir = default_captures_dir() / MATCH / f"camspike_alt_{capture_id}"
        capture_dir.mkdir(parents=True, exist_ok=True)
        sticky = _CameraStickyClient(client, applied["patch"])
        result = run_capture(
            client=sticky,
            clock=clock,
            capture_id=capture_id,
            start_game_ms=a_start,
            end_game_ms=a_end,
            directory=capture_dir,
            mode=CaptureMode.CLIP,
            timeout_s=600.0,
        )
        alt_entry: dict[str, Any] = {
            "death_t_ms": ALT_DEATH_T_MS,
            "strategy": strat,
            "applied": applied,
            "capture_ok": result.ok,
            "capture_error": None if result.error is None else str(result.error),
            "capture_id": capture_id,
        }
        if result.ok:
            _write_manifest(
                capture_dir,
                capture_id=capture_id,
                source_id=source_id,
                clock=clock,
                clock_map_id=new_ulid(),
                artifacts=result.artifacts,
                start_game_ms=a_start,
                end_game_ms=a_end,
                camera_note=f"spike alt strategy={strat}",
            )
            alt_entry["analysis"] = _analyze(capture_dir, gst=gst, death_t_ms=ALT_DEATH_T_MS)
        report["strategy_run_alternate"] = alt_entry

    # Verdict
    useful = any(score(r)[0] >= 3 and score(r)[1] >= 2 for r in strategy_runs if r.get("capture_ok"))
    any_move = any(
        (r.get("applied") or {}).get("position_changed")
        or ((r.get("applied") or {}).get("ground_distance_to_death") or 1e9) < 2500
        for r in strategy_runs
    )
    if useful:
        verdict = "CAMERA_CONTROL_SUPPORTED"
    elif any_move or any(m.get("accepted") for m in mode_results):
        verdict = "CAMERA_CONTROL_PARTIAL"
    else:
        verdict = "CAMERA_CONTROL_NOT_SUPPORTED"
    report["research_verdict"] = verdict

    try:
        host.close_session()
    except Exception as exc:  # noqa: BLE001
        report["close_error"] = str(exc)

    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
    print("VERDICT", verdict, flush=True)
    print("wrote", OUT, flush=True)
    return 0 if verdict != "CAMERA_CONTROL_NOT_SUPPORTED" else 6


if __name__ == "__main__":
    raise SystemExit(main())
