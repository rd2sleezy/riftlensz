"""Offline acceptance for match-aware .rofl association (credential boundary).

Proves identity resolution and mismatch rejection without Riot network.
Full ingest → review → Mac seek requires RIFTLENS_RIOT_API_KEY or desktop API-key sign-in.
"""

from __future__ import annotations

import asyncio
import json
import time
from pathlib import Path

from riftlens.adapters.db.engine import init_database, make_session_factory
from riftlens.adapters.db.repositories import SqlGameplayRepository, SqlMatchRepository
from riftlens.config import Settings, get_settings
from riftlens.domain.ports import MatchRecord
from riftlens.domain.replay_errors import ReplayError, ReplayErrorCode
from riftlens.gameplay.service import GameplaySourceService
from riftlens.pipeline.assemble.real_match import ensure_match_ingested
from riftlens.replay_host.factory import create_replay_host
from riftlens.rofl.identity import identify_rofl

ROFL = Path("/Users/rylanddunn/Documents/League of Legends/Replays/NA1-5620410094.rofl")
OUT = Path(__file__).resolve().parent / "match_association_acceptance.json"
REAL_MATCH = "NA1_5620410094"
FIXTURES = ("NA1_fixture_a", "NA1_fixture_b", "NA1_fixture_c")


async def _seed(repo: SqlMatchRepository, match_id: str) -> None:
    await repo.upsert_match(
        MatchRecord(
            match_id=match_id,
            platform="na1",
            region="americas",
            queue_id=420,
            map_id=11,
            game_version="16.9.1.123",
            patch="16.9",
            game_creation=1,
            game_start=1,
            game_duration_ms=1_800_000,
            game_end_ts=1_800_001,
            winning_team=100,
            raw_match_blob=None,
            raw_timeline_blob=None,
            ingested_at=2,
        )
    )


async def main() -> None:
    report: dict[str, object] = {
        "rofl": str(ROFL),
        "started_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
    }
    if not ROFL.is_file():
        report["ok"] = False
        report["error"] = "ROFL_MISSING"
        OUT.write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
        raise SystemExit(1)

    identified = identify_rofl(str(ROFL))
    report["identity"] = {
        "platform_id": identified.identity.platform_id if identified.identity else None,
        "game_id": identified.identity.game_id if identified.identity else None,
        "match_id_hint": identified.identity.match_id_hint if identified.identity else None,
        "error": None if identified.error is None else identified.error.code.value,
    }
    assert identified.identity is not None
    assert identified.identity.match_id_hint == REAL_MATCH

    data_dir = Path.home() / ".riftlens-match-assoc-acceptance"
    settings = Settings(data_dir=data_dir)
    engine = init_database(settings)
    try:
        factory = make_session_factory(engine)
        matches = SqlMatchRepository(factory)
        gameplay = SqlGameplayRepository(factory)
        for fixture_id in FIXTURES:
            await _seed(matches, fixture_id)
        await _seed(matches, REAL_MATCH)
        service = GameplaySourceService(
            host=create_replay_host(),
            gameplay=gameplay,
            matches=matches,
        )
        mismatch_results = []
        for fixture_id in FIXTURES:
            outcome = await service.import_rofl(
                str(ROFL), now_ms=int(time.time() * 1000), match_id=fixture_id
            )
            mismatch_results.append(
                {
                    "open_match_id": fixture_id,
                    "ok": outcome.ok,
                    "code": None if outcome.error is None else outcome.error.code.value,
                    "replay_match_id": outcome.match_id,
                    "sources_on_fixture": len(await gameplay.list_sources_for_match(fixture_id)),
                }
            )
        report["fixture_mismatch"] = mismatch_results
        assert all(item["ok"] is False for item in mismatch_results)
        assert all(item["code"] == "MATCH_IDENTITY_MISMATCH" for item in mismatch_results)
        assert all(item["sources_on_fixture"] == 0 for item in mismatch_results)

        match_ok = await service.import_rofl(
            str(ROFL), now_ms=int(time.time() * 1000), match_id=REAL_MATCH
        )
        report["matching_bind"] = {
            "ok": match_ok.ok,
            "match_id": match_ok.match_id,
            "source_id": match_ok.source_id,
        }
        assert match_ok.ok is True
        assert match_ok.match_id == REAL_MATCH

        bare = Settings(data_dir=data_dir / "bare-ingest", riot_api_key="")
        credential_error = None
        try:
            await ensure_match_ingested(REAL_MATCH, api_key=None, settings=bare)
        except ReplayError as exc:
            credential_error = {
                "code": exc.code.value,
                "message": str(exc),
            }
            assert exc.code is ReplayErrorCode.RIOT_CREDENTIAL_MISSING
        report["credential_boundary"] = credential_error
        report["env_key_present"] = bool((get_settings().riot_api_key or "").strip())
        report["ok"] = True
        report["real_match_coaching_seeks"] = {
            "completed": False,
            "blocked_by": "RIOT_CREDENTIAL_MISSING",
            "note": (
                "Sign in with a Riot developer API key in the desktop app, then re-run "
                "the real-match ingest → participant → review → MacReplayHost seek flow."
            ),
        }
    finally:
        engine.dispose()

    OUT.write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(report, indent=2))


if __name__ == "__main__":
    asyncio.run(main())
