from __future__ import annotations

from riftlens.adapters.ddragon.patch_data import PatchDataProvider
from tests.helpers.gst import bundled_patch


def test_gold_per_second_unit_is_quarantined() -> None:
    """Timeline goldPerSecond has no documented unit — do not convert it."""
    patch = bundled_patch()
    assert patch.gold_per_second_rate(0) is None
    assert patch.gold_per_second_rate(20) is None
    assert patch.gold_per_second_rate(30) is None
    assert patch._constants.get("gold_per_second_unit") is None  # noqa: SLF001


def test_health_regen_unit_is_quarantined() -> None:
    """Timeline healthRegen has no documented unit — do not convert it."""
    patch = bundled_patch()
    assert patch.health_regen_per_ms(0.0) == 0.0
    assert patch.health_regen_per_ms(17.0) == 0.0
    assert patch._constants.get("health_regen_period_ms") is None  # noqa: SLF001


def test_fresh_provider_same_quarantine() -> None:
    provider = PatchDataProvider()
    provider.load_bundled("12.4.423.2790")
    assert provider.gold_per_second_rate(20) is None
    assert provider.health_regen_per_ms(17.0) == 0.0
