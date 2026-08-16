from __future__ import annotations

import pytest
from riftlens.coaching.bundler import bundle_item
from riftlens.coaching.composer import PROMPT_VERSION, load_prompt, narrate_item
from riftlens.coaching.providers.null import NullProvider
from riftlens.coaching.validator import validate_bundle_text
from riftlens.domain.enums import IssueType, Role
from riftlens.domain.review import CoachingItem, Review
from tests.helpers.h8_findings import finding


class FakeProvider:
    name = "fake"
    model = "fake-v1"

    def __init__(self, text: str = "You lost 9,999 gold to Yasuo at 47:12") -> None:
        self.text = text
        self.calls = 0
        self.prompts: list[str] = []

    async def complete(
        self,
        prompt: str,
        *,
        schema: object = None,
        max_tokens: int = 800,
        fallback_text: str = "",
    ) -> str:
        del schema, max_tokens, fallback_text
        self.calls += 1
        self.prompts.append(prompt)
        return self.text


def _bundle():
    originals = [
        finding(
            rule_id="R-001",
            concept_id="RISK.DEATH_CAUSE.UNSEEN_JUNGLER",
            t_ms=480_000,
            info_age_ms=70_000,
        )
    ]
    item = CoachingItem(
        id="01H11ITEM00000000000000001",
        root_concept_id="RISK.DEATH_CAUSE.UNSEEN_JUNGLER",
        rank=1,
        is_focus=True,
        is_strength=False,
        issue_type=IssueType.TACTICAL,
        impact_score=12.0,
        gold_equivalent=900.0,
        occurrences=2,
        confidence=0.8,
        title="Know the jungler",
        body="Likely: you died on a pushed wave at 8:00.",
        the_fix="Ward before pushing.",
        next_game_check="Die less on a crash.",
        exemplar_finding_id=originals[0].id,
        finding_ids=(originals[0].id,),
        evidence_timestamps_ms=(480_000,),
        grouping_reason="same concept",
        certainty="likely",
        cluster_id="c1",
        cost_summary="~900g",
    )
    review = Review(
        id="01H11REVIEW000000000000001",
        player_id="p1",
        match_id="SYNTH",
        participant_id=1,
        champion="Ahri",
        role=Role.MIDDLE,
        rank="SILVER",
        patch="15.16",
        duration_ms=1_800_000,
        result="LOSS",
        rule_pack_version="1",
        engine_version="0.1.0",
        llm_provider="null",
        status="COMPLETE",
        summary_text="Focus: Know the jungler.",
        findings=tuple(originals),
        clusters=(),
        grouping_log=(),
        focus_items=(item,),
        secondary_items=(),
        strengths=(),
        metrics=(),
        created_at=1,
        completed_at=1,
    )
    return bundle_item(review, item, originals), item


@pytest.mark.asyncio
async def test_ac1_fake_provider_rejected_repair_then_template() -> None:
    bundle, item = _bundle()
    provider = FakeProvider()
    meta = await narrate_item(bundle, provider, extra_names=("Ahri",))
    assert provider.calls == 2
    assert "rejected" in provider.prompts[1].lower() or "unsupported" in provider.prompts[1].lower()
    assert meta.fallback is True
    assert meta.text == item.body
    assert meta.calls == 2


@pytest.mark.asyncio
async def test_null_provider_returns_template() -> None:
    bundle, item = _bundle()
    meta = await narrate_item(bundle, NullProvider(), skip_validate=True)
    assert meta.text == item.body
    assert meta.fallback is False


def test_validator_rejects_number_timestamp_champion() -> None:
    bundle, _item = _bundle()
    failure = validate_bundle_text(
        "You lost 9,999 gold to Yasuo at 47:12", bundle, extra_names=("Ahri",)
    )
    assert failure is not None
    joined = " ".join(failure.offenders)
    assert "9,999" in joined or "9999" in joined
    assert "Yasuo" in failure.offenders
    assert "47:12" in failure.offenders


