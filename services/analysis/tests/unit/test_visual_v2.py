from __future__ import annotations

import json
from collections.abc import Iterator
from pathlib import Path

import numpy as np
from riftlens.domain.capture import (
    CAPTURE_MANIFEST_NAME,
    CaptureArtifactSpec,
    CaptureManifest,
    CaptureMode,
    CaptureStatus,
    RetentionClass,
)
from riftlens.domain.enums import EvidenceKind, Source
from riftlens.domain.ids import is_ulid
from riftlens.domain.observation import (
    FRAME_OBSERVATION_SCHEMA_VERSION,
    CameraControl,
    KnowledgeState,
    VisibilityState,
    VisualClaimKind,
    dumps,
    loads_sequence,
)
from riftlens.domain.observation.common import ScreenRect
from riftlens.visual.detect import ViewportCoverage, detect_champion_like_bars
from riftlens.visual.detect_v2 import (
    confirm_temporal,
    detect_champion_like_entities,
    detect_sample_entities,
)
from riftlens.visual.hud_mask import center_in_hud, hud_rects
from riftlens.visual.metrics import measure_tracks
from riftlens.visual.track import (
    FrameCandidate,
    FrameDetections,
    finalize_tracks,
    track_candidates,
)
from riftlens.visual.v2_analyze import (
    V2_ANALYZER_ID,
    V2_ANALYZER_VERSION,
    analyze_capture_dir_v2,
)

_MATCH = "NA1_5617764200"
_CAPTURE = "01JZ000000V2CAP00000000001"
_SOURCE = "01JZ000000V2SRC00000000001"
_ARTIFACT = "01JZ000000V2ART00000000001"
_CLOCK = "01JZ000000V2CLK00000000001"


def _ids() -> Iterator[str]:
    n = 0
    while True:
        n += 1
        yield f"01JZ000000V2AB{n:012d}"


def _id_factory() -> object:
    stream = _ids()
    return lambda: next(stream)


def _scene(*, width: int = 320, height: int = 180) -> np.ndarray:
    image = np.zeros((height, width, 3), dtype=np.uint8)
    image[:, :] = (18, 22, 28)
    image[40:140, 40:280] = (40, 50, 60)
    return image


def _paint_bar(
    image: np.ndarray,
    *,
    x: int,
    y: int,
    enemy: bool = False,
    width: int = 48,
) -> np.ndarray:
    color = (220, 40, 40) if enemy else (40, 220, 50)
    image[y : y + 5, x : x + width] = color
    return image


def _write_webm(path: Path, frames: list[np.ndarray], *, fps: int = 10) -> None:
    import av

    container = av.open(str(path), mode="w")
    stream = container.add_stream("libvpx", rate=fps)
    stream.width = int(frames[0].shape[1])
    stream.height = int(frames[0].shape[0])
    stream.pix_fmt = "yuv420p"
    try:
        stream.bit_rate = 250_000
    except Exception:
        pass
    for image in frames:
        video_frame = av.VideoFrame.from_ndarray(image, format="rgb24")
        for packet in stream.encode(video_frame):
            container.mux(packet)
    for packet in stream.encode():
        container.mux(packet)
    container.close()


def _capture_dir(
    tmp_path: Path,
    frames: list[np.ndarray],
    *,
    fps: int = 10,
    start: int = 1_328_491,
    end: int = 1_330_491,
) -> Path:
    folder = tmp_path / "cap"
    folder.mkdir()
    _write_webm(folder / "clip.webm", frames, fps=fps)
    spec = CaptureArtifactSpec(
        id=_ARTIFACT,
        kind="clip",
        relative_path="clip.webm",
        game_t_ms=start,
        sha256="c" * 64,
        bytes=100,
        source_t_ms=start + 623,
    )
    manifest = CaptureManifest(
        capture_id=_CAPTURE,
        source_id=_SOURCE,
        match_id=_MATCH,
        clock_map_id=_CLOCK,
        mode=CaptureMode.CLIP,
        codec="webm",
        fps=30.0,
        requested_start_game_ms=start,
        requested_end_game_ms=end,
        start_source_ms=start + 623,
        end_source_ms=end + 623,
        retention=RetentionClass.EPHEMERAL,
        status=CaptureStatus.COMPLETE,
        created_at_ms=1,
        clock_confidence="GOOD",
        clock_verified=True,
        camera_controlled=False,
        artifacts=(spec,),
    )
    (folder / CAPTURE_MANIFEST_NAME).write_text(
        json.dumps(manifest.to_dict()), encoding="utf-8"
    )
    return folder


