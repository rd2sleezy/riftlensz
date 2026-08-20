"""C.1 snapshot and gap helpers over GST. Interpolation follows GST policy only."""

from __future__ import annotations

from riftlens.analysis.features._query import facts_for, subject
from riftlens.analysis.features.gold import unspent_gold
from riftlens.analysis.features.health import hp_fraction
from riftlens.coaching.context.grouping import TemporalCluster
from riftlens.coaching.context.models import (
    ContextGap,
    ContextGapStatus,
    ContextOrigin,
    ContextualValue,
    ParticipantStateSample,
    SnapshotPoint,
)
from riftlens.domain.enums import FactKind, Source
from riftlens.domain.estimate import Estimate
from riftlens.domain.geometry import Point, zone_of
from riftlens.domain.ports import PatchData
from riftlens.domain.timeline import GameStateTimeline, ParticipantSnapshot


def build_samples(
    gst: GameStateTimeline,
    pid: int,
    cluster: TemporalCluster,
    stamps: tuple[int, ...],
    patch: PatchData | None,
) -> tuple[ParticipantStateSample, ...]:
    """Return BEFORE / ANCHOR / AFTER samples for the reviewed participant."""
    points: list[tuple[SnapshotPoint, int]] = [
        (SnapshotPoint.BEFORE, cluster.start_ms),
        *((SnapshotPoint.ANCHOR, stamp) for stamp in stamps),
        (SnapshotPoint.AFTER, cluster.end_ms),
    ]
    if pid not in gst.participants:
        return ()
    return tuple(_one_sample(gst, pid, point, t_ms, patch) for point, t_ms in points)


def build_gaps(
    gst: GameStateTimeline,
    pid: int,
    cluster: TemporalCluster,
    stamps: tuple[int, ...],
    patch: PatchData | None,
) -> tuple[ContextGap, ...]:
    """Return structural plus inspection-based context gaps. Missing stays missing."""
    rows = [
        ContextGap(
            "true_fog",
            ContextGapStatus.UNAVAILABLE,
            "GST has no fog-of-war field; C.1 does not infer fog from info_age or off-camera.",
        ),
        ContextGap(
            "ward_map",
            ContextGapStatus.UNAVAILABLE,
            "WARD_PLACED/WARD_KILL events have no position in Riot timeline payloads.",
        ),
        ContextGap(
            "continuous_movement",
            ContextGapStatus.COARSE,
            "Participant positions are 60s timeline frames plus GST interpolation policy.",
        ),
        ContextGap(
            "wave_state",
            ContextGapStatus.UNAVAILABLE,
            "No explicit wave-state feature exists on GST; C.1 does not invent one.",
        ),
        ContextGap(
            "visual_observations",
            ContextGapStatus.UNAVAILABLE,
            "C.1 does not consume visual FrameObservation objects.",
        ),
    ]
    if not _has_summoner_loadout(gst, pid):
        rows.append(
            ContextGap(
                "summoner_state",
                ContextGapStatus.UNAVAILABLE,
                "Production GST does not write summoner_loadout derived facts.",
            )
        )
    if patch is None:
        rows.append(
            ContextGap(
                "unspent_gold",
                ContextGapStatus.UNKNOWN,
                "PatchData was not provided; unspent gold was not reconstructed.",
            )
        )
        rows.append(
            ContextGap(
                "player_alive",
                ContextGapStatus.UNKNOWN,
                "PatchData was not provided; respawn windows were not modelled.",
            )
        )
    query_times = (cluster.start_ms, cluster.end_ms, *stamps)
    if any(_position_is_coarse(gst, pid, t_ms) for t_ms in query_times):
        rows.append(
            ContextGap(
                "position_precision",
                ContextGapStatus.COARSE,
                "At least one sample is off a 60s POSITION frame, so coordinates are interpolated.",
            )
        )
    return tuple(rows)


