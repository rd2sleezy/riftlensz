from __future__ import annotations

from riftlens.analysis.features.gold import unspent_gold
from riftlens.domain.enums import FactKind, Role, Team
from tests.helpers.gst import bundled_patch, fact, load_gst, make_gst, make_participant


def test_unspent_gold_exact_at_frame() -> None:
    patch = bundled_patch()
    gst = make_gst(
        [
            fact(0, FactKind.GOLD, 1, {"currentGold": 500, "totalGold": 500, "goldPerSecond": 0}),
            fact(
                60_000,
                FactKind.GOLD,
                1,
                {"currentGold": 120, "totalGold": 620, "goldPerSecond": 20},
            ),
            fact(0, FactKind.CS, 1, {"minionsKilled": 0, "jungleMinionsKilled": 0}),
            fact(60_000, FactKind.CS, 1, {"minionsKilled": 0, "jungleMinionsKilled": 0}),
        ]
    )
    estimate = unspent_gold(gst, 1, 60_000, patch)
    assert estimate.value == 120
    assert estimate.confidence == 1.0
    assert estimate.lo == 120
    assert estimate.hi == 120


def test_unspent_gold_applies_purchase_between_frames() -> None:
    patch = bundled_patch()
    gst = make_gst(
        [
            fact(0, FactKind.GOLD, 1, {"currentGold": 500, "totalGold": 500, "goldPerSecond": 0}),
            fact(
                60_000,
                FactKind.GOLD,
                1,
                {"currentGold": 150, "totalGold": 500, "goldPerSecond": 0},
            ),
            fact(0, FactKind.CS, 1, {"minionsKilled": 0, "jungleMinionsKilled": 0}),
            fact(60_000, FactKind.CS, 1, {"minionsKilled": 0, "jungleMinionsKilled": 0}),
            fact(10_000, FactKind.ITEM_PURCHASED, 1, {"itemId": 1036}),
        ]
    )
    before = unspent_gold(gst, 1, 5_000, patch)
    after = unspent_gold(gst, 1, 15_000, patch)
    assert after.value < before.value


def test_unspent_gold_within_200_of_frame_current_all_fixtures() -> None:
    """Calibration: at every GOLD frame boundary, estimate matches currentGold ±200.

    Frame times short-circuit to the GST GOLD fact, so error is 0. This locks the
    contract that analysis never drifts off timeline currentGold at sample times.
    """
    patch = bundled_patch()
    for name in ("NA1_fixture_a", "NA1_fixture_b", "NA1_fixture_c"):
        gst = load_gst(name)
        for pid in gst.participants:
            for gold_fact in gst.facts(kind=FactKind.GOLD):
                if gold_fact.subject.id != pid:
                    continue
                true = int(gold_fact.payload["currentGold"])
                estimate = unspent_gold(gst, pid, gold_fact.t_ms, patch)
                assert abs(estimate.value - true) <= 200, (
                    f"{name} pid={pid} t={gold_fact.t_ms} est={estimate.value} true={true}"
                )


def test_unspent_gold_missing_data_is_low_confidence() -> None:
    patch = bundled_patch()
    gst = make_gst(
        [],
        participants={1: make_participant(1, team=Team.BLUE, role=Role.TOP)},
    )
    estimate = unspent_gold(gst, 1, 30_000, patch)
    assert estimate.confidence < 0.5
