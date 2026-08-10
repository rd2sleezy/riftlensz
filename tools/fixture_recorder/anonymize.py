from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
from typing import Any

_SALT = "riftlens-fixture-v1"


def scramble(value: str, *, kind: str) -> str:
    """Return a deterministic stand-in for a PII string. Assumes value is non-empty."""
    digest = hashlib.sha256(f"{_SALT}:{kind}:{value}".encode()).hexdigest()
    if kind == "puuid":
        return f"anon_{digest[:70]}"
    if kind == "name":
        return f"Player{digest[:8]}"
    if kind == "tag":
        return digest[:4].upper()
    if kind == "match":
        return f"NA1_fixture_{digest[:6]}"
    if kind == "id":
        return digest[:16]
    return digest[:12]


def anonymize_obj(node: Any) -> Any:
    """Walk JSON and scramble identity fields. Assumes Riot match/timeline documents."""
    if isinstance(node, list):
        if node and all(isinstance(item, str) and len(item) > 20 for item in node):
            return [scramble(item, kind="puuid") for item in node]
        return [anonymize_obj(item) for item in node]
    if isinstance(node, dict):
        out: dict[str, Any] = {}
        for key, value in node.items():
            if key == "puuid" and isinstance(value, str):
                out[key] = scramble(value, kind="puuid")
            elif key == "riotIdGameName" and isinstance(value, str) and value or key == "summonerName" and isinstance(value, str) and value:
                out[key] = scramble(value, kind="name")
            elif key == "riotIdTagline" and isinstance(value, str) and value:
                out[key] = scramble(value, kind="tag")
            elif key in {"summonerId", "accountId"} and isinstance(value, str) and value:
                out[key] = scramble(value, kind="id")
            elif key == "matchId" and isinstance(value, str) and value:
                out[key] = value if value.startswith("NA1_fixture_") else scramble(value, kind="match")
            else:
                out[key] = anonymize_obj(value)
        return out
    return node


def anonymize_file(path: Path, *, match_id: str | None = None) -> dict[str, Any]:
    """Load, anonymize, optionally force matchId, and rewrite path. Assumes UTF-8 JSON."""
    payload = json.loads(path.read_text(encoding="utf-8"))
    cleaned = anonymize_obj(payload)
    if match_id and isinstance(cleaned, dict):
        metadata = cleaned.get("metadata")
        if isinstance(metadata, dict):
            metadata["matchId"] = match_id
        info = cleaned.get("info")
        if isinstance(info, dict) and "gameName" in info:
            info["gameName"] = f"teambuilder-match-{match_id}"
    path.write_text(json.dumps(cleaned, indent=2) + "\n", encoding="utf-8")
    return cleaned if isinstance(cleaned, dict) else {}


def main() -> None:
    parser = argparse.ArgumentParser(description="Anonymize Riot match/timeline JSON fixtures.")
    parser.add_argument("paths", nargs="+", type=Path)
    parser.add_argument("--match-id", default=None)
    args = parser.parse_args()
    for path in args.paths:
        anonymize_file(path, match_id=args.match_id)


if __name__ == "__main__":
    main()