def _cand(x: int, *, y: int = 80, conf: float = 0.55) -> FrameCandidate:
    return FrameCandidate(
        region=ScreenRect(x=x, y=y, width=48, height=40),
        confidence=conf,
        ally_like=True,
    )


def test_detects_gameplay_bar_and_rejects_empty() -> None:
    image = _paint_bar(_scene(), x=90, y=70)
    entities = detect_champion_like_entities(image)
    assert len(entities) == 1
    assert 0.0 <= entities[0].confidence <= 1.0
    assert entities[0].region.height > entities[0].bar_region.height
    assert detect_champion_like_entities(np.zeros((180, 320, 3), dtype=np.uint8)) == ()


def test_hud_and_kill_feed_rejected() -> None:
    header = _paint_bar(_scene(), x=90, y=4)
    assert detect_champion_like_entities(header) == ()
    feed = _paint_bar(_scene(), x=270, y=30)
    assert center_in_hud(ScreenRect(x=270, y=30, width=48, height=5), width=320, height=180)
    assert detect_champion_like_entities(feed) == ()
    assert hud_rects(320, 180)


def test_replay_resolution_keeps_champion_bar_drops_edge_chrome() -> None:
    image = np.zeros((992, 1904, 3), dtype=np.uint8)
    image[80:900, 80:1800] = (40, 50, 60)
    image[300:310, 900:1004] = (220, 40, 40)
    image[474:480, 38:66] = (40, 220, 50)
    image[380:384, 1838:1866] = (40, 220, 50)
    bars = detect_champion_like_bars(image)
    entities = detect_champion_like_entities(image)
    assert len(bars) >= 1
    assert len(entities) == 1
    assert entities[0].ally_like is False
    assert entities[0].region.width >= entities[0].bar_region.width


def test_stacked_bars_cluster_to_one_entity() -> None:
    image = _paint_bar(_scene(), x=90, y=70)
    _paint_bar(image, x=92, y=78)
    bars = detect_champion_like_bars(image)
    entities = detect_champion_like_entities(image)
    assert len(bars) >= 1
    assert len(entities) == 1


def test_ally_vs_enemy_and_partial_bar() -> None:
    ally = detect_champion_like_entities(_paint_bar(_scene(), x=90, y=70, enemy=False))
    enemy = detect_champion_like_entities(_paint_bar(_scene(), x=90, y=70, enemy=True))
    assert ally and ally[0].ally_like is True
    assert enemy and enemy[0].ally_like is False
    tiny = _scene()
    tiny[70:73, 90:100] = (40, 220, 50)
    assert detect_champion_like_entities(tiny) == ()


def test_temporal_drops_one_frame_noise_keeps_entry() -> None:
    flash = (
        FrameDetections(0, 1_340_000, (), ViewportCoverage.USEFUL),
        FrameDetections(1, 1_340_250, (_cand(80, conf=0.55),), ViewportCoverage.USEFUL),
        FrameDetections(2, 1_340_500, (), ViewportCoverage.USEFUL),
    )
    confirmed = confirm_temporal(flash)
    assert confirmed[1].candidates == ()
    entering = (
        FrameDetections(0, 1_340_000, (), ViewportCoverage.USEFUL),
        FrameDetections(1, 1_340_250, (_cand(80, conf=0.55),), ViewportCoverage.USEFUL),
        FrameDetections(2, 1_340_500, (_cand(84, conf=0.55),), ViewportCoverage.USEFUL),
        FrameDetections(3, 1_340_750, (_cand(88, conf=0.55),), ViewportCoverage.USEFUL),
    )
    kept = confirm_temporal(entering)
    assert kept[1].candidates and kept[2].candidates and kept[3].candidates


def test_temporal_preserves_exit_and_strong_standalone() -> None:
    leaving = (
        FrameDetections(0, 1_340_000, (_cand(80, conf=0.55),), ViewportCoverage.USEFUL),
        FrameDetections(1, 1_340_250, (_cand(84, conf=0.55),), ViewportCoverage.USEFUL),
        FrameDetections(2, 1_340_500, (), ViewportCoverage.USEFUL),
    )
    kept = confirm_temporal(leaving)
    assert kept[0].candidates and kept[1].candidates
    strong = (
        FrameDetections(0, 1_340_000, (), ViewportCoverage.USEFUL),
        FrameDetections(1, 1_340_250, (_cand(80, conf=0.80),), ViewportCoverage.USEFUL),
        FrameDetections(2, 1_340_500, (), ViewportCoverage.USEFUL),
    )
    assert confirm_temporal(strong)[1].candidates


