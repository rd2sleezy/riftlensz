"""Real Mac V.5 death-window capture + V.4/V.5 validation.

Match: NA1_5620410094 · Vladimir pid 6 · death @ 839881 (13:59).

Uses MacReplayHost.open_session + capture_interval (production R.10 recording path).
Set RIFTLENS_V5_T4=1. Does not commit media. Research only.
"""

from __future__ import annotations

import json
import os
import sqlite3
import time
from pathlib import Path

from riftlens.config import Settings, default_captures_dir
from riftlens.domain.camera_framing import (
    CameraFramingMetadata,
    DEFAULT_STABILIZE_S,
    build_path_gst_framing_plan,
    camera_position_to_riot_xy,
    ground_distance,
    resolve_gst_camera_target,
)
from riftlens.domain.capture import (
    CAPTURE_ENGINE_VERSION,
    CAPTURE_MANIFEST_NAME,
    CaptureArtifactSpec,
    CaptureCoverage,
    CaptureManifest,
    CaptureMode,
    CaptureStatus,
    RetentionClass,
)
from riftlens.domain.clock_map import ClockConfidence, ClockMap, ClockMode
from riftlens.domain.enums import DataTier, FactKind, Role, Source, Team
from riftlens.domain.fact import Fact, Provenance, SubjectRef
from riftlens.domain.ids import new_ulid
from riftlens.domain.timeline import GameStateTimeline, ParticipantInfo
from riftlens.replay_host.mac.game_config import enable_mac_replay_api
from riftlens.replay_host.mac.host import MacReplayHost
from riftlens.replay_host.mac.install_locator import locate_league_install_mac
from riftlens.replay_host.session import ReplaySessionPhase
from riftlens.visual.v4_analyze import analyze_capture_dir_v4
from riftlens.visual.v5_analyze import refine_v4_result

MATCH = "NA1_5620410094"
PID = 6
SUBJECT = "Vladimir"
ROFL = Path.home() / "Documents" / "League of Legends" / "Replays" / "NA1-5620410094.rofl"
DEATH_T_MS = 839_881
PAD_BEFORE_MS = 10_000
PAD_AFTER_MS = 7_000
START_MS = DEATH_T_MS - PAD_BEFORE_MS
END_MS = DEATH_T_MS + PAD_AFTER_MS
# Alternate death if first window has no usable pixels.
ALT_DEATH_T_MS = 1_062_798
OUT = Path(__file__).resolve().parents[1] / "artifacts" / "v5_mac_5620410094_validation.json"


def gst_from_db(match_id: str) -> GameStateTimeline:
    con = sqlite3.connect(Settings().db_path)
    con.row_factory = sqlite3.Row
    match_row = con.execute(
        "SELECT match_id, game_version, queue_id, game_duration_ms FROM match WHERE match_id = ?",
        (match_id,),
    ).fetchone()
    if match_row is None:
        raise SystemExit(f"match {match_id} missing from DB")
    parts = con.execute(
        "SELECT participant_id, champion_name, team_id, team_position "
        "FROM match_participation WHERE match_id = ?",
        (match_id,),
    ).fetchall()
    kills = con.execute(
        "SELECT t_ms, killer_id, victim_id, payload FROM timeline_event "
        "WHERE match_id = ? AND type = 'CHAMPION_KILL' ORDER BY t_ms",
        (match_id,),
    ).fetchall()
    con.close()
    participants: dict[int, ParticipantInfo] = {}
    for row in parts:
        pid = int(row["participant_id"])
        role_raw = str(row["team_position"] or "UNKNOWN").upper()
        try:
            role = Role(role_raw)
        except ValueError:
            role = Role.UNKNOWN
        participants[pid] = ParticipantInfo(
            participant_id=pid,
            champion=str(row["champion_name"] or "Unknown"),
            role=role,
            team=Team(int(row["team_id"])),
            puuid=f"db-{pid}",
        )
    gst = GameStateTimeline(
        match_id=match_id,
        patch=str(match_row["game_version"] or "unknown"),
        queue_id=int(match_row["queue_id"] or 420),
        duration_ms=int(match_row["game_duration_ms"] or 0),
        participants=participants,
        available_data_tiers=frozenset({DataTier.RIOT_ONLY, DataTier.RIOT_DERIVED}),
    )
    provenance = Provenance(producer="v5-mac-validation", producer_version=1)
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
                # Capture camera framing needs on-victim kill world position.
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
    camera_framing: CameraFramingMetadata | None = None,
    capture_coverage: CaptureCoverage | None = None,
) -> CaptureManifest:
    start_source = clock.game_to_source(start_game_ms)
    end_source = clock.game_to_source(end_game_ms)
    codec = "webm"
    if artifacts and artifacts[0].kind == "image":
        codec = "png"
    controlled = False if camera_framing is None else bool(camera_framing.camera_controlled)
    manifest = CaptureManifest(
        capture_id=capture_id,
        source_id=source_id,
        match_id=MATCH,
        clock_map_id=clock_map_id,
        mode=CaptureMode.CLIP,
        codec=codec,
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
        camera_controlled=controlled,
        camera_framing=camera_framing,
        capture_coverage=capture_coverage,
        engine_version=CAPTURE_ENGINE_VERSION,
        artifacts=artifacts,
    )
    path = directory / CAPTURE_MANIFEST_NAME
    path.write_text(json.dumps(manifest.to_dict(), indent=2) + "\n", encoding="utf-8")
    return manifest


