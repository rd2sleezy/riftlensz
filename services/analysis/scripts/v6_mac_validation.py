"""Real Mac V.6 death-window candidate ranking validation.

Uses the corrected full path+GST capture for NA1_5620410094 / Vladimir pid 6.
Does not re-capture. Does not mutate GST. Research only.
"""

from __future__ import annotations

import json
import sqlite3
import time
from pathlib import Path
from typing import Any

from riftlens.config import Settings
from riftlens.domain.enums import DataTier, FactKind, Role, Source, Team
from riftlens.domain.fact import Fact, Provenance, SubjectRef
from riftlens.domain.timeline import GameStateTimeline, ParticipantInfo
from riftlens.visual.v6_analyze import analyze_capture_dir_v6

MATCH = "NA1_5620410094"
PID = 6
SUBJECT = "Vladimir"
DEATH_T_MS = 839_881
ALT_DEATH_T_MS = 1_062_798
PRIMARY_CAPTURE = Path.home() / ".riftlens" / "captures" / MATCH / "01M00NSCH421BEY2SP3PADQT8A"
OUT = Path(__file__).resolve().parents[1] / "artifacts" / "v6_mac_5620410094_validation.json"


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
    provenance = Provenance(producer="v6-mac-validation", producer_version=1)
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


def _candidate_rows(result: Any) -> list[dict[str, Any]]:
    ranking = None if result.v6 is None else result.v6.ranking
    if ranking is None:
        return []
    return [item.to_dict() for item in ranking.candidates]


def run_window(capture_dir: Path, *, death_t_ms: int, gst: GameStateTimeline) -> dict[str, Any]:
    started = time.perf_counter()
    result = analyze_capture_dir_v6(
        capture_dir,
        gst=gst,
        subject_pid=PID,
        subject_champion=SUBJECT,
        capture_review_pid=PID,
    )
    wall_ms = (time.perf_counter() - started) * 1000.0
    v5 = result.v5
    v6 = result.v6
    return {
        "capture_dir": str(capture_dir),
        "death_t_ms": death_t_ms,
        "wall_ms": round(wall_ms, 1),
        "ranking_ms": round(result.ranking_ms, 3),
        "continuity_ms": round(result.continuity_ms, 3),
        "timing": {
            "total_ms": result.timing.total_ms,
            "detect_ms": result.timing.detect_ms,
            "track_ms": result.timing.track_ms,
            "frames": result.timing.analyzed_frames,
        },
        "v4": {
            "status": None if v5 is None else v5.base.status.value,
            "track_id": None if v5 is None else v5.base.track_id,
            "confidence": None if v5 is None else v5.base.confidence,
            "method": None if v5 is None else v5.base.method,
        },
        "v5": {
            "status": None if v5 is None else v5.refined.status.value,
            "track_id": None if v5 is None else v5.refined.track_id,
            "confidence": None if v5 is None else v5.refined.confidence,
            "identity_change": None if v5 is None else v5.identity_change,
        },
        "v6": {
            "status": result.correlation.status.value,
            "track_id": result.correlation.track_id,
            "confidence": result.correlation.confidence,
            "method": result.correlation.method,
            "identity_change": None if v6 is None else v6.identity_change,
            "winner_margin": None if v6 is None else v6.winner_margin,
            "reasons": list(result.correlation.reasons),
            "conflicts": list(result.correlation.conflicts),
            "reject_reason": None if v6 is None or v6.ranking is None else v6.ranking.reject_reason,
        },
        "candidates": _candidate_rows(result),
        "alignment_mutated_gst": result.alignment.mutated_gst,
        "track_count": len(result.tracks),
        "confirmed_detections": result.confirmed_detections,
    }


def main() -> None:
    if not PRIMARY_CAPTURE.is_dir():
        raise SystemExit(f"missing primary capture {PRIMARY_CAPTURE}")
    gst = gst_from_db(MATCH)
    primary = run_window(PRIMARY_CAPTURE, death_t_ms=DEATH_T_MS, gst=gst)
    alt: dict[str, Any] = {
        "death_t_ms": ALT_DEATH_T_MS,
        "note": (
            "Secondary window not re-captured for this spike; prior V.5 alt "
            "clip had no stable champion-like tracks. Primary clip covers "
            "829881–846881 only."
        ),
        "skipped": True,
    }
    payload = {
        "match_id": MATCH,
        "subject_pid": PID,
        "subject_champion": SUBJECT,
        "primary": primary,
        "secondary": alt,
        "death_align_ms_unchanged": 2000,
        "verdict_hint": primary["v6"]["status"],
    }
    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(payload["primary"]["v6"], indent=2))
    print(f"candidates={len(payload['primary']['candidates'])}")
    print(f"ranking_ms={payload['primary']['ranking_ms']}")
    print(f"wrote {OUT}")


if __name__ == "__main__":
    main()