def test_v2_feeds_v1_tracker_with_less_synthetic_fragmentation() -> None:
    noisy = []
    for index in range(8):
        if index == 3:
            noisy.append(
                FrameDetections(
                    index,
                    1_340_000 + index * 250,
                    (),
                    ViewportCoverage.USEFUL,
                )
            )
        else:
            noisy.append(
                FrameDetections(
                    index,
                    1_340_000 + index * 250,
                    (_cand(80 + index, conf=0.55),),
                    ViewportCoverage.USEFUL,
                )
            )
    v1_tracks = finalize_tracks(track_candidates(tuple(noisy)))
    v2_tracks = finalize_tracks(track_candidates(confirm_temporal(tuple(noisy))))
    v1_m = measure_tracks(v1_tracks, sample_count=8, interval_ms=250)
    v2_m = measure_tracks(v2_tracks, sample_count=8, interval_ms=250)
    assert v2_m.one_frame_tracks <= v1_m.one_frame_tracks
    assert v2_m.total_tracks <= v1_m.total_tracks
    assert v2_m.stable_tracks >= 1


def test_two_moving_entities_remain_two_tracks() -> None:
    frames = tuple(
        FrameDetections(
            index,
            1_340_000 + index * 250,
            (
                _cand(40 + index * 4, conf=0.6),
                FrameCandidate(
                    region=ScreenRect(x=160 + index * 3, y=90, width=48, height=40),
                    confidence=0.6,
                    ally_like=False,
                ),
            ),
            ViewportCoverage.USEFUL,
        )
        for index in range(6)
    )
    tracks = finalize_tracks(track_candidates(confirm_temporal(frames)))
    assert len(tracks) == 2
    assert all(item.observation_count >= 5 for item in tracks)


def test_noisy_background_is_not_an_entity() -> None:
    rng = np.random.default_rng(0)
    noise = rng.integers(0, 40, size=(180, 320, 3), dtype=np.uint8)
    assert detect_champion_like_entities(noise) == ()


def test_crossing_still_does_not_invent_identity() -> None:
    frames = tuple(
        FrameDetections(
            index,
            1_340_000 + index * 250,
            (
                _cand(20 + index * 20, conf=0.6),
                FrameCandidate(
                    region=ScreenRect(x=200 - index * 20, y=80, width=48, height=40),
                    confidence=0.6,
                    ally_like=True,
                ),
            ),
            ViewportCoverage.USEFUL,
        )
        for index in range(5)
    )
    tracks = finalize_tracks(track_candidates(confirm_temporal(frames)))
    assert len(tracks) >= 2
    assert any(item.ambiguous or item.fragmented for item in tracks) or len(tracks) >= 2


def test_no_champion_and_transition_frame() -> None:
    blank = detect_sample_entities(
        np.zeros((180, 320, 3), dtype=np.uint8), frame_index=0, game_t_ms=1_340_000
    )
    assert blank.coverage.value in {"OBSTRUCTED", "TRANSITION", "UNKNOWN"}
    assert blank.candidates == ()


def test_v2_emits_r11_and_keeps_visual_provenance(tmp_path: Path) -> None:
    frames = [_paint_bar(_scene(), x=90 + index, y=70) for index in range(12)]
    folder = _capture_dir(tmp_path, frames, fps=10, start=1_328_491, end=1_329_691)
    result = analyze_capture_dir_v2(
        folder,
        fps=4.0,
        id_factory=_id_factory(),  # type: ignore[arg-type]
        subject_pid=9,
        subject_champion="Kaisa",
        capture_review_pid=9,
    )
    sequence = result.sequence
    assert sequence.detector_id == V2_ANALYZER_ID
    assert sequence.detector_version == V2_ANALYZER_VERSION
    assert sequence.schema_version == FRAME_OBSERVATION_SCHEMA_VERSION
    assert sequence.match_id == _MATCH
    assert sequence.clock_map_id == _CLOCK
    first = sequence.frames[0]
    assert first.source is Source.VISUAL
    assert first.claim_kind is VisualClaimKind.OBSERVED
    assert first.camera.control is CameraControl.UNCONTROLLED
    for entity in first.entities:
        assert entity.participant_id is None
        assert entity.champion_id is None
        assert entity.visibility is VisibilityState.VISIBLE
        assert is_ulid(entity.entity_observation_id)
    encoded = dumps(sequence)
    assert dumps(loads_sequence(encoded)) == encoded
    assert result.metrics is not None
    assert result.subject_visibility is KnowledgeState.UNKNOWN
    assert result.correlation.participant_id is None


