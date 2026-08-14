"""Research-only: V.4 baseline + V.5 refine on Vladimir capture when present."""

from __future__ import annotations

import json
import sqlite3
import time
from pathlib import Path

from riftlens.config import Settings, default_captures_dir
from riftlens.domain.enums import DataTier, FactKind, Role, Source, Team
from riftlens.domain.fact import Fact, Provenance, SubjectRef
from riftlens.domain.timeline import GameStateTimeline, ParticipantInfo
from riftlens.visual.v4_analyze import analyze_capture_dir_v4
from riftlens.visual.v5_analyze import analyze_capture_dir_v5, refine_v4_result

MATCH = "NA1_5614479225"
PID = 6
CAPTURE_ID = "01KZT2ZK13TPZP72070CEC9DEF"
# Frozen from docs/architecture/v4-spectator-team-color-calibration-report.md
FROZEN_V4_BASELINE = {
    "subject_track_id": "trk_0003",
    "subject_status": "LIKELY",
    "confidence": 0.55,
    "death_t_ms": 903_411,
    "calibration": "WEAK",
    "note": "Published V.4 report numbers; live re-run requires local capture.",
}


def _capture_dir() -> Path | None:
    root = default_captures_dir()
    path = root / MATCH / CAPTURE_ID
    if path.is_dir():
        return path
    return None


def gst_from_db(match_id: str) -> GameStateTimeline:
    con = sqlite3.connect(Settings().db_path)
    con.row_factory = sqlite3.Row
    match_row = con.execute(
        "SELECT match_id, game_version, queue_id, game_duration_ms FROM match WHERE match_id = ?",
        (match_id,),
    ).fetchone()
    if match_row is None:
        raise SystemExit(f"match {match_id} not in local DB")
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
    provenance = Provenance(producer="v5-research-db", producer_version=1)
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
            if isinstance(loaded, dict) and loaded.get("assistingParticipantIds") is not None:
                payload["assistingParticipantIds"] = loaded["assistingParticipantIds"]
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


def _print_correlation(
    label: str, status: str, track_id: str | None, conf: float, method: str
) -> None:
    print(label, status, track_id, conf, method)


def main() -> None:
    print("=== Frozen V.4 baseline (report) ===")
    print(json.dumps(FROZEN_V4_BASELINE, indent=2))
    cap = _capture_dir()
    if cap is None:
        print(
            "CAPTURE_UNAVAILABLE: "
            f"{default_captures_dir() / MATCH / CAPTURE_ID} "
            "not present on this machine. Live V.4/V.5 pixel re-run skipped."
        )
        return
    try:
        gst = gst_from_db(MATCH)
    except SystemExit as exc:
        print(exc)
        print("DB missing match; cannot join GST for live re-run.")
        return
    subject = gst.participants[PID]
    print("subject", subject.champion, "team", int(subject.team), "capture", cap)

    print("=== V4 live baseline ===")
    t0 = time.perf_counter()
    v4 = analyze_capture_dir_v4(
        cap,
        subject_pid=PID,
        subject_champion="Vladimir",
        capture_review_pid=PID,
        gst=gst,
        subject_team=subject.team,
    )
    print(f"v4_sec={(time.perf_counter() - t0):.1f}")
    _print_correlation(
        "v4_corr",
        v4.correlation.status.value,
        v4.correlation.track_id,
        v4.correlation.confidence,
        v4.correlation.method,
    )
    if v4.correlation.track_id:
        tr = next(t for t in v4.tracks if t.track_id == v4.correlation.track_id)
        print(
            "v4_track",
            tr.track_id,
            f"obs={tr.observation_count}",
            f"{tr.first_seen_game_t_ms}-{tr.last_seen_game_t_ms}",
            f"dur_ms={tr.last_seen_game_t_ms - tr.first_seen_game_t_ms}",
            tr.team_estimate.value,
        )
    death = (
        None
        if v4.alignment.subject is None or not v4.alignment.subject.deaths
        else v4.alignment.subject.deaths[0]
    )
    print("death_t_ms", death)
    print("calib", None if v4.calibration is None else v4.calibration.to_dict())

    print("=== V5 refine ===")
    t0 = time.perf_counter()
    v5 = refine_v4_result(v4)
    print(f"v5_refine_sec={(time.perf_counter() - t0):.3f} continuity_ms={v5.continuity_ms:.2f}")
    assert v5.v5 is not None
    print("identity_change", v5.v5.identity_change)
    _print_correlation(
        "v5_base",
        v5.v5.base.status.value,
        v5.v5.base.track_id,
        v5.v5.base.confidence,
        v5.v5.base.method,
    )
    _print_correlation(
        "v5_refined",
        v5.correlation.status.value,
        v5.correlation.track_id,
        v5.correlation.confidence,
        v5.correlation.method,
    )
    if v5.v5.bundle is not None:
        print("continuity_duration_ms", v5.v5.bundle.continuity_duration_ms)
        motion = (
            None
            if v5.v5.bundle.trajectory is None
            else v5.v5.bundle.trajectory.motion_class.value
        )
        print("motion", motion)
        print("contributing", v5.v5.contributing_cues)
        print("rejected", v5.v5.rejected_cues)
    out = Path("artifacts") / "v5_vladimir_result.json"
    out.parent.mkdir(exist_ok=True)
    out.write_text(json.dumps(v5.to_dict(), indent=2) + "\n", encoding="utf-8")
    print("wrote", out)
    # Also exercise full analyze_capture_dir_v5 path once.
    _ = analyze_capture_dir_v5(
        cap,
        subject_pid=PID,
        subject_champion="Vladimir",
        capture_review_pid=PID,
        gst=gst,
        subject_team=subject.team,
    )


if __name__ == "__main__":
    main()
