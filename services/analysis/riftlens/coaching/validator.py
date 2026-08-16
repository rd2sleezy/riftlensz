from __future__ import annotations

import re
from dataclasses import dataclass

from riftlens.coaching.bundler import AllowedValues, EvidenceBundle

_TIMESTAMP_RE = re.compile(r"\b(\d{1,2}:\d{2}(?::\d{2})?)\b")
_NUMBER_RE = re.compile(r"(?<![\w.])(-?\d{1,3}(?:,\d{3})*(?:\.\d+)?|-?\d+(?:\.\d+)?)(?![\w.])")
_NAME_RE = re.compile(r"\b([A-Z][a-z]+(?:[' ][A-Z][a-z]+)*)\b")
_ROUNDING = 0.02

STOPLIST = frozenset(
    {
        "You",
        "Your",
        "Focus",
        "Keep",
        "Gold",
        "Flash",
        "Ward",
        "Jungler",
        "Minion",
        "Minions",
        "Dragon",
        "Baron",
        "Herald",
        "Tower",
        "Turret",
        "Inhibitor",
        "Nexus",
        "Likely",
        "Certain",
        "Looks",
        "The",
        "This",
        "That",
        "When",
        "After",
        "Before",
        "During",
        "Lane",
        "River",
        "Jungle",
        "Mid",
        "Top",
        "Bot",
        "Support",
        "Adc",
        "About",
        "Lost",
        "Was",
        "With",
        "From",
        "Into",
        "Over",
        "Under",
        "Near",
        "Died",
        "Death",
        "Wave",
        "Push",
        "Pushed",
        "Unseen",
        "Pressure",
        "Catch",
        "Good",
        "Bad",
        "Play",
        "Fight",
        "Team",
        "Enemy",
        "Ally",
        "Objective",
        "Vision",
        "Reset",
        "Recall",
        "Base",
        "Item",
        "Items",
        "Level",
        "Cs",
    }
)


@dataclass(frozen=True)
class ValidationFailure:
    offenders: tuple[str, ...]
    reason: str

    def describe(self) -> str:
        """Return a repair-facing description of the violations."""
        joined = ", ".join(self.offenders)
        return f"{self.reason}: {joined}"


def validate_narration(
    text: str,
    allowed: AllowedValues,
    *,
    extra_names: tuple[str, ...] = (),
) -> ValidationFailure | None:
    """Return a failure when narration cites values absent from the bundle.

    Timestamps are stripped before number extraction so ``mm:ss`` does not yield
    stray integers. Champion-like tokens must be in allowed names, extra roster
    names, or the stoplist. Numbers may match an allowed value within ±2%.
    """
    offenders: list[str] = []
    timestamps = _TIMESTAMP_RE.findall(text)
    allowed_ts = {item.strip() for item in allowed.timestamps}
    for stamp in timestamps:
        if stamp not in allowed_ts:
            offenders.append(stamp)
    stripped = _TIMESTAMP_RE.sub(" ", text)
    allowed_nums = [float(item) for item in allowed.numbers]
    for raw in _NUMBER_RE.findall(stripped):
        number = _parse_number(raw)
        if number is None:
            continue
        if not _number_allowed(number, allowed_nums):
            offenders.append(raw)
    allowed_names = {item for item in allowed.names} | set(extra_names) | set(STOPLIST)
    allowed_lower = {item.lower() for item in allowed_names}
    for name in _NAME_RE.findall(text):
        if name.lower() not in allowed_lower:
            offenders.append(name)
    if not offenders:
        return None
    unique = tuple(dict.fromkeys(offenders))
    return ValidationFailure(offenders=unique, reason="unsupported tokens")


def validate_bundle_text(text: str, bundle: EvidenceBundle, extra_names: tuple[str, ...] = ()) -> (
    ValidationFailure | None
):
    """Validate ``text`` against one EvidenceBundle."""
    return validate_narration(text, bundle.allowed_values, extra_names=extra_names)


def _parse_number(raw: str) -> float | None:
    cleaned = raw.replace(",", "")
    try:
        return float(cleaned)
    except ValueError:
        return None


def _number_allowed(value: float, allowed: list[float]) -> bool:
    for candidate in allowed:
        if candidate == 0.0:
            if abs(value) <= 1e-9:
                return True
            continue
        if abs(value - candidate) <= abs(candidate) * _ROUNDING:
            return True
        if abs(value - candidate) <= 0.5 and abs(candidate) < 10:
            return True
    return False
