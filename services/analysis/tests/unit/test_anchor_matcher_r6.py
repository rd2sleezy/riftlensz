from __future__ import annotations

from riftlens.replay_host.clock.anchor_matcher import KillEvent, match_kill_anchors


def _kill(
    t_ms: int,
    killer: str | None = None,
    victim: str | None = None,
    *,
    killer_name: str | None = None,
    victim_name: str | None = None,
) -> KillEvent:
    return KillEvent(
        t_ms=t_ms,
        killer_champion=killer,
        victim_champion=victim,
        killer_name=killer_name,
        victim_name=victim_name,
    )


def test_clean_identity_matching_accepts() -> None:
    riot = (
        _kill(100_000, "Ahri", "Zed"),
        _kill(200_000, "Lux", "Jinx"),
        _kill(300_000, "Garen", "Darius"),
        _kill(400_000, "LeeSin", "Graves"),
    )
    lcd = (
        _kill(98_000, "Ahri", "Zed"),
        _kill(198_000, "Lux", "Jinx"),
        _kill(298_000, "Garen", "Darius"),
        _kill(398_000, "LeeSin", "Graves"),
    )
    result = match_kill_anchors(riot, lcd)
    assert result.accepted is True
    assert result.reason == "ok"
    assert result.offset_ms == 2000
    assert result.inlier_count >= 3
    assert result.residual_ms is not None and result.residual_ms <= 750
    assert result.stdev_ms is not None and result.stdev_ms <= 750
    assert all(item.method == "identity" for item in result.anchors)


def test_missing_lcd_events_still_calibrates_with_remaining() -> None:
    riot = (
        _kill(100_000, "Ahri", "Zed"),
        _kill(200_000, "Lux", "Jinx"),
        _kill(300_000, "Garen", "Darius"),
        _kill(400_000, "LeeSin", "Graves"),
    )
    lcd = (
        _kill(98_000, "Ahri", "Zed"),
        _kill(198_000, "Lux", "Jinx"),
        _kill(398_000, "LeeSin", "Graves"),
    )
    result = match_kill_anchors(riot, lcd)
    assert result.accepted is True
    assert result.inlier_count == 3
    assert result.offset_ms == 2000


def test_extra_replay_events_are_rejected_not_forced() -> None:
    riot = (
        _kill(100_000, "Ahri", "Zed"),
        _kill(200_000, "Lux", "Jinx"),
        _kill(300_000, "Garen", "Darius"),
    )
    lcd = (
        _kill(98_000, "Ahri", "Zed"),
        _kill(150_000, "Yasuo", "Malphite"),
        _kill(198_000, "Lux", "Jinx"),
        _kill(298_000, "Garen", "Darius"),
    )
    result = match_kill_anchors(riot, lcd)
    assert result.accepted is True
    assert result.offset_ms == 2000
    assert any(item.reason == "no_identity_peer" for item in result.rejected)


def test_duplicate_champion_kills_match_fifo_ordinal_within_identity() -> None:
    riot = (
        _kill(100_000, "Ahri", "Zed"),
        _kill(180_000, "Ahri", "Zed"),
        _kill(260_000, "Lux", "Jinx"),
        _kill(340_000, "Garen", "Darius"),
    )
    lcd = (
        _kill(98_000, "Ahri", "Zed"),
        _kill(178_000, "Ahri", "Zed"),
        _kill(258_000, "Lux", "Jinx"),
        _kill(338_000, "Garen", "Darius"),
    )
    result = match_kill_anchors(riot, lcd)
    assert result.accepted is True
    assert result.offset_ms == 2000
    ahri = [item for item in result.anchors if item.identity_key == ("champ:ahri", "champ:zed")]
    assert len(ahri) == 2
    assert ahri[0].riot_index < ahri[1].riot_index
    assert ahri[0].lcd_index < ahri[1].lcd_index


def test_same_killer_victim_reordered_is_ambiguous_or_residual() -> None:
    riot = (
        _kill(100_000, "Ahri", "Zed"),
        _kill(200_000, "Ahri", "Zed"),
        _kill(300_000, "Lux", "Jinx"),
        _kill(400_000, "Garen", "Darius"),
    )
    lcd = (
        _kill(198_000, "Ahri", "Zed"),
        _kill(98_000, "Ahri", "Zed"),
        _kill(298_000, "Lux", "Jinx"),
        _kill(398_000, "Garen", "Darius"),
    )
    result = match_kill_anchors(riot, lcd)
    assert result.accepted is False
    assert result.reason in {"residual_too_high", "insufficient_inliers", "ambiguous"}


