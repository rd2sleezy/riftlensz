"""Subject-camera attachment spike against NA1_5620410094 (macOS Replay API).

Set RIFTLENS_SUBJECT_ATTACH_SPIKE=1. Does not change production CONTROLLED_SUBJECT.
"""

from __future__ import annotations

import json
import os
import sqlite3
import subprocess
import sys
import time
from collections.abc import Mapping
from pathlib import Path
from typing import Any

SPIKE_ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(SPIKE_ROOT))

from attachment import (  # noqa: E402
    ReattachSequence,
    attach_patch,
    evaluate_attempt,
    nearest_participant,
    rank_reattach_sequences,
)
from identity import (  # noqa: E402
    MappingStatus,
    RosterEntry,
    plan_subject_selection,
)
from render_state import (  # noqa: E402
    camera_ground_xz,
    ground_distance,
    interesting_render,
    parse_render,
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
from riftlens.replay_host.api.live_client import LiveClientDataClient  # noqa: E402
from riftlens.replay_host.api.replay_client import ReplayApiClient  # noqa: E402
from riftlens.replay_host.capture.recording import run_capture  # noqa: E402
from riftlens.replay_host.mac.game_config import enable_mac_replay_api  # noqa: E402
from riftlens.replay_host.mac.install_locator import locate_league_install_mac  # noqa: E402
from riftlens.visual.v4_analyze import analyze_capture_dir_v4  # noqa: E402
from riftlens.visual.v5_analyze import refine_v4_result  # noqa: E402

MATCH = "NA1_5620410094"
PID = 6
SUBJECT = "Vladimir"
DEATH_T_MS = 839_881
START_MS = 829_881
END_MS = 846_881
ROFL = Path.home() / "Documents" / "League of Legends" / "Replays" / "NA1-5620410094.rofl"
OUT = SPIKE_ROOT / "artifacts" / "subject_attach_spike.json"
FRAMES = SPIKE_ROOT / "artifacts" / "frames"
PATH_GST_CAPTURE = (
    Path.home() / ".riftlens" / "captures" / MATCH / "01M00NSCH421BEY2SP3PADQT8A"
)
OPENAPI_PATHS = (
    "/swagger/v1/swagger.json",
    "/swagger/v2/swagger.json",
    "/openapi.json",
    "/swagger.json",
    "/replay/swagger.json",
)


class StickyAttachClient:
    """Re-apply selection/attach after capture seek (spike-only)."""

    def __init__(self, inner: ReplayApiClient, patch: Mapping[str, Any]) -> None:
        self._inner = inner
        self._patch = dict(patch)

    def get_recording(self) -> Any:
        return self._inner.get_recording()

    def set_recording(self, patch: Mapping[str, Any]) -> Any:
        try:
            self._inner.set_render(self._patch)
        except Exception:  # noqa: BLE001 — spike
            pass
        return self._inner.set_recording(patch)

    def get_playback(self) -> Any:
        return self._inner.get_playback()

    def set_playback(self, **kwargs: Any) -> Any:
        result = self._inner.set_playback(**kwargs)
        if kwargs.get("time") is not None:
            try:
                self._inner.set_render(self._patch)
            except Exception:  # noqa: BLE001
                pass
        return result

    def get_render(self) -> Any:
        return self._inner.get_render()

    def set_render(self, patch: Mapping[str, Any]) -> Any:
        return self._inner.set_render(patch)


def _dump(obj: Any) -> Any:
    if hasattr(obj, "model_dump"):
        return obj.model_dump()
    return obj


def load_roster(match_id: str) -> tuple[RosterEntry, ...]:
    con = sqlite3.connect(Settings().db_path)
    rows = con.execute(
        "SELECT participant_id, champion_name, stats_json "
        "FROM match_participation WHERE match_id=? ORDER BY participant_id",
        (match_id,),
    ).fetchall()
    con.close()
    out: list[RosterEntry] = []
    for pid, champ, raw in rows:
        stats = json.loads(raw or "{}")
        out.append(
            RosterEntry(
                participant_id=int(pid),
                champion_name=str(champ),
                riot_id_game_name=stats.get("riotIdGameName") or None,
                riot_id_tagline=stats.get("riotIdTagline") or None,
                summoner_name=stats.get("summonerName") or None,
            )
        )
    return tuple(out)


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
    provenance = Provenance(producer="subject-attach-spike", producer_version=1)
    facts: list[Fact] = []
    for row in kills:
        payload: dict[str, object] = {"killerId": row["killer_id"], "victimId": row["victim_id"]}
        raw = row["payload"]
        if isinstance(raw, str) and raw:
            try:
                loaded = json.loads(raw)
            except json.JSONDecodeError:
                loaded = {}
            if isinstance(loaded, dict) and isinstance(loaded.get("position"), dict):
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


def gst_positions_at(match_id: str, t_ms: int) -> dict[int, tuple[float, float]]:
    """Interpolate participant_frame positions to ``t_ms`` (60s samples)."""
    con = sqlite3.connect(Settings().db_path)
    rows = con.execute(
        "SELECT participant_id, t_ms, pos_x, pos_y FROM participant_frame "
        "WHERE match_id=? AND pos_x IS NOT NULL ORDER BY participant_id, t_ms",
        (match_id,),
    ).fetchall()
    con.close()
    by_pid: dict[int, list[tuple[int, float, float]]] = {}
    for pid, ts, x, y in rows:
        by_pid.setdefault(int(pid), []).append((int(ts), float(x), float(y)))
    out: dict[int, tuple[float, float]] = {}
    for pid, samples in by_pid.items():
        if not samples:
            continue
        if t_ms <= samples[0][0]:
            out[pid] = (samples[0][1], samples[0][2])
            continue
        if t_ms >= samples[-1][0]:
            out[pid] = (samples[-1][1], samples[-1][2])
            continue
        for i in range(1, len(samples)):
            t0, x0, y0 = samples[i - 1]
            t1, x1, y1 = samples[i]
            if t0 <= t_ms <= t1:
                if t1 == t0:
                    out[pid] = (x0, y0)
                else:
                    a = (t_ms - t0) / (t1 - t0)
                    out[pid] = (x0 + a * (x1 - x0), y0 + a * (y1 - y0))
                break
    return out


def death_position(match_id: str, death_t_ms: int, pid: int) -> tuple[float, float] | None:
    con = sqlite3.connect(Settings().db_path)
    row = con.execute(
        "SELECT payload FROM timeline_event "
        "WHERE match_id=? AND type='CHAMPION_KILL' AND victim_id=? AND t_ms=?",
        (match_id, pid, death_t_ms),
    ).fetchone()
    con.close()
    if not row or not row[0]:
        return None
    try:
        pos = json.loads(row[0]).get("position") or {}
        return float(pos["x"]), float(pos["y"])
    except (json.JSONDecodeError, KeyError, TypeError, ValueError):
        return None


def await_seek(client: ReplayApiClient, target_s: float, *, timeout_s: float = 90.0) -> dict[str, Any]:
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
        except Exception as exc:  # noqa: BLE001
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


def replay_ready(*, timeout_s: float = 5.0) -> bool:
    try:
        ReplayApiClient(timeout_s=timeout_s, connect_timeout_s=2.0, max_retries=0).get_game()
        return True
    except Exception:  # noqa: BLE001
        return False


def enable_and_launch() -> dict[str, Any]:
    located = locate_league_install_mac()
    if located.install is None:
        return {"enable_ok": False, "launched": False, "ready": False, "error": "install_not_found"}
    enable = enable_mac_replay_api(located.install, consent=True)
    launched = False
    if not replay_ready():
        script = (
            'tell application "Terminal" to do script '
            '"cd \\"/Applications/League of Legends.app/Contents/LoL/Game\\" && '
            './LeagueofLegends.app/Contents/MacOS/LeagueofLegends '
            '\\"/Users/rylanddunn/Documents/League of Legends/Replays/NA1-5620410094.rofl\\" '
            '-GameBaseDir=\\"/Applications/League of Legends.app/Contents/LoL/Game\\" '
            '-Region=NA -PlatformID=NA1 -Locale=en_US -SkipBuild"'
        )
        subprocess.run(  # noqa: S603
            ["osascript", "-e", script],
            check=False,
            timeout=15,
        )
        launched = True
        deadline = time.monotonic() + 180.0
        while time.monotonic() < deadline and not replay_ready(timeout_s=3.0):
            time.sleep(2.0)
    return {"enable_ok": enable.ok, "launched": launched, "ready": replay_ready()}


def fetch_openapi(client: ReplayApiClient) -> dict[str, Any]:
    out: dict[str, Any] = {"paths": {}}
    for path in OPENAPI_PATHS:
        payload = client.try_get_json(path)
        out["paths"][path] = payload is not None
        if not isinstance(payload, dict):
            continue
        paths = payload.get("paths") or {}
        render = paths.get("/replay/render") or paths.get("replay/render")
        out["render_path"] = render
        schemas = (payload.get("components") or {}).get("schemas") or payload.get("definitions")
        if isinstance(schemas, dict):
            for name, schema in schemas.items():
                if "render" in str(name).lower() or (
                    isinstance(schema, dict)
                    and "selectionName" in str(schema)
                ):
                    out["render_schema_name"] = name
                    props = schema.get("properties") if isinstance(schema, dict) else None
                    if isinstance(props, dict):
                        out["render_property_names"] = sorted(props)
        break
    return out


def try_selection(
    client: ReplayApiClient,
    *,
    label: str,
    name: str,
    attached: bool,
    roster: tuple[RosterEntry, ...],
    intended_pid: int | None,
    camera_mode: str | None = None,
) -> dict[str, Any]:
    before = _dump(client.get_render())
    patch = attach_patch(name, camera_attached=attached, camera_mode=camera_mode)
    client.set_render(patch)
    time.sleep(0.6)
    after = _dump(client.get_render())
    attempt = evaluate_attempt(
        label=label,
        patch=patch,
        before=before,
        after=after,
        roster=roster,
        intended_pid=intended_pid,
    )
    print(
        "SEL",
        label,
        attempt.resolved.selection_name,
        attempt.resolved.camera_attached,
        attempt.request_status.value,
        attempt.mapping_status.value,
        flush=True,
    )
    return {
        "label": label,
        "patch": patch,
        "before": interesting_render(before),
        "after": interesting_render(after),
        "after_full_keys": sorted(after),
        "request_status": attempt.request_status.value,
        "mapping_status": attempt.mapping_status.value,
        "resolved_selectionName": attempt.resolved.selection_name,
        "cameraAttached": attempt.resolved.camera_attached,
        "has_participant_id": attempt.resolved.has_participant_id,
    }


def sample_follow(
    client: ReplayApiClient,
    *,
    match_id: str,
    seconds: float = 4.0,
) -> dict[str, Any]:
    samples: list[dict[str, Any]] = []
    client.set_playback(paused=False, speed=1.0, readback=False)
    t_end = time.monotonic() + seconds
    while time.monotonic() < t_end:
        pb = client.get_playback()
        raw = _dump(client.get_render())
        parsed = parse_render(raw)
        cam = camera_ground_xz(parsed.camera_position)
        game_ms = max(0, int(round(float(pb.time) * 1000.0)))
        positions = gst_positions_at(match_id, game_ms)
        nearest = None if cam is None else nearest_participant(cam, positions)
        subject = positions.get(PID)
        dist_subject = None if cam is None or subject is None else round(ground_distance(cam, subject), 1)
        samples.append(
            {
                "playback_s": pb.time,
                "selectionName": parsed.selection_name,
                "cameraAttached": parsed.camera_attached,
                "cameraMode": parsed.camera_mode,
                "camera_xy": cam,
                "nearest_pid": None if nearest is None else nearest[0],
                "nearest_dist": None if nearest is None else round(nearest[1], 1),
                "subject_dist": dist_subject,
            }
        )
        time.sleep(0.5)
    client.set_playback(paused=True, readback=False)
    nearest_ids = [s["nearest_pid"] for s in samples if s["nearest_pid"] is not None]
    subject_share = 0.0 if not nearest_ids else nearest_ids.count(PID) / len(nearest_ids)
    moved = False
    if len(samples) >= 2 and samples[0]["camera_xy"] and samples[-1]["camera_xy"]:
        moved = ground_distance(samples[0]["camera_xy"], samples[-1]["camera_xy"]) > 50.0
    return {
        "samples": samples,
        "camera_moved": moved,
        "subject_nearest_fraction": round(subject_share, 3),
        "subject_is_nearest_majority": subject_share >= 0.6,
    }


def write_manifest(
    directory: Path,
    *,
    capture_id: str,
    clock: ClockMap,
    artifacts: tuple[CaptureArtifactSpec, ...],
    camera_note: str,
) -> CaptureManifest:
    manifest = CaptureManifest(
        capture_id=capture_id,
        source_id=new_ulid(),
        match_id=MATCH,
        clock_map_id=new_ulid(),
        mode=CaptureMode.CLIP,
        codec="webm",
        fps=30.0,
        requested_start_game_ms=START_MS,
        requested_end_game_ms=END_MS,
        start_source_ms=START_MS,
        end_source_ms=END_MS,
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
    (directory / CAPTURE_MANIFEST_NAME).write_text(
        json.dumps(manifest.to_dict(), indent=2) + "\n", encoding="utf-8"
    )
    (directory / "subject_attach_note.txt").write_text(camera_note + "\n", encoding="utf-8")
    return manifest


def extract_frames(webm: Path, out_dir: Path, indices: set[int]) -> list[str]:
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
            if cv2.imwrite(str(path), frame):
                saved.append(str(path.relative_to(SPIKE_ROOT)))
        n += 1
    cap.release()
    return saved


def analyze_dir(capture_dir: Path, gst: GameStateTimeline) -> dict[str, Any]:
    subject = gst.participants[PID]
    v4 = analyze_capture_dir_v4(
        capture_dir,
        subject_pid=PID,
        subject_champion=SUBJECT,
        capture_review_pid=PID,
        gst=gst,
        subject_team=subject.team,
    )
    v5 = refine_v4_result(v4)
    tracks = []
    longest = 0
    for tr in v4.tracks:
        dur = int(tr.last_seen_game_t_ms) - int(tr.first_seen_game_t_ms)
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
    return {
        "v4_status": v4.correlation.status.value,
        "v4_confidence": v4.correlation.confidence,
        "v4_track_id": v4.correlation.track_id,
        "v4_reasons": list(v4.correlation.reasons),
        "v5_status": v5.correlation.status.value,
        "v5_identity_change": None if v5.v5 is None else v5.v5.identity_change,
        "tracks": tracks,
        "track_count": len(tracks),
        "longest_track_ms": longest,
        "confirmed_detections": sum(t["obs"] for t in tracks),
        "analyzed_frames": v4.timing.analyzed_frames,
    }


def main() -> int:
    if os.environ.get("RIFTLENS_SUBJECT_ATTACH_SPIKE") != "1":
        print("Set RIFTLENS_SUBJECT_ATTACH_SPIKE=1", file=sys.stderr)
        return 2
    roster = load_roster(MATCH)
    plan = plan_subject_selection(roster, PID)
    gst = gst_from_db(MATCH)
    death_xy = death_position(MATCH, DEATH_T_MS, PID)
    report: dict[str, Any] = {
        "match_id": MATCH,
        "subject_pid": PID,
        "subject_champion": SUBJECT,
        "death_t_ms": DEATH_T_MS,
        "roster": [
            {
                "participant_id": e.participant_id,
                "champion_name": e.champion_name,
                "riot_id_game_name": e.riot_id_game_name,
                "riot_id_tagline": e.riot_id_tagline,
                "summoner_name": e.summoner_name,
            }
            for e in roster
        ],
        "selection_plan": {
            "status": plan.status.value,
            "attach_allowed": plan.attach_allowed,
            "preferred": [
                {"kind": c.kind.value, "value": c.value, "unique": c.unique} for c in plan.preferred
            ],
            "rejected_reason": plan.rejected_reason,
        },
        "hypothesis": (
            "selectionName + cameraAttached can deterministically follow the analyzed "
            "participant when the selection token uniquely reverse-maps to that pid."
        ),
    }
    launch = enable_and_launch()
    report["launch"] = launch
    print("LAUNCH", launch, flush=True)
    if not launch.get("ready"):
        report["environment"] = "inconclusive"
        report["research_verdict"] = "INCONCLUSIVE"
        _write(report)
        return 3
    client = ReplayApiClient(timeout_s=15.0, connect_timeout_s=2.0, max_retries=2)
    client.set_playback(paused=True, speed=1.0, readback=False)
    await_seek(client, (DEATH_T_MS - 10_000) / 1000.0)
    time.sleep(1.0)
    raw_before = _dump(client.get_render())
    parsed_before = parse_render(raw_before)
    report["render_schema"] = {
        "keys": sorted(raw_before),
        "identity_fields": parsed_before.identity_fields,
        "has_participant_id": parsed_before.has_participant_id,
        "champions_field_type": type(raw_before.get("champions")).__name__,
        "characters_field_type": type(raw_before.get("characters")).__name__,
        "baseline": interesting_render(raw_before),
    }
    report["openapi"] = fetch_openapi(client)
    lcd: dict[str, Any] = {}
    try:
        live = LiveClientDataClient(timeout_s=8.0, connect_timeout_s=2.0)
        players = [_dump(p) for p in live.get_playerlist()]
        lcd["playerlist_count"] = len(players)
        lcd["playerlist_keys"] = sorted(players[0]) if players else []
        lcd["activeplayername"] = live.get_activeplayername()
        lcd["players"] = [
            {
                "championName": p.get("championName"),
                "summonerName": p.get("summonerName"),
                "riotId": p.get("riotId") or p.get("riotIdGameName"),
                "team": p.get("team"),
            }
            for p in players
        ]
    except Exception as exc:  # noqa: BLE001
        lcd["error"] = str(exc)
    report["lcd"] = lcd

    fizz = next(e for e in roster if e.champion_name == "Fizz")
    mundo = next(e for e in roster if e.champion_name == "DrMundo")
    selection_tests = [
        try_selection(
            client, label="champion_Vladimir", name="Vladimir", attached=True,
            roster=roster, intended_pid=PID,
        ),
        try_selection(
            client, label="champion_vladimir_lower", name="vladimir", attached=True,
            roster=roster, intended_pid=PID,
        ),
        try_selection(
            client, label="champion_VLADIMIR_upper", name="VLADIMIR", attached=True,
            roster=roster, intended_pid=PID,
        ),
        try_selection(
            client, label="riot_immynator", name="immynator", attached=True,
            roster=roster, intended_pid=PID,
        ),
        try_selection(
            client, label="riot_tagged", name="immynator#loler", attached=True,
            roster=roster, intended_pid=PID,
        ),
        try_selection(
            client, label="pid_string_6", name="6", attached=True,
            roster=roster, intended_pid=PID,
        ),
        try_selection(
            client, label="invalid_NotAChampion", name="NotAChampion", attached=True,
            roster=roster, intended_pid=PID,
        ),
        try_selection(
            client, label="format_DrMundo", name="DrMundo", attached=True,
            roster=roster, intended_pid=mundo.participant_id,
        ),
        try_selection(
            client, label="format_Dr_Mundo", name="Dr. Mundo", attached=True,
            roster=roster, intended_pid=mundo.participant_id,
        ),
        try_selection(
            client, label="switch_Fizz", name="Fizz", attached=True,
            roster=roster, intended_pid=fizz.participant_id,
        ),
        try_selection(
            client, label="switch_back_Vladimir", name="Vladimir", attached=True,
            roster=roster, intended_pid=PID,
        ),
        try_selection(
            client, label="clear_empty", name="", attached=False,
            roster=roster, intended_pid=PID,
        ),
    ]
    report["selection_tests"] = selection_tests
    vlad_test = next(t for t in selection_tests if t["label"] == "champion_Vladimir")
    reverse_mapped = vlad_test["mapping_status"] == MappingStatus.UNIQUE.value
    report["participant_mapping"] = {
        "riot_pid": PID,
        "match_v5_champion": SUBJECT,
        "match_v5_riot_id": "immynator",
        "replay_selection_target": vlad_test["resolved_selectionName"],
        "readback_cameraAttached": vlad_test["cameraAttached"],
        "reverse_mapped": reverse_mapped,
        "champion_unique_in_match": True,
        "api_has_participant_id": bool(vlad_test.get("has_participant_id")),
        "limitation": (
            "Replay API exposes selectionName only; no participant/entity id. "
            "Identity is proven by unique reverse-map of resolved name onto MATCH-V5."
        ),
    }

    # Re-attach Vladimir for semantics / seek / capture.
    client.set_render(attach_patch("Vladimir", camera_attached=True, camera_mode="top"))
    time.sleep(0.5)
    await_seek(client, (DEATH_T_MS - 10_000) / 1000.0)
    time.sleep(0.8)
    after_seek = parse_render(_dump(client.get_render()))
    attach_survives = bool(after_seek.camera_attached) and bool(after_seek.selection_name)
    if not attach_survives:
        client.set_render(attach_patch("Vladimir", camera_attached=True, camera_mode="top"))
        time.sleep(0.6)
        restored = parse_render(_dump(client.get_render()))
        seek_then_attach = bool(restored.camera_attached) and restored.selection_name != ""
    else:
        seek_then_attach = True
        restored = after_seek
    report["seek_attach_then_seek"] = {
        "selectionName": after_seek.selection_name,
        "cameraAttached": after_seek.camera_attached,
        "survived": attach_survives,
    }

    follow = sample_follow(client, match_id=MATCH, seconds=4.0)
    report["attachment_semantics"] = follow
    report["attach_visually_works"] = bool(follow.get("camera_moved") or follow.get("subject_is_nearest_majority"))

    await_seek(client, DEATH_T_MS / 1000.0)
    time.sleep(0.8)
    at_death = parse_render(_dump(client.get_render()))
    cam_death = camera_ground_xz(at_death.camera_position)
    dist_death = None
    if cam_death is not None and death_xy is not None:
        dist_death = round(ground_distance(cam_death, death_xy), 1)
    report["at_death"] = {
        "selectionName": at_death.selection_name,
        "cameraAttached": at_death.camera_attached,
        "camera_xy": cam_death,
        "gst_death_xy": death_xy,
        "distance_to_death": dist_death,
    }
    await_seek(client, (DEATH_T_MS + 4_000) / 1000.0)
    time.sleep(0.8)
    after_death_raw = _dump(client.get_render())
    report["after_death"] = interesting_render(after_death_raw)

    client.set_render({"cameraMode": "path"})
    time.sleep(0.4)
    mode_change = parse_render(_dump(client.get_render()))
    report["after_camera_mode_path"] = {
        "cameraMode": mode_change.camera_mode,
        "cameraAttached": mode_change.camera_attached,
        "selectionName": mode_change.selection_name,
    }
    client.set_render(attach_patch("Vladimir", camera_attached=True, camera_mode="top"))
    time.sleep(0.4)

    ranked = rank_reattach_sequences(
        attach_survives_seek=attach_survives,
        seek_clears_attach=not attach_survives,
        seek_then_attach_works=seek_then_attach,
        seek_wait_attach_works=seek_then_attach,
    )
    report["seek_behavior"] = {
        "attach_survives_seek": attach_survives,
        "seek_then_attach_works": seek_then_attach,
        "ranked_sequences": [item.value for item in ranked],
        "preferred": ranked[0].value if ranked else ReattachSequence.SEEK_THEN_ATTACH.value,
    }
    _write(report)

    # Capture if mapping + follow look trustworthy.
    skip_capture = os.environ.get("RIFTLENS_SKIP_ATTACH_CAPTURE") == "1"
    capture_block: dict[str, Any] = {"skipped": skip_capture}
    if not skip_capture and reverse_mapped:
        try:
            patch = attach_patch("Vladimir", camera_attached=True, camera_mode="top")
            client.set_render(patch)
            time.sleep(0.5)
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
            capture_id = "attach_" + new_ulid()
            out_dir = default_captures_dir() / MATCH / capture_id
            out_dir.mkdir(parents=True, exist_ok=True)
            sticky = StickyAttachClient(client, patch)
            t0 = time.perf_counter()
            result = run_capture(
                client=sticky,  # type: ignore[arg-type]
                clock=clock,
                capture_id=capture_id,
                start_game_ms=START_MS,
                end_game_ms=END_MS,
                directory=out_dir,
                mode=CaptureMode.CLIP,
                fps=30.0,
                timeout_s=90.0,
                allow_capture_without_framing=True,
                enforce_frame_rate=False,
            )
            wall = round(time.perf_counter() - t0, 2)
            after_cap = interesting_render(_dump(client.get_render()))
            capture_block = {
                "skipped": False,
                "ok": result.ok,
                "status": result.status.value,
                "capture_id": capture_id,
                "capture_dir": str(out_dir),
                "wall_s": wall,
                "error": None if result.error is None else result.error.code.value,
                "coverage": None
                if result.capture_coverage is None
                else result.capture_coverage.to_dict(),
                "after_capture_render": after_cap,
            }
            if result.ok and result.artifacts:
                write_manifest(
                    out_dir,
                    capture_id=capture_id,
                    clock=clock,
                    artifacts=result.artifacts,
                    camera_note="selectionName=Vladimir cameraAttached=true cameraMode=top",
                )
                webm = next(
                    (
                        out_dir / spec.relative_path
                        for spec in result.artifacts
                        if spec.relative_path.endswith(".webm")
                    ),
                    None,
                )
                if webm is not None and webm.is_file():
                    capture_block["frames"] = extract_frames(webm, FRAMES / "attach", {0, 30, 90, 150})
                try:
                    capture_block["analysis"] = analyze_dir(out_dir, gst)
                except Exception as exc:  # noqa: BLE001
                    capture_block["analysis_error"] = str(exc)
            print("CAPTURE", capture_block.get("ok"), capture_block.get("error"), flush=True)
        except Exception as exc:  # noqa: BLE001
            capture_block = {"skipped": False, "ok": False, "error": str(exc)}
            print("CAPTURE_EXC", exc, flush=True)
    report["capture"] = capture_block

    path_gst: dict[str, Any] = {"path": str(PATH_GST_CAPTURE), "present": PATH_GST_CAPTURE.is_dir()}
    if PATH_GST_CAPTURE.is_dir():
        try:
            path_gst["analysis"] = analyze_dir(PATH_GST_CAPTURE, gst)
        except Exception as exc:  # noqa: BLE001
            path_gst["analysis_error"] = str(exc)
    report["path_gst_comparison"] = path_gst
    report["research_verdict"] = "SUBJECT_ATTACH_PARTIAL"
    _write(report)
    print("VERDICT", report["research_verdict"], flush=True)
    return 0


def _write(report: dict[str, Any]) -> None:
    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(json.dumps(report, indent=2, default=str) + "\n", encoding="utf-8")


if __name__ == "__main__":
    raise SystemExit(main())
