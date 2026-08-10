from __future__ import annotations

from riftlens.analysis.features.health import hp_fraction
from riftlens.domain.enums import FactKind
from tests.helpers.gst import bundled_patch, fact, load_gst, make_gst


def test_hp_fraction_exact_at_fixture_frame_times() -> None:
    patch = bundled_patch()
    for name in ("NA1_fixture_a", "NA1_fixture_b", "NA1_fixture_c"):
        gst = load_gst(name)
        for pid in gst.participants:
            for health in gst.facts(kind=FactKind.HEALTH):
                if health.subject.id != pid:
                    continue
                hp = float(health.payload["health"])
                maximum = float(health.payload["healthMax"])
                expected = 0.0 if maximum <= 0 else hp / maximum
                estimate = hp_fraction(gst, pid, health.t_ms, patch)
                assert estimate.confidence == 1.0
                assert estimate.value == expected
                assert estimate.lo == expected
                assert estimate.hi == expected


def test_hp_fraction_midpoint_has_generous_interval() -> None:
    patch = bundled_patch()
    gst = make_gst(
        [
            fact(
                0,
                FactKind.HEALTH,
                1,
                {"health": 1000, "healthMax": 1000, "healthRegen": 20},
            ),
            fact(
                60_000,
                FactKind.HEALTH,
                1,
                {"health": 400, "healthMax": 1000, "healthRegen": 20},
            ),
            fact(0, FactKind.DAMAGE_ACCUM, 1, {"totalDamageTaken": 0}),
            fact(60_000, FactKind.DAMAGE_ACCUM, 1, {"totalDamageTaken": 600}),
            fact(0, FactKind.POSITION, 1, {"x": 7500, "y": 7500}),
            fact(60_000, FactKind.POSITION, 1, {"x": 8200, "y": 8200}),
        ]
    )
    estimate = hp_fraction(gst, 1, 30_000, patch)
    assert estimate.lo is not None and estimate.hi is not None
    assert estimate.lo < estimate.value < estimate.hi
    assert estimate.hi - estimate.lo >= 0.2
    assert estimate.confidence < 1.0
