# RP.1 — Rich Replay Perception Foundation

**Status:** COMPLETE (foundation)  
**Schema:** `rp1.0`  
**Package:** `riftlens.perception`  
**Not:** wave/fight/knowledge reasoning (RP.2–RP.6). Not C.8. Not production review.

## Architecture

```
R.10 capture dir / still image / synthetic RGB
        ↓
CapturedFrame (requested vs actual t_ms, timing_error_ms)
        ↓
ScreenGeometry + ROI map (resolution-relative)
        ↓
detectors (champion V.2 reuse, minion short-bar, HUD fractions, minimap ROI)
        ↓
short-window VisualTrack (trk_vis_####)
        ↓
RichReplayState  (gst_fact=false)
```

**GST ≠ VISUAL ≠ VISUAL_INFERRED.** Perception never writes GST facts.

Import direction: `perception → visual` / `domain`. Production and coaching must not import `perception`.

## Sensors (internal)

| Capability | Status | Evidence |
| --- | --- | --- |
| FRAME-CAPTURE | READY | CapturedFrame + timing error |
| HUD-REGION | PARTIAL | Resolution-relative ROIs |
| HP-FRACTION | PARTIAL | Green HUD column-fill when present |
| RESOURCE-FRACTION | PARTIAL / UNKNOWN | Blue bar when present; else UNKNOWN ≠ 0 |
| CHAMPION-CANDIDATE | PARTIAL | V.2 hybrid; identity unset |
| MINION-CANDIDATE | PARTIAL | Short bars formerly treated as noise |
| MINIMAP-ROI | PARTIAL | ROI + optional bright pips; no fog |
| TEMPORAL-TRACKING | PARTIAL | Local tracks; prefer split over merge |

**Not READY:** RP-CAP-WAVE-STATE, FIGHT-SELECTION, PLAYER-KNOWLEDGE (unchanged BLOCKED).

## Provenance rules

- Every field uses `OBSERVED | DERIVED_VISUAL | INFERRED_VISUAL | UNKNOWN | UNAVAILABLE`
- Source is `VISUAL` (or `VISUAL_INFERRED` only if later inference is added)
- Confidence 0..1; identity fields stay `None`
- Resource missing → `UNKNOWN`, never fabricated `0`

## Layouts

Supported: 320×180 – 3840×2160 with V.2-compatible fractional ROIs.  
Outside that range → `LayoutSupport.UNSUPPORTED` and UNKNOWN/UNAVAILABLE fields (no bad coordinates).

## How to inspect (local)

Match id alone cannot produce pixels. Capture a short R.10 window (or export a PNG), then:

```bash
cd services/analysis

# List baseline timestamps (no media)
python scripts/rp_perception.py baseline-manifest

# After you have an R.10 capture directory:
python scripts/rp_perception.py inspect \
  --capture-dir /path/to/r10_capture \
  --timestamp 1446000 \
  --debug

python scripts/rp_perception.py sequence \
  --capture-dir /path/to/r10_capture \
  --timestamp 1446000 \
  --pre-ms 3000 \
  --post-ms 3000 \
  --debug

# Or a still frame:
python scripts/rp_perception.py inspect --image /path/to/frame.png --timestamp 1446000
```

Debug artifacts: `~/.riftlens/rp/perception/` (outside git; refused under the repo).

## Vladimir baseline timestamps

`NA1_5620410094` pid 6 Vladimir TOP — see `baseline-manifest` and `docs/research/reference-parity/baseline-vladimir-match.md`.

Screenshots/video are **not** committed.

## What RP.2 can consume

- `minion_candidates[]` with screen/norm position, team_class, health_fraction, confidence  
- Still **missing** for wave reasoning: stable lane geometry, push direction, crash/bounce labels, exact counts validated on real replays

## What RP.3 can consume

- `champion_candidates[]` + `tracks[]` without identity  
- Still **missing**: participant binding, fight-time resources density, player-visible fog

## Remaining blockers

- Live seek→frame without a prior R.10 capture is out of this CLI (orchestration lives above `visual`/`perception` walls).
- Classical CV minion/champion bars are heuristics; high precision over recall.
- No VLM / paid API in RP.1.