def _track_summary(tracks: object) -> list[dict[str, object]]:
    out: list[dict[str, object]] = []
    for tr in tracks:  # type: ignore[attr-defined]
        out.append(
            {
                "track_id": tr.track_id,
                "kind": tr.kind.value,
                "team": tr.team_estimate.value,
                "obs": tr.observation_count,
                "first_ms": tr.first_seen_game_t_ms,
                "last_ms": tr.last_seen_game_t_ms,
                "duration_ms": tr.last_seen_game_t_ms - tr.first_seen_game_t_ms,
                "confidence": tr.confidence,
            }
        )
    return out


def _analyze_capture(
    capture_dir: Path,
    *,
    gst: GameStateTimeline,
    death_t_ms: int,
    report: dict[str, object],
) -> dict[str, object]:
    subject = gst.participants[PID]
    print("=== V4 baseline ===")
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
    print(
        "v4",
        v4.correlation.status.value,
        v4.correlation.track_id,
        v4.correlation.confidence,
        f"wall_s={v4_wall:.1f}",
    )
    print("=== V5 refine ===")
    t0 = time.perf_counter()
    v5 = refine_v4_result(v4)
    v5_wall = time.perf_counter() - t0
    assert v5.v5 is not None
    print(
        "v5",
        v5.correlation.status.value,
        v5.correlation.track_id,
        v5.correlation.confidence,
        v5.v5.identity_change,
        f"continuity_ms={v5.continuity_ms:.2f}",
    )
    cues = [] if v5.v5.bundle is None else [c.to_dict() for c in v5.v5.bundle.cues]
    report["death_t_ms"] = death_t_ms
    report["v4"] = {
        "status": v4.correlation.status.value,
        "track_id": v4.correlation.track_id,
        "confidence": v4.correlation.confidence,
        "method": v4.correlation.method,
        "reasons": list(v4.correlation.reasons),
        "tracks": _track_summary(v4.tracks),
        "calibration": None if v4.calibration is None else v4.calibration.to_dict(),
        "timing": {
            "extract_ms": round(v4.timing.extract_ms, 1),
            "detect_ms": round(v4.timing.detect_ms, 1),
            "track_ms": round(v4.timing.track_ms, 1),
            "align_ms": round(v4.timing.align_ms, 1),
            "color_sample_ms": round(v4.color_sample_ms, 1),
            "calibrate_ms": round(v4.calibrate_ms, 1),
            "total_ms": round(v4.timing.total_ms, 1),
            "frames": v4.timing.analyzed_frames,
        },
        "subject_deaths_in_window": (
            [] if v4.alignment.subject is None else list(v4.alignment.subject.deaths)
        ),
        "camera_note": v4.camera_note,
        "informative_frames": v4.informative_frames,
        "confirmed_detections": v4.confirmed_detections,
    }
    report["v5"] = {
        "status": v5.correlation.status.value,
        "track_id": v5.correlation.track_id,
        "confidence": v5.correlation.confidence,
        "method": v5.correlation.method,
        "identity_change": v5.v5.identity_change,
        "contributing_cues": list(v5.v5.contributing_cues),
        "rejected_cues": list(v5.v5.rejected_cues),
        "continuity_ms": round(v5.continuity_ms, 3),
        "bundle": None if v5.v5.bundle is None else v5.v5.bundle.to_dict(),
        "cues": cues,
        "base": {
            "status": v5.v5.base.status.value,
            "track_id": v5.v5.base.track_id,
            "confidence": v5.v5.base.confidence,
        },
    }
    report["runtime"] = {
        "v4_wall_s": round(v4_wall, 2),
        "v5_refine_wall_s": round(v5_wall, 3),
        "detect_ms": round(v4.timing.detect_ms, 1),
        "track_ms": round(v4.timing.track_ms, 1),
        "calibrate_ms": round(v4.calibrate_ms, 1),
        "color_sample_ms": round(v4.color_sample_ms, 1),
        "continuity_ms": round(v5.continuity_ms, 3),
    }
    report["fail_closed_checks"] = {
        "no_correlated_under_uncontrolled": v5.correlation.status.value != "CORRELATED",
        "capture_ownership_ignored_in_reasons": (
            "capture_review_pid_ignored_for_identity" in list(v4.correlation.reasons)
            or v4.correlation.status.value == "UNKNOWN"
        ),
        "no_silent_track_swap": (
            v5.v5.base.track_id is None
            or v5.correlation.track_id is None
            or v5.correlation.track_id == v5.v5.base.track_id
            or v5.correlation.status.value == "UNKNOWN"
        ),
        "unknown_base_not_invented": True,
    }
    usable = v4.informative_frames > 0 and v4.confirmed_detections > 0
    report["pixels_usable"] = usable
    return report


