"""V.3 research helpers: finding selection and attach-only capture discipline."""

from __future__ import annotations

import importlib.util
from pathlib import Path

from riftlens.visual.window import FindingStamp


def _load_v3_script():
    path = Path(__file__).resolve().parents[2] / "scripts" / "v3_finding_capture.py"
    spec = importlib.util.spec_from_file_location("v3_finding_capture", path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_v3_prefers_r003_death_finding_not_summary() -> None:
    findings = [
        FindingStamp(
            finding_id="01KZT1SVVWKMZHVZM8222ETZ1V",
            rule_id="R-008",
            t_ms=465_947,
            match_id="NA1_5614479225",
            review_id="01KZT1SW9NH14W0EV3P60HPDND",
            participant_id=6,
            title="Missed the objective without a trade",
        ),
        FindingStamp(
            finding_id="01KZT1SW2SRV24TZF5499AR0ER",
            rule_id="R-003",
            t_ms=903_411,
            match_id="NA1_5614479225",
            review_id="01KZT1SW9NH14W0EV3P60HPDND",
            participant_id=6,
            title="Died in the enemy half with no recent ward",
        ),
        FindingStamp(
            finding_id="01KZT1SVXYNTQ7D8TNAQBE6WZY",
            rule_id="R-014",
            t_ms=1_798_780,
            match_id="NA1_5614479225",
            review_id="01KZT1SW9NH14W0EV3P60HPDND",
            participant_id=6,
            title="Tempo wasted after a won fight",
        ),
    ]
    v3 = _load_v3_script()
    chosen = v3._select_v3_finding(findings)
    assert chosen.finding_id == "01KZT1SW2SRV24TZF5499AR0ER"
    assert chosen.rule_id == "R-003"
    assert chosen.t_ms == 903_411


def test_v3_capture_script_is_attach_only() -> None:
    source = Path("scripts/v3_finding_capture.py").read_text(encoding="utf-8")
    assert "UserAssistedStrategy" in source
    assert "strategies=(UserAssistedStrategy(),)" in source
    assert "no re-launch" in source.lower()
    assert "C:\\Users\\" not in source
    assert "openai" not in source.lower()
    assert "ultralytics" not in source.lower()


def test_v3_did_not_add_continuity_module_when_unneeded() -> None:
    visual = Path("riftlens/visual")
    assert not (visual / "continuity.py").exists()
    assert not (visual / "v3_track.py").exists()
    assert (visual / "detect_v2.py").is_file()
    assert (visual / "track.py").is_file()