def test_validator_rounding_tolerance() -> None:
    bundle, _item = _bundle()
    # 900 gold equivalent is allowed; 918 is +2%
    failure = validate_bundle_text("918 gold was lost.", bundle, extra_names=("Ahri",))
    assert failure is None


@pytest.mark.asyncio
async def test_valid_narration_accepted() -> None:
    bundle, item = _bundle()
    provider = FakeProvider('{"explanation": "Ahri died at 8:00 with unseen jungler pressure."}')
    meta = await narrate_item(bundle, provider, extra_names=("Ahri",))
    assert meta.fallback is False
    assert "8:00" in meta.text
    assert provider.calls == 1
    del item


@pytest.mark.asyncio
async def test_provider_exception_falls_back_to_template() -> None:
    bundle, item = _bundle()

    class Boom:
        name = "boom"
        model = "boom"

        async def complete(self, prompt: str, **kwargs: object) -> str:
            del prompt, kwargs
            from riftlens.coaching.providers.base import ProviderUnavailable

            raise ProviderUnavailable("down")

    meta = await narrate_item(bundle, Boom())  # type: ignore[arg-type]
    assert meta.fallback is True
    assert meta.text == item.body


@pytest.mark.asyncio
async def test_llm_cache_hit_and_model_invalidation(tmp_path) -> None:
    bundle, _item = _bundle()
    provider = FakeProvider('{"explanation": "Ahri died at 8:00."}')
    first = await narrate_item(
        bundle, provider, extra_names=("Ahri",), cache=tmp_path
    )
    assert first.cache_hit is False
    second = await narrate_item(
        bundle, provider, extra_names=("Ahri",), cache=tmp_path
    )
    assert second.cache_hit is True
    assert second.text == first.text
    other = FakeProvider('{"explanation": "Ahri died at 8:00."}')
    other.model = "other-model"
    third = await narrate_item(bundle, other, extra_names=("Ahri",), cache=tmp_path)
    assert third.cache_hit is False


@pytest.mark.asyncio
async def test_prompt_version_invalidation(tmp_path, monkeypatch: pytest.MonkeyPatch) -> None:
    bundle, _item = _bundle()
    provider = FakeProvider('{"explanation": "Ahri died at 8:00."}')
    first = await narrate_item(bundle, provider, extra_names=("Ahri",), cache=tmp_path)
    assert first.cache_hit is False
    monkeypatch.setattr("riftlens.coaching.composer.PROMPT_VERSION", "v2")
    second = await narrate_item(bundle, provider, extra_names=("Ahri",), cache=tmp_path)
    assert second.cache_hit is False


@pytest.mark.asyncio
async def test_invalid_narration_is_not_cached(tmp_path) -> None:
    bundle, item = _bundle()
    bad = FakeProvider()
    meta = await narrate_item(bundle, bad, extra_names=("Ahri",), cache=tmp_path)
    assert meta.fallback is True
    assert meta.text == item.body
    good = FakeProvider('{"explanation": "Ahri died at 8:00."}')
    second = await narrate_item(bundle, good, extra_names=("Ahri",), cache=tmp_path)
    assert second.cache_hit is False
    assert second.fallback is False


def test_prompt_snapshots(snapshot) -> None:
    assert load_prompt("finding_v1.md") == snapshot
    assert load_prompt("summary_v1.md") == snapshot
    assert PROMPT_VERSION == "v1"


def test_validator_rejects_unsupported_number() -> None:
    bundle, _item = _bundle()
    failure = validate_bundle_text("You lost 9999 gold.", bundle, extra_names=("Ahri",))
    assert failure is not None


def test_validator_rejects_unsupported_timestamp() -> None:
    bundle, _item = _bundle()
    failure = validate_bundle_text("The death was at 47:12.", bundle, extra_names=("Ahri",))
    assert failure is not None
    assert "47:12" in failure.offenders


def test_validator_rejects_unsupported_champion() -> None:
    bundle, _item = _bundle()
    failure = validate_bundle_text("Yasuo killed you.", bundle, extra_names=("Ahri",))
    assert failure is not None
    assert "Yasuo" in failure.offenders