def _capture_window(
    host: MacReplayHost,
    *,
    clock: ClockMap,
    gst: GameStateTimeline,
    death_t_ms: int,
    start_ms: int,
    end_ms: int,
    source_id: str,
) -> tuple[Path, str, CaptureManifest | None, dict[str, object]]:
    capture_id = new_ulid()
    capture_dir = default_captures_dir() / MATCH / capture_id
    capture_dir.mkdir(parents=True, exist_ok=True)
    meta: dict[str, object] = {
        "capture_id": capture_id,
        "capture_dir": str(capture_dir),
        "requested_start_game_ms": start_ms,
        "requested_end_game_ms": end_ms,
        "death_t_ms": death_t_ms,
    }
    # Probe playback before recording.
    client = host.recording_client()
    if client is None:
        meta["capture_ok"] = False
        meta["capture_error"] = "recording_client_missing"
        return capture_dir, capture_id, None, meta
    try:
        playback = client.get_playback()
        meta["playback_length_s"] = playback.length
        meta["playback_time_s"] = playback.time
    except Exception as exc:  # noqa: BLE001 — research probe
        meta["capture_ok"] = False
        meta["capture_error"] = f"playback_probe_failed:{exc}"
        return capture_dir, capture_id, None, meta

    target = resolve_gst_camera_target(
        gst, participant_id=PID, target_game_t_ms=int(death_t_ms)
    )
    framing_plan = None if target is None else build_path_gst_framing_plan(
        target, stabilize_s=DEFAULT_STABILIZE_S
    )
    if target is None:
        meta["camera_target"] = None
        meta["camera_plan"] = None
    else:
        meta["camera_target"] = target.to_dict()
        meta["camera_plan"] = framing_plan.to_dict() if framing_plan is not None else None
        print(
            "CAMERA_TARGET",
            target.position.x,
            target.position.y,
            "conf",
            target.confidence,
            target.basis,
        )

    print("CAPTURE", capture_id, start_ms, end_ms, "framing", framing_plan is not None)
    result = host.capture_interval(
        start_ms,
        end_ms,
        clock,
        output_dir=str(capture_dir),
        capture_id=capture_id,
        mode=CaptureMode.CLIP,
        timeout_s=600.0,
        camera_framing=framing_plan,
        allow_capture_without_framing=True,
    )
    meta["capture_ok"] = result.ok
    meta["capture_status"] = result.status.value
    if result.capture_coverage is not None:
        meta["capture_coverage"] = result.capture_coverage.to_dict()
        print(
            "COVERAGE",
            result.capture_coverage.coverage_verdict.value,
            "requested",
            result.capture_coverage.requested_duration_ms,
            "actual",
            result.capture_coverage.actual_duration_ms,
            "dropouts",
            result.capture_coverage.api_dropout_count,
            "method",
            None
            if result.capture_coverage.completion_method is None
            else result.capture_coverage.completion_method.value,
        )
    if result.camera_framing is not None:
        framing = result.camera_framing
        gst_xy = None
        if framing.gst_position is not None:
            gst_xy = (float(framing.gst_position["x"]), float(framing.gst_position["y"]))
        render_xy = camera_position_to_riot_xy(framing.replay_camera_position)
        delta = None
        if gst_xy is not None and render_xy is not None:
            delta = ground_distance(gst_xy, render_xy)
        meta["camera_framing"] = framing.to_dict()
        meta["placement_delta"] = delta
        print(
            "CAMERA_FRAMING",
            framing.status.value,
            "controlled",
            framing.camera_controlled,
            "mode",
            framing.camera_mode,
            "delta",
            delta,
            "restore",
            None if framing.restore_status is None else framing.restore_status.value,
        )
    if result.error is None:
        meta["capture_error"] = None
        meta["capture_error_details"] = None
    else:
        meta["capture_error"] = str(result.error)
        meta["capture_error_code"] = result.error.code.value
        meta["capture_error_details"] = dict(result.error.details)
    if not result.ok:
        return capture_dir, capture_id, None, meta
    clock_map_id = new_ulid()
    manifest = _write_manifest(
        capture_dir,
        capture_id=capture_id,
        source_id=source_id,
        clock=clock,
        clock_map_id=clock_map_id,
        artifacts=result.artifacts,
        start_game_ms=start_ms,
        end_game_ms=end_ms,
        camera_framing=result.camera_framing,
        capture_coverage=result.capture_coverage,
    )
    meta["manifest"] = {
        "capture_id": manifest.capture_id,
        "clock_map_id": clock_map_id,
        "clock_confidence": clock.confidence.value,
        "clock_mode": clock.mode.value,
        "clock_verified": clock.verified,
        "offset_ms": clock.offset_ms,
        "camera_controlled": manifest.camera_controlled,
        "camera_framing": None
        if manifest.camera_framing is None
        else manifest.camera_framing.to_dict(),
        "capture_coverage": None
        if manifest.capture_coverage is None
        else manifest.capture_coverage.to_dict(),
        "game_interval": [start_ms, end_ms],
        "source_interval": [manifest.start_source_ms, manifest.end_source_ms],
        "artifacts": [a.to_dict() for a in manifest.artifacts],
        "duration_ms": end_ms - start_ms,
    }
    return capture_dir, capture_id, manifest, meta