def _one_sample(
    gst: GameStateTimeline,
    pid: int,
    point: SnapshotPoint,
    t_ms: int,
    patch: PatchData | None,
) -> ParticipantStateSample:
    snap = gst.at(t_ms).participants.get(pid)
    pos_x, pos_y, zone = _position_fields(gst, pid, t_ms)
    return ParticipantStateSample(
        point=point,
        t_ms=t_ms,
        participant_id=pid,
        phase=gst.phase(t_ms),
        level=_estimate_int(snap.level if snap else None, t_ms, "level"),
        xp=_estimate_int(snap.xp if snap else None, t_ms, "xp"),
        current_gold=_frame_numeric(gst, pid, FactKind.GOLD, "currentGold", t_ms),
        total_gold=_frame_numeric(gst, pid, FactKind.GOLD, "totalGold", t_ms),
        unspent_gold=_unspent(gst, pid, t_ms, patch),
        cs=_estimate_int(snap.cs if snap else None, t_ms, "cs"),
        hp_fraction=_hp(gst, pid, t_ms, patch, snap),
        position_x=pos_x,
        position_y=pos_y,
        zone=zone,
        alive=_alive(gst, pid, t_ms, patch),
    )


def _estimate_int(estimate: Estimate[int] | None, t_ms: int, label: str) -> ContextualValue | None:
    if estimate is None:
        return None
    exact = f"at t={t_ms}" in estimate.basis and f"queried t={t_ms}" in estimate.basis
    origin = ContextOrigin.GST_FACT if exact else ContextOrigin.GST_DERIVED
    return ContextualValue(
        value=int(estimate.value),
        origin=origin,
        source=Source.RIOT_TIMELINE,
        confidence=estimate.confidence,
        basis=estimate.basis or label,
        t_ms=t_ms,
        exact=exact,
    )


def _frame_numeric(
    gst: GameStateTimeline, pid: int, kind: FactKind, key: str, t_ms: int
) -> ContextualValue | None:
    before = [item for item in facts_for(gst, kind, pid) if item.t_ms <= t_ms]
    if not before:
        return None
    fact = before[-1]
    raw = fact.payload.get(key)
    if isinstance(raw, bool) or not isinstance(raw, int | float):
        return None
    exact = fact.t_ms == t_ms
    return ContextualValue(
        value=int(raw),
        origin=ContextOrigin.GST_FACT if exact else ContextOrigin.GST_DERIVED,
        source=fact.source,
        confidence=fact.confidence,
        basis=f"{key} from {kind.value} t={fact.t_ms} queried t={t_ms}",
        t_ms=fact.t_ms,
        exact=exact,
    )


def _unspent(
    gst: GameStateTimeline, pid: int, t_ms: int, patch: PatchData | None
) -> ContextualValue | None:
    if patch is None:
        return None
    estimate = unspent_gold(gst, pid, t_ms, patch)
    exact = estimate.confidence >= 1.0 and f"t={t_ms}" in estimate.basis
    return ContextualValue(
        value=int(estimate.value),
        origin=ContextOrigin.FEATURE,
        source=Source.DERIVED,
        confidence=estimate.confidence,
        basis=estimate.basis,
        t_ms=t_ms,
        exact=exact,
    )


def _hp(
    gst: GameStateTimeline,
    pid: int,
    t_ms: int,
    patch: PatchData | None,
    snap: ParticipantSnapshot | None,
) -> ContextualValue | None:
    if patch is not None:
        estimate = hp_fraction(gst, pid, t_ms, patch)
        exact = estimate.confidence >= 1.0 and f"t={t_ms}" in estimate.basis
        return ContextualValue(
            value=float(estimate.value),
            origin=ContextOrigin.FEATURE,
            source=Source.DERIVED,
            confidence=estimate.confidence,
            basis=estimate.basis,
            t_ms=t_ms,
            exact=exact,
        )
    if snap is None or snap.health is None or snap.health_max is None:
        return None
    maximum = snap.health_max.value
    if maximum <= 0:
        return None
    return ContextualValue(
        value=float(snap.health.value) / float(maximum),
        origin=ContextOrigin.GST_DERIVED,
        source=Source.RIOT_TIMELINE,
        confidence=min(snap.health.confidence, snap.health_max.confidence),
        basis="last HEALTH frame ratio; healthRegen not applied",
        t_ms=t_ms,
        exact=False,
    )