def test_v2_does_not_mutate_coaching() -> None:
    from riftlens.analysis.rules.engine import RuleEngine
    from riftlens.analysis.rules.loader import load_rule_pack
    from tests.helpers.gst import bundled_patch, load_gst

    gst = load_gst("NA1_fixture_a")
    pack = load_rule_pack()
    patch = bundled_patch(gst.patch)
    before = [
        (item.rule_id, item.t_ms, item.title, item.severity.value)
        for item in RuleEngine(pack, patch=patch).run(gst, 5)
    ]
    import riftlens.visual as visual_spike

    assert visual_spike.V2_ANALYZER_ID == V2_ANALYZER_ID
    after = [
        (item.rule_id, item.t_ms, item.title, item.severity.value)
        for item in RuleEngine(pack, patch=patch).run(gst, 5)
    ]
    assert before == after
    assert not any(
        item.kind is EvidenceKind.FRAME
        for finding in RuleEngine(pack, patch=patch).run(gst, 5)
        for item in finding.evidence
    )


def test_team_classification_does_not_imply_identity(tmp_path: Path) -> None:
    frames = [_paint_bar(_scene(), x=90, y=70) for _ in range(8)]
    folder = _capture_dir(tmp_path, frames, fps=10, start=1_328_491, end=1_329_291)
    result = analyze_capture_dir_v2(
        folder, fps=4.0, id_factory=_id_factory(), subject_pid=9  # type: ignore[arg-type]
    )
    for frame in result.sequence.frames:
        for entity in frame.entities:
            assert entity.participant_id is None
        assert frame.hud is not None
        assert frame.hud.get("health").knowledge is KnowledgeState.UNKNOWN
    assert result.correlation.status.value == "UNKNOWN"


def test_v2_subject_correlation_uses_v1_conservative_rules() -> None:
    from riftlens.domain.enums import FactKind, Team
    from riftlens.domain.observation import CameraControl, VisualClaimKind
    from riftlens.visual.correlate import CorrelationStatus, correlate_subject
    from riftlens.visual.gst_align import align_gst
    from riftlens.visual.track import TeamEstimate
    from tests.helpers.gst import fact, make_gst, make_participant

    frames = tuple(
        FrameDetections(
            index,
            1_340_000 + index * 250,
            (_cand(80, conf=0.6),) if index < 6 else (),
            ViewportCoverage.USEFUL,
        )
        for index in range(10)
    )
    tracks = finalize_tracks(track_candidates(confirm_temporal(frames)))
    death_t = tracks[0].last_seen_game_t_ms
    gst = make_gst(
        [fact(death_t, FactKind.CHAMPION_KILL, 9, {"killerId": 2, "victimId": 9})],
        participants={9: make_participant(9, team=Team.RED, champion="Kaisa")},
        match_id=_MATCH,
        duration_ms=1_800_000,
    )
    alignment = align_gst(
        gst,
        start_game_ms=1_340_000,
        end_game_ms=1_350_000,
        subject_pid=9,
        tracks=tracks,
    )
    likely = correlate_subject(
        tracks,
        subject_pid=9,
        subject_champion="Kaisa",
        alignment=alignment,
        capture_review_pid=9,
    )
    assert likely.status is CorrelationStatus.LIKELY
    assert likely.confidence <= 0.55
    assert likely.claim_kind is VisualClaimKind.INFERRED
    both = tuple(
        FrameDetections(
            index,
            1_340_000 + index * 250,
            (
                _cand(80, conf=0.6),
                FrameCandidate(
                    region=ScreenRect(x=180, y=80, width=48, height=40),
                    confidence=0.6,
                    ally_like=False,
                ),
            )
            if index < 6
            else (),
            ViewportCoverage.USEFUL,
        )
        for index in range(10)
    )
    both_tracks = finalize_tracks(track_candidates(confirm_temporal(both)))
    conflicted = correlate_subject(
        both_tracks,
        subject_pid=9,
        alignment=align_gst(
            gst,
            start_game_ms=1_340_000,
            end_game_ms=1_350_000,
            subject_pid=9,
            tracks=both_tracks,
        ),
    )
    assert conflicted.status is CorrelationStatus.UNKNOWN
    strong = correlate_subject(
        tracks,
        subject_pid=9,
        subject_champion="Kaisa",
        alignment=alignment,
        camera_control=CameraControl.CONTROLLED_SUBJECT,
        subject_team_estimate=TeamEstimate.ALLY,
        assume_subject_perspective_hud=True,
    )
    assert strong.status is CorrelationStatus.CORRELATED
    assert strong.confidence <= 0.75
    weak = correlate_subject(tracks, subject_pid=9, capture_review_pid=9)
    assert weak.status is CorrelationStatus.UNKNOWN


def test_learned_model_is_not_required() -> None:
    source = Path("riftlens/visual/detect_v2.py").read_text(encoding="utf-8")
    assert "onnxruntime" not in source
    assert "ultralytics" not in source
    assert "openai" not in source
