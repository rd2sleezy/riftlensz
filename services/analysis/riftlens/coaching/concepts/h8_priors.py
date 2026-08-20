"""H.8 causal-graph priors for C.3 hypothesis strengthening.

H.8 production clustering is unchanged. C.3 may consult the authored graph as
prior art only. Graph edges never alone yield CausalStatus.SUPPORTED.
"""

from __future__ import annotations

from functools import lru_cache

from riftlens.coaching.data import CausalGraph, load_causal_graph


@lru_cache(maxsize=1)
def h8_causal_graph() -> CausalGraph:
    """Load the H.8 causal graph once (read-only prior art)."""
    return load_causal_graph()


def h8_edge_pair(upstream_taxonomy: str, downstream_taxonomy: str) -> bool:
    """Return True if H.8 authors upstream as a cause of downstream symptom."""
    graph = h8_causal_graph()
    for cause in graph.causes_for(downstream_taxonomy):
        if cause.concept_id == upstream_taxonomy:
            return True
    return False


def h8_related_rule_ids(downstream_taxonomy: str) -> frozenset[str]:
    """Rule ids mentioned in related_rule_near params for a symptom concept."""
    found: set[str] = set()
    for cause in h8_causal_graph().causes_for(downstream_taxonomy):
        if cause.test != "coaching.causal.related_rule_near":
            continue
        raw = cause.params.get("rule_ids", [])
        if isinstance(raw, list):
            found.update(str(item) for item in raw)
    return frozenset(found)
