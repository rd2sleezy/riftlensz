from __future__ import annotations

from collections.abc import Callable, Sequence
from typing import TYPE_CHECKING

from riftlens.domain.finding import Finding
from riftlens.domain.timeline import GameStateTimeline

if TYPE_CHECKING:
    from riftlens.analysis.rules.context import RuleContext

RulePredicate = Callable[["RuleContext"], Finding | None]
Segmenter = Callable[[GameStateTimeline, int], Sequence[int]]

_PREDICATES: dict[str, RulePredicate] = {}
_SEGMENTERS: dict[str, Segmenter] = {}


def register_rule(name: str) -> Callable[[RulePredicate], RulePredicate]:
    """Register ``fn`` under ``name``. Assumes names are unique dotted paths."""

    def decorator(fn: RulePredicate) -> RulePredicate:
        if name in _PREDICATES and _PREDICATES[name] is not fn:
            raise ValueError(f"predicate already registered: {name}")
        _PREDICATES[name] = fn
        return fn

    return decorator


def register_segmenter(name: str) -> Callable[[Segmenter], Segmenter]:
    """Register a WINDOW segmenter. Assumes ``fn`` returns candidate t_ms values."""

    def decorator(fn: Segmenter) -> Segmenter:
        if name in _SEGMENTERS and _SEGMENTERS[name] is not fn:
            raise ValueError(f"segmenter already registered: {name}")
        _SEGMENTERS[name] = fn
        return fn

    return decorator


class PredicateRegistry:
    """Lookup table for YAML ``trigger.predicate`` names."""

    def __init__(self, mapping: dict[str, RulePredicate] | None = None) -> None:
        self._mapping = dict(mapping if mapping is not None else _PREDICATES)

    def __getitem__(self, name: str) -> RulePredicate:
        try:
            return self._mapping[name]
        except KeyError as exc:
            raise KeyError(f"unregistered rule predicate: {name}") from exc

    def __contains__(self, name: object) -> bool:
        return isinstance(name, str) and name in self._mapping

    def names(self) -> frozenset[str]:
        """Return registered predicate names."""
        return frozenset(self._mapping)


def get_segmenter(name: str) -> Segmenter:
    """Return a registered WINDOW segmenter. Assumes ``name`` is a YAML reference."""
    try:
        return _SEGMENTERS[name]
    except KeyError as exc:
        raise KeyError(f"unregistered segmenter: {name}") from exc


def segmenter_registered(name: str) -> bool:
    """Return True when ``name`` is a known WINDOW segmenter."""
    return name in _SEGMENTERS


def global_predicates() -> PredicateRegistry:
    """Return a registry snapshot of module-level ``@register_rule`` callables."""
    return PredicateRegistry(dict(_PREDICATES))
