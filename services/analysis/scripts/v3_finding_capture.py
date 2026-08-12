"""Research-only V.3 finding-window capture + V.2 baseline analysis.

Target: NA1_5614479225 Vladimir (pid resolved from MATCH-V5, not assumed).

Set RIFTLENS_V3_T4=1 to request a real R.10 capture after the Replay API is
reachable. Without the flag this script only resolves the finding window.

Previous Kaisa NA1_5617764200 T4 was abandoned because that replay was no
longer practically available through League — not because the visual
architecture failed.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import os
import sqlite3
import time
from pathlib import Path

from riftlens.adapters.db.engine import init_database, make_session_factory
from riftlens.adapters.db.repositories import (
    SqlCaptureRepository,
    SqlGameplayRepository,
    SqlMatchRepository,
)
from riftlens.config import get_settings
from riftlens.domain.capture import CaptureStatus
from riftlens.domain.enums import DataTier, FactKind, Role, Source, Team
from riftlens.domain.fact import Fact, Provenance, SubjectRef
from riftlens.domain.timeline import GameStateTimeline, ParticipantInfo
from riftlens.gameplay.service import GameplaySourceService
from riftlens.replay_host.capture.capture_service import CaptureService
from riftlens.replay_host.factory import create_replay_host
from riftlens.replay_host.launch_strategies import UserAssistedStrategy
from riftlens.replay_host.supervisor import (
    ReplayProcessSupervisor,
    default_api_transport,
)
from riftlens.replay_host.windows.capability_probe import probe_replay_api_capability
from riftlens.visual.report import (
    StructuredClaim,
    classify_v1_against_claim,
    format_v1_timeline,
)
from riftlens.visual.v2_analyze import DEFAULT_V2_SAMPLE_FPS, analyze_capture_dir_v2
from riftlens.visual.window import (
    FindingStamp,
    PlannedCapture,
    capture_covers_window,
    capture_request_for_window,
    capture_window_for_finding,
    refuse_automatic_capture,
    require_explicit_capture,
    typed_from_replay_error,
)

MATCH = "NA1_5614479225"
ROFL_BASENAME = "NA1-5614479225.rofl"
SUBJECT_CHAMPION = "Vladimir"
# Selected V.3 finding: R-003 death @ 15:03 (resolved from persisted review).
PREFERRED_FINDING_ID = "01KZT1SW2SRV24TZF5499AR0ER"
PREFERRED_RULE_ID = "R-003"
PREFERRED_T_MS = 903_411
PAD_BEFORE_MS = 12_000
PAD_AFTER_MS = 15_000


def _db_path() -> Path:
    return Path(os.environ["APPDATA"]) / "RiftLens" / "riftlens.db"


def _resolve_subject_pid(match_id: str, champion: str) -> int:
    con = sqlite3.connect(_db_path())
    con.row_factory = sqlite3.Row
    rows = con.execute(
        """
        SELECT participant_id, champion_name FROM match_participation
        WHERE match_id = ?
        ORDER BY participant_id
        """,
        (match_id,),
    ).fetchall()
    con.close()
    hits = [
        int(row["participant_id"])
        for row in rows
        if str(row["champion_name"] or "").lower() == champion.lower()
    ]
    if len(hits) != 1:
        raise SystemExit(f"expected one {champion} participant, found {hits} in {match_id}")
    return hits[0]


def _load_findings(match_id: str, participant_id: int) -> list[FindingStamp]:
    con = sqlite3.connect(_db_path())
    con.row_factory = sqlite3.Row
    rows = con.execute(
        """
        SELECT f.id, f.review_id, f.rule_id, f.t_ms, f.t_end_ms, f.title,
               r.match_id, r.participant_id
        FROM finding f JOIN review r ON r.id = f.review_id
        WHERE r.match_id = ? AND r.participant_id = ?
        ORDER BY f.t_ms
        """,
        (match_id, participant_id),
    ).fetchall()
    con.close()
    return [
        FindingStamp(
            finding_id=str(row["id"]),
            rule_id=str(row["rule_id"]),
            t_ms=int(row["t_ms"]),
            match_id=str(row["match_id"]),
            review_id=str(row["review_id"]),
            t_end_ms=None if row["t_end_ms"] is None else int(row["t_end_ms"]),
            participant_id=int(row["participant_id"]),
            title=None if row["title"] is None else str(row["title"]),
        )
        for row in rows
    ]


def _select_v3_finding(findings: list[FindingStamp]) -> FindingStamp:
    for item in findings:
        if item.finding_id == PREFERRED_FINDING_ID:
            return item
    matched = [
        item
        for item in findings
        if item.rule_id == PREFERRED_RULE_ID and abs(item.t_ms - PREFERRED_T_MS) < 2_000
    ]
    if not matched:
        raise SystemExit("V.3 preferred R-003 finding not found in persisted review")
    return matched[0]


def _latest_source_and_clock(match_id: str) -> tuple[str | None, str | None, int | None]:
    con = sqlite3.connect(_db_path())
    con.row_factory = sqlite3.Row
    source = con.execute(
        """
        SELECT id FROM gameplay_source WHERE match_id = ?
        ORDER BY rowid DESC LIMIT 1
        """,
        (match_id,),
    ).fetchone()
    clock = con.execute(
        """
        SELECT c.id FROM clock_map c
        JOIN gameplay_source g ON g.id = c.gameplay_source_id
        WHERE g.match_id = ?
        ORDER BY c.rowid DESC LIMIT 1
        """,
        (match_id,),
    ).fetchone()
    duration = con.execute(
        "SELECT game_duration_ms FROM match WHERE match_id = ?", (match_id,)
    ).fetchone()
    con.close()
    source_id = None if source is None else str(source["id"])
    clock_id = None if clock is None else str(clock["id"])
    duration_ms = None if duration is None or duration[0] is None else int(duration[0])
    return source_id, clock_id, duration_ms


def _find_existing_capture(match_id: str, start_ms: int, end_ms: int) -> Path | None:
    settings = get_settings()
    root = settings.captures_dir / match_id
    if not root.is_dir():
        return None
    for folder in sorted(root.iterdir()):
        manifest_path = folder / "manifest.json"
        if not manifest_path.is_file():
            continue
        payload = json.loads(manifest_path.read_text(encoding="utf-8"))
        if str(payload.get("status")) != "complete":
            continue
        if capture_covers_window(
            capture_start_game_ms=int(payload["requested_start_game_ms"]),
            capture_end_game_ms=int(payload["requested_end_game_ms"]),
            window_start_game_ms=start_ms,
            window_end_game_ms=end_ms,
        ):
            return folder
    return None


def _gst_from_db(match_id: str, subject_pid: int) -> GameStateTimeline | None:
    con = sqlite3.connect(_db_path())
    con.row_factory = sqlite3.Row
    match_row = con.execute(
        "SELECT match_id, game_version, queue_id, game_duration_ms FROM match WHERE match_id = ?",
        (match_id,),
    ).fetchone()
    if match_row is None:
        con.close()
        return None
    parts = con.execute(
        """
        SELECT participant_id, champion_name, team_id, team_position
        FROM match_participation WHERE match_id = ?
        """,
        (match_id,),
    ).fetchall()
    kills = con.execute(
        """
        SELECT t_ms, killer_id, victim_id, payload
        FROM timeline_event WHERE match_id = ? AND type = 'CHAMPION_KILL'
        ORDER BY t_ms
        """,
        (match_id,),
    ).fetchall()
    con.close()
    participants: dict[int, ParticipantInfo] = {}
    for row in parts:
        pid = int(row["participant_id"])
        team_raw = row["team_id"]
        try:
            team = Team(int(team_raw))
        except (TypeError, ValueError):
            team = Team.RED if pid == subject_pid else Team.BLUE
        role_raw = str(row["team_position"] or "UNKNOWN").upper()
        try:
            role = Role(role_raw)
        except ValueError:
            role = Role.UNKNOWN
        participants[pid] = ParticipantInfo(
            participant_id=pid,
            champion=str(row["champion_name"] or "Unknown"),
            role=role,
            team=team,
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
    provenance = Provenance(producer="v3-research-db", producer_version=1)
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
                assists = loaded.get("assistingParticipantIds")
                if assists is not None:
                    payload["assistingParticipantIds"] = assists
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


def _resolve_rofl() -> Path | None:
    for key in (
        "RIFTLENS_V3_ROFL",
        "RIFTLENS_R6_ROFL",
        "RIFTLENS_REPLAY_ROFL",
        "RIFTLENS_R10_ROFL",
    ):
        raw = os.environ.get(key)
        if raw:
            path = Path(raw)
            return path if path.is_file() else None
    candidates = (
        Path.home() / "OneDrive" / "Documents" / "League of Legends" / "Replays",
        Path.home() / "Documents" / "League of Legends" / "Replays",
    )
    for folder in candidates:
        if not folder.is_dir():
            continue
        hits = sorted(folder.glob(f"*{MATCH.split('_', 1)[-1]}*.rofl"))
        if hits:
            return hits[0]
        named = folder / ROFL_BASENAME
        if named.is_file():
            return named
    return None


async def _capture(plan_source_id: str, plan: PlannedCapture) -> tuple[int, Path | None]:
    del plan_source_id
    rofl = _resolve_rofl()
    if rofl is None:
        print(f"FAIL: {ROFL_BASENAME} not found via env or Documents/Replays")
        return 2, None
    capability = probe_replay_api_capability()
    print(
        "REPLAY_API",
        capability.reachable,
        capability.replay_playback_present,
        None if capability.error is None else capability.error.code.value,
    )
    if not capability.reachable or not capability.replay_playback_present:
        print(
            "FAIL: Replay API is not reachable. Open NA1-5614479225.rofl in the "
            "League game client first, then re-run with RIFTLENS_V3_T4=1. "
            "Do not let RiftLens re-launch the .rofl (that can kill the session)."
        )
        return 4, None
    settings = get_settings()
    engine = init_database(settings)
    factory = make_session_factory(engine)
    # Attach only: never shell-open / direct-exe while a manual replay is running.
    # Shell-open previously terminated the user's League of Legends.exe session.
    transport = default_api_transport()

    def _attach_supervisor() -> ReplayProcessSupervisor:
        return ReplayProcessSupervisor(
            transport=transport,
            live_probe=transport,
            strategies=(UserAssistedStrategy(),),
            startup_timeout_s=60.0,
            allow_user_assisted=True,
        )

    host = create_replay_host(transport=transport, supervisor_factory=_attach_supervisor)
    gameplay_repo = SqlGameplayRepository(factory)
    capture_repo = SqlCaptureRepository(factory)
    captures = CaptureService(
        host=host,
        captures=capture_repo,
        gameplay=gameplay_repo,
        captures_dir=settings.captures_dir,
        budget=settings.capture_budget,
    )
    service = GameplaySourceService(
        host=host,
        gameplay=gameplay_repo,
        matches=SqlMatchRepository(factory),
        captures=captures,
    )
    now = int(time.time() * 1000)
    imported = await service.import_rofl(str(rofl), now_ms=now, match_id=MATCH)
    print("IMPORT", imported.ok, imported.source_id, imported.error)
    if not imported.ok or imported.source_id is None:
        engine.dispose()
        return 3, None
    source_id = imported.source_id
    print("ATTACHING SESSION (user-assisted; no re-launch)...")
    session = await service.open_linked_source(source_id)
    print("SESSION", session.phase, session.error)
    if not session.is_active:
        engine.dispose()
        return 4, None
    req = capture_request_for_window(plan, source_id=source_id)
    started = await service.request_capture(req, now_ms=int(time.time() * 1000))
    print("CAPTURE_START", started.capture_id, started.status, started.error)
    if started.capture_id is None:
        if started.error is not None:
            print("TYPED_FAILURE", typed_from_replay_error(started.error))
        await service.close_session(source_id, now_ms=int(time.time() * 1000))
        engine.dispose()
        return 5, None
    result = await captures.await_result(started.capture_id, timeout_s=900.0)
    print("CAPTURE_DONE", result.status, result.ok, result.error)
    await service.close_session(source_id, now_ms=int(time.time() * 1000))
    engine.dispose()
    if not result.ok or result.status is not CaptureStatus.COMPLETE:
        if result.error is not None:
            print("TYPED_FAILURE", typed_from_replay_error(result.error))
        return 6, None
    capture_dir = settings.captures_dir / MATCH / started.capture_id
    return 0, capture_dir


def main() -> int:
    parser = argparse.ArgumentParser(description="V.3 Vladimir finding-window capture")
    parser.add_argument("--fps", type=float, default=DEFAULT_V2_SAMPLE_FPS)
    parser.add_argument("--json-out", type=Path, default=None)
    parser.add_argument("--analyze-only", action="store_true")
    args = parser.parse_args()
    subject_pid = _resolve_subject_pid(MATCH, SUBJECT_CHAMPION)
    findings = _load_findings(MATCH, subject_pid)
    finding = _select_v3_finding(findings)
    source_id, clock_id, duration_ms = _latest_source_and_clock(MATCH)
    plan = capture_window_for_finding(
        finding,
        pad_before_ms=PAD_BEFORE_MS,
        pad_after_ms=PAD_AFTER_MS,
        match_duration_ms=duration_ms,
        source_id=source_id,
        clock_map_id=clock_id,
    )
    stamp = f"{finding.t_ms // 60000}:{(finding.t_ms // 1000) % 60:02d}"
    print("MATCH", MATCH, "SUBJECT", SUBJECT_CHAMPION, "pid", subject_pid)
    print("FINDING", finding.finding_id, finding.rule_id, finding.t_ms, stamp, finding.title)
    print("WINDOW", plan.start_game_ms, plan.end_game_ms, "duration", plan.duration_ms)
    print("SOURCE", plan.source_id, "CLOCK", plan.clock_map_id, "REVIEW", plan.review_id)
    enabled = os.environ.get("RIFTLENS_V3_T4") == "1"
    existing = _find_existing_capture(MATCH, plan.start_game_ms, plan.end_game_ms)
    capture_dir: Path | None = existing
    if existing is not None:
        print("EXISTING_CAPTURE", existing)
    elif args.analyze_only or not enabled:
        outcome = refuse_automatic_capture(plan)
        print("NO_CAPTURE", outcome.code, outcome.message)
        if not args.analyze_only:
            try:
                require_explicit_capture(False, plan)
            except Exception as exc:
                print("TYPED", type(exc).__name__, exc)
            return 0
    else:
        code, capture_dir = asyncio.run(_capture(source_id or "", plan))
        if code != 0 or capture_dir is None:
            return code
    if capture_dir is None:
        return 0
    gst = _gst_from_db(MATCH, subject_pid)
    result = analyze_capture_dir_v2(
        capture_dir,
        fps=args.fps,
        gst=gst,
        subject_pid=subject_pid,
        subject_champion=SUBJECT_CHAMPION,
        capture_review_pid=subject_pid,
    )
    print(format_v1_timeline(result), end="")
    claim = StructuredClaim(
        rule_id=finding.rule_id,
        t_ms=finding.t_ms,
        summary=finding.title or "Died in the enemy half with no recent ward",
    )
    diagnostic = classify_v1_against_claim(result, claim)
    print("DIAGNOSTIC", diagnostic.value)
    print(
        "PERF",
        json.dumps(
            {
                "fps": result.sample_fps,
                "decoded": result.timing.decoded_frames,
                "analyzed": result.timing.analyzed_frames,
                "extract_ms": round(result.timing.extract_ms, 1),
                "detect_ms": round(result.timing.detect_ms, 1),
                "track_ms": round(result.timing.track_ms, 1),
                "align_ms": round(result.timing.align_ms, 1),
                "total_ms": round(result.timing.total_ms, 1),
                "metrics": None if result.metrics is None else result.metrics.to_dict(),
                "raw_bar_detections": result.raw_bar_detections,
                "confirmed_detections": result.confirmed_detections,
                "correlation": result.correlation.status.value,
                "correlation_confidence": result.correlation.confidence,
            }
        ),
    )
    if args.json_out is not None:
        args.json_out.write_text(json.dumps(result.to_dict(), indent=2) + "\n", encoding="utf-8")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
