"""Research-only: run V.2 vs V.4 on the real Vladimir V.3 capture. Not production."""

from __future__ import annotations

import json
import sqlite3
import time
from pathlib import Path

from riftlens.config import Settings, default_captures_dir
from riftlens.domain.enums import DataTier, FactKind, Role, Source, Team
from riftlens.domain.fact import Fact, Provenance, SubjectRef
from riftlens.domain.timeline import GameStateTimeline, ParticipantInfo
from riftlens.visual.v2_analyze import analyze_capture_dir_v2
from riftlens.visual.v4_analyze import analyze_capture_dir_v4

MATCH = "NA1_5614479225"
PID = 6
CAPTURE_ID = "01KZT2ZK13TPZP72070CEC9DEF"


def _capture_dir() -> Path:
    root = default_captures_dir()
    path = root / MATCH / CAPTURE_ID
    if not path.is_dir():
        raise SystemExit(f"missing capture dir {path}")
    return path


def gst_from_db(match_id: str) -> GameStateTimeline:
    con = sqlite3.connect(Settings().db_path)
    con.row_factory = sqlite3.Row
    match_row = con.execute(
        "SELECT match_id, game_version, queue_id, game_duration_ms FROM match WHERE match_id = ?",
        (match_id,),
    ).fetchone()
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
    assert match_row is not None
    gst = GameStateTimeline(
        match_id=match_id,
        patch=str(match_row["game_version"] or "unknown"),
        queue_id=int(match_row["queue_id"] or 420),
        duration_ms=int(match_row["game_duration_ms"] or 0),
        participants=participants,
        available_data_tiers=frozenset({DataTier.RIOT_ONLY, DataTier.RIOT_DERIVED}),
    )
    provenance = Provenance(producer="v4-research-db", producer_version=1)
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


def main() -> None:
    gst = gst_from_db(MATCH)
    subject = gst.participants[PID]
    print("subject", subject.champion, "team", int(subject.team))
    cap = _capture_dir()

    print("=== V2 ===")
    t0 = time.perf_counter()
    v2 = analyze_capture_dir_v2(
        cap,
        subject_pid=PID,
        subject_champion="Vladimir",
        capture_review_pid=PID,
        gst=gst,
    )
    print(f"v2_sec={(time.perf_counter() - t0):.1f}")
    teams2: dict[str, int] = {}
    for tr in v2.tracks:
        teams2[tr.team_estimate.value] = teams2.get(tr.team_estimate.value, 0) + 1
    print("tracks", len(v2.tracks), "teams", teams2)
    print("corr", v2.correlation.status.value, v2.correlation.track_id, v2.correlation.confidence)

    print("=== V4 ===")
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
    teams4: dict[str, int] = {}
    for tr in v4.tracks:
        teams4[tr.team_estimate.value] = teams4.get(tr.team_estimate.value, 0) + 1
    print("tracks", len(v4.tracks), "teams", teams4)
    print("corr", v4.correlation.status.value, v4.correlation.track_id, v4.correlation.confidence)
    print("calib", None if v4.calibration is None else v4.calibration.to_dict())
    print(
        "timing",
        {
            "extract": round(v4.timing.extract_ms, 1),
            "detect": round(v4.timing.detect_ms, 1),
            "track": round(v4.timing.track_ms, 1),
            "color_sample": round(v4.color_sample_ms, 1),
            "calibrate": round(v4.calibrate_ms, 1),
            "align": round(v4.timing.align_ms, 1),
            "total": round(v4.timing.total_ms, 1),
            "frames": v4.timing.analyzed_frames,
        },
    )
    print("raw/confirmed", v4.raw_bar_detections, v4.confirmed_detections)
    print("inferred_types", sorted({f.observation_type for f in v4.inferred_frames}))
    if v4.sequence.frames:
        print("observed_source", v4.sequence.frames[0].source.value)
    for frame in v4.inferred_frames:
        if frame.observation_type == "track_team_label":
            print(
                " team_inf",
                frame.payload.get("track_id"),
                frame.payload.get("team_class"),
                frame.payload.get("color_class"),
                "src",
                frame.source.value,
            )
    print("--- tracks ---")
    for tr in v4.tracks:
        lab = (v4.track_labels or {}).get(tr.track_id, {})
        print(
            tr.track_id,
            tr.kind.value,
            tr.team_estimate.value,
            f"conf={tr.team_confidence}",
            f"obs={tr.observation_count}",
            f"{tr.first_seen_game_t_ms}-{tr.last_seen_game_t_ms}",
            lab,
        )
    out = Path("artifacts") / "v4_vladimir_result.json"
    out.parent.mkdir(exist_ok=True)
    out.write_text(json.dumps(v4.to_dict(), indent=2) + "\n", encoding="utf-8")
    print("wrote", out)


if __name__ == "__main__":
    main()
