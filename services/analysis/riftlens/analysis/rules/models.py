from __future__ import annotations

from collections.abc import Mapping, Sequence
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from riftlens.domain.enums import DataTier, FactKind, GamePhase, Role, Severity

EvaluateOn = Literal["PERIODIC", "EVENT", "WINDOW"]

_ROLE_ALIASES: dict[str, Role] = {
    "TOP": Role.TOP,
    "JUNGLE": Role.JUNGLE,
    "MIDDLE": Role.MIDDLE,
    "MID": Role.MIDDLE,
    "BOTTOM": Role.BOTTOM,
    "ADC": Role.BOTTOM,
    "UTILITY": Role.UTILITY,
    "SUPPORT": Role.UTILITY,
    "UNKNOWN": Role.UNKNOWN,
}


class ChampionFilter(BaseModel):
    model_config = ConfigDict(extra="forbid")

    include: list[str] = Field(default_factory=lambda: ["*"])
    exclude: list[str] = Field(default_factory=list)


class Applicability(BaseModel):
    model_config = ConfigDict(extra="forbid")

    roles: list[Role]
    champions: ChampionFilter = Field(default_factory=ChampionFilter)
    champion_tags_exclude: list[str] = Field(default_factory=list)
    queues: list[int]
    phases: list[GamePhase]
    min_rank: str | None = None
    max_rank: str | None = None

    @field_validator("roles", mode="before")
    @classmethod
    def _coerce_roles(cls, value: object) -> list[Role]:
        if not isinstance(value, list):
            raise TypeError("applicability.roles must be a list")
        out: list[Role] = []
        for item in value:
            key = str(item).upper()
            if key not in _ROLE_ALIASES:
                raise ValueError(f"unknown role {item!r}")
            out.append(_ROLE_ALIASES[key])
        return out


class RequiredInputsItem(BaseModel):
    model_config = ConfigDict(extra="forbid")

    facts: list[str] = Field(default_factory=list)
    features: list[str] = Field(default_factory=list)
    min_confidence: dict[str, float] = Field(default_factory=dict)


class Trigger(BaseModel):
    model_config = ConfigDict(extra="forbid")

    evaluate_on: EvaluateOn
    predicate: str
    period_ms: int | None = None
    fact_kinds: list[FactKind] = Field(default_factory=list)
    segmenter: str | None = None

    @field_validator("fact_kinds", mode="before")
    @classmethod
    def _coerce_kinds(cls, value: object) -> object:
        if value is None:
            return []
        return value

    @model_validator(mode="after")
    def _check_trigger_fields(self) -> Trigger:
        if self.evaluate_on == "PERIODIC":
            if self.period_ms is None or self.period_ms <= 0:
                raise ValueError("PERIODIC trigger requires period_ms > 0")
        if self.evaluate_on == "WINDOW" and not self.segmenter:
            raise ValueError("WINDOW trigger requires segmenter")
        return self


class SeverityModifier(BaseModel):
    model_config = ConfigDict(extra="forbid", populate_by_name=True)

    condition: str = Field(alias="if")
    then: int


class RuleDefinition(BaseModel):
    """YAML rule shape from the technical design §4.1."""

    model_config = ConfigDict(extra="forbid")

    id: str
    version: int
    name: str
    concept_id: str
    category: str
    severity_base: Severity
    data_tier: DataTier
    patch_range: str | None = None
    applicability: Applicability
    required_inputs: list[RequiredInputsItem] = Field(default_factory=list)
    trigger: Trigger
    params: dict[str, Any] = Field(default_factory=dict)
    severity_modifiers: list[SeverityModifier] = Field(default_factory=list)
    evidence_template: list[str] = Field(default_factory=list)
    explanation: str = ""
    better_alternative: str = ""
    false_positives: list[str]
    suppressed_by: list[str] = Field(default_factory=list)
    cooldown_ms: int = 0
    max_findings_per_match: int | None = None
    is_strength: bool = False
    requires_visual: bool = False

    @field_validator("false_positives")
    @classmethod
    def _min_false_positives(cls, value: list[str]) -> list[str]:
        if len(value) < 2:
            raise ValueError("false_positives must contain at least 2 entries (§4.1)")
        return value

    def required_fact_names(self) -> tuple[str, ...]:
        """Return declared required fact names across input blocks."""
        names: list[str] = []
        for block in self.required_inputs:
            names.extend(block.facts)
        return tuple(names)

    def required_feature_names(self) -> tuple[str, ...]:
        """Return declared required feature names across input blocks."""
        names: list[str] = []
        for block in self.required_inputs:
            names.extend(block.features)
        return tuple(names)

    def min_confidences(self) -> dict[str, float]:
        """Return merged per-feature confidence floors from required_inputs."""
        merged: dict[str, float] = {}
        for block in self.required_inputs:
            merged.update(block.min_confidence)
        return merged

    def event_fact_kinds(self) -> tuple[FactKind, ...]:
        """Return EVENT candidate kinds from trigger or required_inputs facts."""
        if self.trigger.fact_kinds:
            return tuple(self.trigger.fact_kinds)
        kinds: list[FactKind] = []
        for name in self.required_fact_names():
            resolved = _fact_kind(name)
            if resolved is not None:
                kinds.append(resolved)
        return tuple(kinds)


