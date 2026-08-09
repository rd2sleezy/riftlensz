from __future__ import annotations

import json
from collections.abc import Iterable, Mapping
from pathlib import Path
from typing import Any, cast

import yaml
from sqlalchemy.orm import Session, sessionmaker

from riftlens.adapters.db.models import ConceptRow, RuleDefinitionRow

_RESOURCES = Path(__file__).resolve().parents[2] / "resources"
_TAXONOMY_PATH = _RESOURCES / "taxonomy" / "taxonomy.yaml"
_RULES_ROOT = _RESOURCES / "rules"


def dumps_json(value: object) -> str:
    """Return compact deterministic JSON. Assumes ``value`` is JSON-serializable."""
    return json.dumps(value, separators=(",", ":"), sort_keys=True, ensure_ascii=False)


class TaxonomyLoader:
    def __init__(
        self,
        session_factory: sessionmaker[Session],
        yaml_path: Path | None = None,
    ) -> None:
        self._factory = session_factory
        self._path = yaml_path or _TAXONOMY_PATH

    def load(self) -> int:
        """Upsert taxonomy YAML into ``concept``. Returns the number of rows written.

        Assumes each concept ``id`` is unique and ``parent_id`` values resolve in-file.
        """
        payload = _load_yaml(self._path)
        concepts = payload.get("concepts")
        if not isinstance(concepts, list):
            raise ValueError(f"{self._path} must contain a top-level 'concepts' list")
        ordered = _order_concepts(cast(list[Mapping[str, Any]], concepts))
        session = self._factory()
        try:
            for item in ordered:
                session.merge(_concept_row(item))
            session.commit()
        except Exception:
            session.rollback()
            raise
        finally:
            session.close()
        return len(ordered)


class RuleDefinitionLoader:
    def __init__(
        self,
        session_factory: sessionmaker[Session],
        rules_root: Path | None = None,
    ) -> None:
        self._factory = session_factory
        self._root = rules_root or _RULES_ROOT

    def load(self) -> int:
        """Upsert rule YAML files into ``rule_definition``. Returns rows written.

        Assumes each file has ``id`` + ``version`` and a ``concept_id`` already loaded.
        """
        paths = sorted(self._root.rglob("*.yaml")) + sorted(self._root.rglob("*.yml"))
        definitions = [_rule_row(_load_yaml(path), path) for path in paths]
        session = self._factory()
        try:
            for row in definitions:
                session.merge(row)
            session.commit()
        except Exception:
            session.rollback()
            raise
        finally:
            session.close()
        return len(definitions)


def _load_yaml(path: Path) -> dict[str, Any]:
    if not path.is_file():
        raise FileNotFoundError(f"reference YAML not found: {path}")
    loaded = yaml.safe_load(path.read_text(encoding="utf-8"))
    if not isinstance(loaded, dict):
        raise ValueError(f"{path} must be a YAML mapping")
    return cast(dict[str, Any], loaded)


def _order_concepts(concepts: Iterable[Mapping[str, Any]]) -> list[Mapping[str, Any]]:
    remaining = [dict(item) for item in concepts]
    ordered: list[Mapping[str, Any]] = []
    loaded: set[str] = set()
    while remaining:
        ready = [
            item
            for item in remaining
            if not item.get("parent_id") or str(item["parent_id"]) in loaded
        ]
        if not ready:
            ids = [str(item.get("id")) for item in remaining]
            raise ValueError(f"concept parent cycle or missing parent among {ids}")
        for item in ready:
            concept_id = str(item["id"])
            ordered.append(item)
            loaded.add(concept_id)
        remaining = [item for item in remaining if str(item["id"]) not in loaded]
    return ordered


def _concept_row(item: Mapping[str, Any]) -> ConceptRow:
    concept_id = str(item["id"])
    parent = item.get("parent_id")
    return ConceptRow(
        id=concept_id,
        parent_id=None if parent in (None, "") else str(parent),
        domain=str(item["domain"]),
        label=str(item["label"]),
        description=None if item.get("description") is None else str(item["description"]),
        data_tier=str(item["data_tier"]),
        teachability=float(item["teachability"]),
        roles=dumps_json(item["roles"]),
        phases=dumps_json(item["phases"]),
    )


def _rule_row(payload: Mapping[str, Any], path: Path) -> RuleDefinitionRow:
    try:
        rule_id = str(payload["id"])
        version = int(payload["version"])
        concept_id = str(payload["concept_id"])
    except KeyError as exc:
        raise ValueError(f"{path} is missing required rule field {exc}") from exc
    patch_range = payload.get("patch_range")
    return RuleDefinitionRow(
        id=rule_id,
        version=version,
        name=str(payload["name"]),
        concept_id=concept_id,
        category=str(payload["category"]),
        severity_base=str(payload["severity_base"]),
        data_tier=str(payload["data_tier"]),
        patch_range=None if patch_range in (None, "") else str(patch_range),
        definition_json=dumps_json(dict(payload)),
    )
