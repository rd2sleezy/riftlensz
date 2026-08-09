from __future__ import annotations

import json
from collections.abc import Iterable, Mapping, Sequence
from importlib import import_module
from pathlib import Path
from pkgutil import walk_packages
from typing import Any, cast

import yaml
from pydantic import ValidationError

from riftlens.analysis.rules.models import RuleDefinition, RulePack, dump_rule_schema
from riftlens.analysis.rules.registry import (
    PredicateRegistry,
    global_predicates,
    segmenter_registered,
)

_RESOURCES = Path(__file__).resolve().parents[2] / "resources"
_TAXONOMY_PATH = _RESOURCES / "taxonomy" / "taxonomy.yaml"
_RULES_ROOT = _RESOURCES / "rules"
_SCHEMA_PATH = _RULES_ROOT / "_schema.json"


class RuleLoadError(ValueError):
    """Raised when a rule YAML or taxonomy file is malformed."""


def load_taxonomy(path: Path | None = None) -> list[dict[str, Any]]:
    """Return ordered concept dicts. Assumes every ``parent_id`` resolves in-file."""
    target = path or _TAXONOMY_PATH
    payload = _load_yaml(target)
    concepts = payload.get("concepts")
    if not isinstance(concepts, list):
        raise RuleLoadError(f"{target} must contain a top-level 'concepts' list")
    items = [dict(item) for item in cast(list[Mapping[str, Any]], concepts)]
    validate_taxonomy_parents(items, source=str(target))
    return _order_concepts(items)


def validate_taxonomy_parents(concepts: Sequence[Mapping[str, Any]], *, source: str) -> None:
    """Raise if any ``parent_id`` / ``parent`` does not resolve to another concept id."""
    ids = {str(item["id"]) for item in concepts}
    if len(ids) != len(concepts):
        raise RuleLoadError(f"{source}: duplicate concept id")
    for item in concepts:
        parent = item.get("parent_id", item.get("parent"))
        if parent in (None, ""):
            continue
        parent_id = str(parent)
        if parent_id not in ids:
            raise RuleLoadError(
                f"{source}: concept {item.get('id')!r} parent {parent_id!r} does not resolve"
            )


def load_rule_pack(
    rules_root: Path | None = None,
    taxonomy_path: Path | None = None,
    *,
    registry: PredicateRegistry | None = None,
) -> RulePack:
    """Load and validate every rule YAML. Malformed files are startup errors."""
    import_predicate_modules()
    concepts = load_taxonomy(taxonomy_path)
    concept_ids = {str(item["id"]) for item in concepts}
    root = rules_root or _RULES_ROOT
    paths = _rule_paths(root)
    resolved = registry or global_predicates()
    rules = [load_rule_file(path, concept_ids=concept_ids, registry=resolved) for path in paths]
    return RulePack(rules, sorted(concept_ids))


def load_rule_file(
    path: Path,
    *,
    concept_ids: set[str],
    registry: PredicateRegistry,
) -> RuleDefinition:
    """Validate one YAML rule. Assumes ``path`` is a mapping document."""
    payload = _load_yaml(path)
    try:
        rule = RuleDefinition.model_validate(payload)
    except ValidationError as exc:
        raise RuleLoadError(f"{path} is not a valid RuleDefinition:\n{exc}") from exc
    if rule.concept_id not in concept_ids:
        raise RuleLoadError(
            f"{path}: unknown concept_id {rule.concept_id!r} (not in taxonomy)"
        )
    if rule.trigger.predicate not in registry:
        raise RuleLoadError(
            f"{path}: trigger.predicate {rule.trigger.predicate!r} is not registered"
        )
    if rule.trigger.evaluate_on == "WINDOW":
        name = rule.trigger.segmenter or ""
        if not segmenter_registered(name):
            raise RuleLoadError(f"{path}: trigger.segmenter {name!r} is not registered")
    if rule.trigger.evaluate_on == "EVENT" and not rule.event_fact_kinds():
        raise RuleLoadError(f"{path}: EVENT trigger must declare fact kinds")
    return rule


def import_predicate_modules() -> None:
    """Import ``riftlens.analysis.rules.predicates`` so ``@register_rule`` runs."""
    import riftlens.analysis.rules.predicates as package

    prefix = package.__name__ + "."
    for module in walk_packages(package.__path__, prefix):
        import_module(module.name)


def write_rule_schema(path: Path | None = None) -> Path:
    """Write ``_schema.json`` from the pydantic model. Assumes the rules dir exists."""
    target = path or _SCHEMA_PATH
    target.write_text(
        json.dumps(dump_rule_schema(), indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    return target


def _rule_paths(root: Path) -> list[Path]:
    paths = sorted(root.rglob("*.yaml")) + sorted(root.rglob("*.yml"))
    return [path for path in paths if path.is_file() and path.name != "_schema.yaml"]


def _load_yaml(path: Path) -> dict[str, Any]:
    if not path.is_file():
        raise RuleLoadError(f"reference YAML not found: {path}")
    loaded = yaml.safe_load(path.read_text(encoding="utf-8"))
    if not isinstance(loaded, dict):
        raise RuleLoadError(f"{path} must be a YAML mapping")
    return cast(dict[str, Any], loaded)


def _order_concepts(concepts: Iterable[Mapping[str, Any]]) -> list[dict[str, Any]]:
    remaining = [dict(item) for item in concepts]
    ordered: list[dict[str, Any]] = []
    loaded: set[str] = set()
    while remaining:
        ready = [
            item
            for item in remaining
            if not _parent_of(item) or str(_parent_of(item)) in loaded
        ]
        if not ready:
            ids = [str(item.get("id")) for item in remaining]
            raise RuleLoadError(f"concept parent cycle or missing parent among {ids}")
        for item in ready:
            ordered.append(item)
            loaded.add(str(item["id"]))
        remaining = [item for item in remaining if str(item["id"]) not in loaded]
    return ordered


def _parent_of(item: Mapping[str, Any]) -> object:
    return item.get("parent_id", item.get("parent"))