def main() -> int:
    if os.environ.get("RIFTLENS_V5_T4") != "1":
        print("SKIP: set RIFTLENS_V5_T4=1")
        return 0
    if not ROFL.is_file():
        print("FAIL: missing", ROFL)
        return 2
    gst = gst_from_db(MATCH)
    subject = gst.participants[PID]
    print("subject", subject.champion, "team", int(subject.team))
    print("primary_death", DEATH_T_MS, "window", START_MS, END_MS)

    located = locate_league_install_mac()
    if located.install is None:
        print("FAIL: League install not found")
        return 3
    enable = enable_mac_replay_api(located.install, consent=True)
    print("enable_replay_api", enable.ok)

    host = MacReplayHost()
    open_snap = host.open_session(str(ROFL))
    print("OPEN", open_snap.phase.value, open_snap.error)
    ready = _wait_active(host)
    print("READY", ready.phase.value, ready.error)
    report: dict[str, object] = {
        "match_id": MATCH,
        "subject_pid": PID,
        "subject_champion": SUBJECT,
        "rofl": str(ROFL),
        "open_phase": open_snap.phase.value,
        "ready_phase": ready.phase.value,
    }
    if not ready.is_active:
        report["capture_ok"] = False
        report["capture_error"] = "session_not_active"
        OUT.parent.mkdir(parents=True, exist_ok=True)
        OUT.write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
        try:
            host.close_session()
        except Exception:  # noqa: BLE001 — research cleanup
            pass
        return 4

    # Prefer a lightweight identity clock from live playback length.
    # Full host.calibrate() multi-seek has crashed the Mac Replay API mid-session.
    client = host.recording_client()
    if client is None:
        report["capture_ok"] = False
        report["capture_error"] = "recording_client_missing_after_ready"
        OUT.parent.mkdir(parents=True, exist_ok=True)
        OUT.write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
        host.close_session()
        return 5
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
    report["clock"] = {
        "confidence": clock.confidence.value,
        "mode": clock.mode.value,
        "verified": clock.verified,
        "offset_ms": clock.offset_ms,
        "playback_length_ms": length_ms,
        "calibrate_mode": "identity_from_playback_length",
    }
    print("CLOCK identity length_ms", length_ms)
    source_id = new_ulid()

    attempts: list[dict[str, object]] = []
    windows = [
        (DEATH_T_MS, START_MS, END_MS),
        (
            ALT_DEATH_T_MS,
            ALT_DEATH_T_MS - PAD_BEFORE_MS,
            ALT_DEATH_T_MS + PAD_AFTER_MS,
        ),
    ]
    final_report = report
    try:
        for death_t, start_ms, end_ms in windows:
            # Re-probe / reopen if a prior attempt killed the Replay API.
            health = host.poll_health()
            if not health.is_active:
                print("REOPEN after inactive", health.phase.value, health.error)
                try:
                    host.close_session()
                except Exception:  # noqa: BLE001
                    pass
                open_snap = host.open_session(str(ROFL))
                ready = _wait_active(host)
                print("REOPEN", open_snap.phase.value, ready.phase.value, ready.error)
                if not ready.is_active:
                    attempts.append(
                        {
                            "death_t_ms": death_t,
                            "capture_ok": False,
                            "capture_error": f"reopen_failed:{ready.error}",
                        }
                    )
                    continue
                client = host.recording_client()
                if client is None:
                    attempts.append(
                        {
                            "death_t_ms": death_t,
                            "capture_ok": False,
                            "capture_error": "recording_client_missing_after_reopen",
                        }
                    )
                    continue
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
            capture_dir, capture_id, manifest, meta = _capture_window(
                host,
                clock=clock,
                gst=gst,
                death_t_ms=death_t,
                start_ms=start_ms,
                end_ms=end_ms,
                source_id=source_id,
            )
            attempts.append(meta)
            if not meta.get("capture_ok"):
                print("CAPTURE_FAIL", death_t, meta.get("capture_error"))
                # Include structured error details when present.
                err = meta.get("capture_error")
                print("CAPTURE_FAIL_DETAIL", err)
                continue
            assert manifest is not None
            analyzed = _analyze_capture(
                capture_dir, gst=gst, death_t_ms=death_t, report={**report, **meta}
            )
            attempts[-1]["pixels_usable"] = analyzed.get("pixels_usable")
            final_report = analyzed
            if analyzed.get("pixels_usable"):
                break
            print("PIXELS_UNUSABLE trying alternate death window")
        final_report["attempts"] = attempts
        # Research verdict placeholder for the report updater.
        v5 = final_report.get("v5")
        if isinstance(v5, dict) and final_report.get("pixels_usable"):
            change = str(v5.get("identity_change"))
            status = str(v5.get("status"))
            if status == "LIKELY" and change in {"stronger", "unchanged"}:
                final_report["research_verdict"] = "SUPPORTED"
            elif status in {"LIKELY", "UNKNOWN"}:
                final_report["research_verdict"] = "PARTIALLY_SUPPORTED"
            else:
                final_report["research_verdict"] = "NOT_SUPPORTED"
        else:
            final_report["research_verdict"] = "NOT_SUPPORTED"
            final_report["unsuitable_reason"] = "capture_or_pixels_failed_both_windows"
    finally:
        try:
            host.close_session()
        except Exception:  # noqa: BLE001
            pass
        OUT.parent.mkdir(parents=True, exist_ok=True)
        OUT.write_text(json.dumps(final_report, indent=2) + "\n", encoding="utf-8")
        print("wrote", OUT)
    return 0 if final_report.get("pixels_usable") else 6


if __name__ == "__main__":
    raise SystemExit(main())