def _position_fields(
    gst: GameStateTimeline, pid: int, t_ms: int
) -> tuple[ContextualValue | None, ContextualValue | None, ContextualValue | None]:
    try:
        estimate = gst.interpolate_position(pid, t_ms)
    except KeyError:
        return None, None, None
    if estimate.confidence <= 0 or estimate.basis == "no position facts":
        return None, None, None
    point = estimate.value
    exact = estimate.confidence >= 1.0 and estimate.basis.startswith("participant frame")
    origin = ContextOrigin.GST_FACT if exact else ContextOrigin.GST_DERIVED
    shared = ContextualValue(
        value=point.x,
        origin=origin,
        source=Source.RIOT_TIMELINE,
        confidence=estimate.confidence,
        basis=estimate.basis,
        t_ms=t_ms,
        exact=exact,
    )
    zone = zone_of(Point(point.x, point.y))
    y_value = ContextualValue(
        value=point.y,
        origin=origin,
        source=Source.RIOT_TIMELINE,
        confidence=estimate.confidence,
        basis=estimate.basis,
        t_ms=t_ms,
        exact=exact,
    )
    zone_value = ContextualValue(
        value=zone.value,
        origin=origin,
        source=Source.RIOT_TIMELINE,
        confidence=estimate.confidence,
        basis=estimate.basis,
        t_ms=t_ms,
        exact=exact,
    )
    return shared, y_value, zone_value


def _alive(
    gst: GameStateTimeline, pid: int, t_ms: int, patch: PatchData | None
) -> ContextualValue | None:
    if patch is None:
        return None
    living = True
    basis = "no CHAMPION_KILL as victim at or before t_ms"
    confidence = 0.85
    for death in gst.facts(kind=FactKind.CHAMPION_KILL):
        if death.payload.get("victimId") != pid or death.t_ms > t_ms:
            continue
        level_fact = gst.nearest(FactKind.LEVEL, death.t_ms, "before", subject=subject(pid))
        level = int(level_fact.payload.get("level") or 1) if level_fact else 1
        respawn = patch.respawn_ms(level, death.t_ms)
        living, basis, confidence = _apply_respawn(
            t_ms, death.t_ms, respawn, living, basis, confidence
        )
    return ContextualValue(
        value=living,
        origin=ContextOrigin.INFERENCE,
        source=Source.DERIVED,
        confidence=confidence,
        basis=basis,
        t_ms=t_ms,
        exact=False,
    )


def _apply_respawn(
    t_ms: int,
    death_ms: int,
    respawn: int | None,
    living: bool,
    basis: str,
    confidence: float,
) -> tuple[bool, str, float]:
    if respawn is None:
        if t_ms - death_ms < 10_000:
            return False, "death within 10s; PatchData.respawn_ms unavailable", 0.4
        return living, basis, confidence
    if death_ms <= t_ms < death_ms + respawn:
        return False, f"respawn window {respawn}ms after death t={death_ms}", 0.75
    return living, basis, confidence


def _has_summoner_loadout(gst: GameStateTimeline, pid: int) -> bool:
    for item in facts_for(gst, FactKind.DERIVED, pid):
        payload = item.payload
        if payload.get("kind") == "summoner_loadout" or "summoner1Id" in payload:
            return True
    return False


def _position_is_coarse(gst: GameStateTimeline, pid: int, t_ms: int) -> bool:
    if pid not in gst.participants:
        return False
    estimate = gst.interpolate_position(pid, t_ms)
    if estimate.confidence <= 0:
        return False
    return not (estimate.confidence >= 1.0 and estimate.basis.startswith("participant frame"))