def test_reordered_distinct_identities_still_match() -> None:
    riot = (
        _kill(100_000, "Ahri", "Zed"),
        _kill(200_000, "Lux", "Jinx"),
        _kill(300_000, "Garen", "Darius"),
    )
    lcd = (
        _kill(298_000, "Garen", "Darius"),
        _kill(98_000, "Ahri", "Zed"),
        _kill(198_000, "Lux", "Jinx"),
    )
    result = match_kill_anchors(riot, lcd)
    assert result.accepted is True
    assert result.offset_ms == 2000


def test_noisy_timestamps_within_gate() -> None:
    riot = (
        _kill(120_000, "Ahri", "Zed"),
        _kill(240_000, "Lux", "Jinx"),
        _kill(360_000, "Garen", "Darius"),
        _kill(480_000, "LeeSin", "Graves"),
    )
    lcd = (
        _kill(119_600, "Ahri", "Zed"),
        _kill(239_900, "Lux", "Jinx"),
        _kill(359_400, "Garen", "Darius"),
        _kill(479_700, "LeeSin", "Graves"),
    )
    result = match_kill_anchors(riot, lcd)
    assert result.accepted is True
    assert result.residual_ms is not None and result.residual_ms <= 750


def test_one_bad_outlier_is_dropped() -> None:
    riot = (
        _kill(100_000, "Ahri", "Zed"),
        _kill(200_000, "Lux", "Jinx"),
        _kill(300_000, "Garen", "Darius"),
        _kill(400_000, "LeeSin", "Graves"),
        _kill(500_000, "Orianna", "Syndra"),
    )
    lcd = (
        _kill(98_000, "Ahri", "Zed"),
        _kill(198_000, "Lux", "Jinx"),
        _kill(250_000, "Garen", "Darius"),
        _kill(398_000, "LeeSin", "Graves"),
        _kill(498_000, "Orianna", "Syndra"),
    )
    result = match_kill_anchors(riot, lcd)
    assert result.accepted is True
    assert result.offset_ms == 2000
    assert result.inlier_count == 4


def test_completely_wrong_event_set_rejected() -> None:
    riot = (
        _kill(100_000, "Ahri", "Zed"),
        _kill(200_000, "Lux", "Jinx"),
        _kill(300_000, "Garen", "Darius"),
        _kill(400_000, "LeeSin", "Graves"),
    )
    lcd = (
        _kill(12_000, "Yasuo", "Malphite"),
        _kill(40_000, "Jhin", "Caitlyn"),
        _kill(90_000, "Sett", "Ornn"),
        _kill(140_000, "Viego", "Kindred"),
    )
    result = match_kill_anchors(riot, lcd)
    assert result.accepted is False
    assert result.reason in {"ambiguous", "insufficient_anchors", "residual_too_high"}
    assert result.offset_ms is None or result.reason == "residual_too_high"


def test_fewer_than_three_valid_anchors() -> None:
    riot = (_kill(100_000, "Ahri", "Zed"), _kill(200_000, "Lux", "Jinx"))
    lcd = (_kill(98_000, "Ahri", "Zed"), _kill(198_000, "Lux", "Jinx"))
    result = match_kill_anchors(riot, lcd)
    assert result.accepted is False
    assert result.reason == "insufficient_anchors"


def test_high_residual_spread_rejected() -> None:
    riot = (
        _kill(100_000, "Ahri", "Zed"),
        _kill(200_000, "Lux", "Jinx"),
        _kill(300_000, "Garen", "Darius"),
        _kill(400_000, "LeeSin", "Graves"),
    )
    lcd = (
        _kill(98_000, "Ahri", "Zed"),
        _kill(190_000, "Lux", "Jinx"),
        _kill(280_000, "Garen", "Darius"),
        _kill(360_000, "LeeSin", "Graves"),
    )
    result = match_kill_anchors(riot, lcd)
    assert result.accepted is False
    assert result.reason == "residual_too_high"
    assert result.offset_ms is not None


def test_ordinal_fallback_without_identity_is_deterministic() -> None:
    riot = (_kill(100_000), _kill(200_000), _kill(300_000), _kill(400_000))
    lcd = (_kill(97_000), _kill(197_000), _kill(297_000), _kill(397_000))
    first = match_kill_anchors(riot, lcd)
    second = match_kill_anchors(riot, lcd)
    assert first == second
    assert first.accepted is True
    assert first.offset_ms == 3000
    assert all(item.method == "ordinal" for item in first.anchors)


def test_empty_inputs_insufficient_events() -> None:
    assert match_kill_anchors((), ()).reason == "insufficient_events"
    assert match_kill_anchors((_kill(1, "A", "B"),), ()).reason == "insufficient_events"