class RulePack:
    """In-memory validated rule set plus known taxonomy ids."""

    def __init__(self, rules: Sequence[RuleDefinition], concept_ids: Sequence[str]) -> None:
        self.rules = tuple(rules)
        self.concept_ids = frozenset(concept_ids)
        self.version = str(max((rule.version for rule in rules), default=1))

    def applicable(
        self,
        *,
        role: Role,
        champion: str,
        patch: str,
        queue: int,
        available_tiers: frozenset[DataTier],
        champion_tags: Sequence[str] = (),
    ) -> list[RuleDefinition]:
        """Return rules that apply to this subject. Assumes GST fields are populated."""
        out: list[RuleDefinition] = []
        tags = {tag.upper() for tag in champion_tags}
        for rule in self.rules:
            if not _applies(
                rule,
                role=role,
                champion=champion,
                patch=patch,
                queue=queue,
                available_tiers=available_tiers,
                champion_tags=tags,
            ):
                continue
            out.append(rule)
        return out


def _applies(
    rule: RuleDefinition,
    *,
    role: Role,
    champion: str,
    patch: str,
    queue: int,
    available_tiers: frozenset[DataTier],
    champion_tags: set[str],
) -> bool:
    app = rule.applicability
    if role not in app.roles:
        return False
    if queue not in app.queues:
        return False
    if rule.data_tier not in available_tiers:
        return False
    if rule.requires_visual and DataTier.CV_REQUIRED not in available_tiers:
        return False
    if not patch_in_range(rule.patch_range, patch):
        return False
    if not _champion_allowed(app.champions, champion):
        return False
    excluded = {tag.upper() for tag in app.champion_tags_exclude}
    if excluded and champion_tags.intersection(excluded):
        return False
    return True


def _champion_allowed(filt: ChampionFilter, champion: str) -> bool:
    name = champion.casefold()
    excluded = {item.casefold() for item in filt.exclude}
    if name in excluded:
        return False
    include = [item.casefold() for item in filt.include] or ["*"]
    if "*" in include:
        return True
    return name in include


def patch_in_range(spec: str | None, patch: str) -> bool:
    """Return whether ``patch`` (gameVersion or major.minor) satisfies ``spec``."""
    if spec is None or spec.strip() == "":
        return True
    target = _patch_tuple(patch)
    text = spec.strip()
    if text.startswith(">="):
        return target >= _patch_tuple(text[2:])
    if text.startswith("<="):
        return target <= _patch_tuple(text[2:])
    if text.startswith(">"):
        return target > _patch_tuple(text[1:])
    if text.startswith("<"):
        return target < _patch_tuple(text[1:])
    if "-" in text:
        left, _, right = text.partition("-")
        if left[:1].isdigit() and right[:1].isdigit():
            return _patch_tuple(left) <= target <= _patch_tuple(right)
    return target[:2] == _patch_tuple(text)[:2]


def _patch_tuple(raw: str) -> tuple[int, ...]:
    cleaned = raw.strip().lstrip("vV")
    nums: list[int] = []
    for part in cleaned.split("."):
        digits = "".join(ch for ch in part if ch.isdigit())
        if digits == "":
            break
        nums.append(int(digits))
        if len(nums) >= 3:
            break
    if not nums:
        return (0, 0)
    if len(nums) == 1:
        return (nums[0], 0)
    return tuple(nums)


def _fact_kind(name: str) -> FactKind | None:
    key = name.strip().upper()
    if key == "PARTICIPANT_FRAME":
        return None
    try:
        return FactKind(key)
    except ValueError:
        return None


def dump_rule_schema() -> Mapping[str, Any]:
    """Return the JSON Schema for RuleDefinition. Assumes pydantic v2."""
    return RuleDefinition.model_json_schema()
