# Replay Camera Control Spike (macOS)

**Status:** complete (research spike; not production)  
**Date:** 2026-08-14  
**Branch:** `integrate/ui-r1`  
**Spike path:** `spikes/replay_camera_control/`  
**Match / death:** `NA1_5620410094` · Vladimir pid 6 · `t_ms=839881`

## 1. Hypothesis

RiftLens can use Replay API `/replay/render` on macOS to place the camera over a GST death window so automated R.10 capture shows the fight/subject — not Directed Camera’s fountain default.

## 2. Observed Replay API render schema (Mac)

`GET /replay/render` returns a large object (extras allowed on `ReplayRender`). Camera-relevant keys observed:

| Field | Role |
|---|---|
| `cameraMode` | string mode (`top` / `path` / `fps` accepted on this client) |
| `cameraPosition` | `{x, y, z}` — **y is height**; ground plane is **x/z** |
| `cameraRotation` | `{x, y, z}` |
| `cameraAttached` | bool — attach/follow toggle |
| `selectionName` | string — subject/selection hook (not in League Director’s older field list; present on Mac) |
| `selectionOffset` | `{x,y,z}` |
| `cameraLockX/Y/Z`, `cameraMoveSpeed`, `cameraLookSpeed` | free-cam locks / speeds |
| `fieldOfView`, `fogOfWar`, interface/healthBar toggles | render chrome |

No OpenAPI enum document was reliably fetched from this client; modes were discovered by POST + GET readback.

Evidence: prior Mac probe sample + live spike readbacks in `spikes/replay_camera_control/artifacts/camera_spike_report.json`.

## 3. Camera modes tested

| Requested | Readback | Accepted |
|---|---|---|
| `top` | `top` | yes |
| `path` | `path` | yes |
| `fps` | `fps` | yes |
| `fpscam`, `free`, `directed`, `follow`, `attached`, `first`, … | not accepted / unchanged | no |

HUD still labels some sessions “Directed Camera” even when API `cameraMode` is `path` — treat HUD text as non-authoritative vs API readback.

## 4. Direct subject targeting

**No participant-id / entity-id follow field** was observed.

Available hooks:

- `selectionName` + `cameraAttached`
- Setting `selectionName="Vladimir"` **resolved to summoner** `immynator` with `cameraAttached=true` on readback
- Setting summoner name `immynator` likewise stuck
- Clearing selection was sticky/incomplete in one probe (`selectionName` remained after detach)

**Conclusion:** champion/summoner **name** targeting exists via `selectionName`; there is **no** GST `participant_id` → camera target API. Do not invent screen-space target mapping.

Attach+selection capture (strategy D) did not finish this run (Replay API died after prior encodes); targeting itself was API-proven in the probe phase.

## 5. World-coordinate control

GST death position (kill payload): **`(x=1591, y=9726)`**.

Mapping used (League Director convention):

```text
cameraPosition = { x: riot_x, y: height≈1910, z: riot_y }
```

| Patch | Mode after | Ground distance to death |
|---|---|---|
| `cameraPosition` only (mode stays `top`) | `top` | ~13127 (ignored) |
| `cameraMode=path` + position | `path` | **0.0** |
| `cameraMode=top` + position | `top` | ~13127 (Directed/top ignores manual position) |

**Finding:** world placement works **only in `path` mode** on this Mac client. `top` (Directed-like) owns the camera and discards manual position.

## 6. Directed Camera / `top` behavior

| Experiment | Result |
|---|---|
| Seek while `top` | Camera remains ~red fountain / far from death (~13k units) |
| Seek while `path` parked on GST death | Position **held** (distance 0) |
| Prior V.5 validation capture | Directed Camera on fountain → 1 detection |

Seeking under `top` does **not** reliably re-center on the subject. Path+GST position is deterministic; `top` is not.

Stabilization: ~0.3–1.5 s seek land + ~1 s render settle was enough for API readback; encode still benefits from re-applying render after capture’s internal seek (spike used a sticky client wrapper — **not** productionized).

## 7. Strategy comparison

| Strategy | Reliability | Determinism | Subject visibility | Complexity | Fit for R.10 |
|---|---|---|---|---|---|
| **A** Directed/`top` only | Poor | Low | Fountain / empty | Low | No |
| **B** Seek → wait → `top` | Poor (API flake mid-run) | Low | Same as A | Low | No |
| **C** Seek → `path` → GST position | **Good** | **High** | Fight on-screen; many tracks | Medium | **Best** |
| **D** `selectionName` + attach | API ok; capture unfinished | Medium | Likely strong when stable | Medium | Promising next |
| **E** path then `top` | Not fully captured | Low (`top` undoes path) | Weak | Medium | Avoid |

**Rank for automated capture:** C ≫ D (pending stable encode) ≫ A/B.

## 8. Primary real capture results (`839881`)

Window `829881–846881`. Identity ClockMap GOOD/verified.

| | Fountain baseline (V.5 val) | **C `path`+GST** | A `top` |
|---|---|---|---|
| Capture id | `01KZZAGC6QZ8FWB61KQYDX4VVY` | `camspike_01KZZBA8Y3VQ06YTAB4GTSJHH1` | `camspike_01KZZBH5TK01HK99AXF97FC37M` |
| Detections | 1 | **35** | 0 |
| Tracks | 1 | **5** | 0 |
| Longest track | 0 ms | **3266 ms** | 0 |
| USEFUL fraction | — | **1.0** (14/14 informative) | 1.0 frames but empty |
| V.4 | UNKNOWN | UNKNOWN | UNKNOWN |
| V.5 | UNKNOWN | UNKNOWN (`no_base_likely_track`) | UNKNOWN |
| Ground dist (API) | n/a | **0** | ~13126 |

Frame refs (small JPEGs, committed):  
`spikes/replay_camera_control/artifacts/frames/C_path_gst_position/frame_0000.jpg` — Vladimir visible in combat ~13:49.

V.4 stayed UNKNOWN because **no champion-like track disappeared near GST death** (death-time alignment insufficient) — identity problem, not camera emptiness. V.5 correctly refused to invent a LIKELY track.

## 9. Secondary death `1062798`

Not run: primary window already met the **camera usefulness** bar with strategy C; remaining strategies exhausted the Replay API process.

## 10. Camera quality metrics (C)

| Metric | Value |
|---|---|
| USEFUL fraction | 1.0 |
| Champion-like detections | 35 |
| Tracks | 5 |
| Longest track duration | 3266 ms |
| Subject candidate (V.4 track_id) | none |
| Fight visibly in-frame | yes (frames) |
| Stabilize after seek | ~1–2 s + sticky re-apply |
| Capture runtime | ~50–60 s wall for 17 s clip |

## 11. V.4 / V.5 downstream effect

Camera control unblocked **useful pixels** (35× detections vs fountain). Continuity cues still idle until V.4 produces a LIKELY base (death-aligned disappearance / subject track). That is the next research bottleneck — **not** “can we move the camera.”

## 12. macOS-specific findings

- `/replay/render` works with TLS Replay API after `EnableReplayApi`
- `selectionName` present on Mac (beyond older League Director field list)
- `path` + position is required; `top` ignores position
- Encode still writes `clip.webm.tmp` / API stalls (handled by prior R.10 harden)
- Capture’s internal seek can undo camera unless render is re-applied after seek (spike wrapper only)

## 13. Limitations

- No `participant_id` targeting
- Attach capture not completed this session (API loss)
- HUD “Directed Camera” label can disagree with API `cameraMode`
- Axis mapping assumed `riot.y → camera.z` (works at death coords; not exhaustively calibrated map-wide)
- Sticky re-apply is spike-only; production R.10 does not yet set `/replay/render`
- V.4/V.5 identity still UNKNOWN on this window

## 14. Final verdict

### `CAMERA_CONTROL_SUPPORTED`

Replay API-native camera control on macOS can place the camera over a GST death using **`cameraMode=path` + world `cameraPosition`**, and R.10 capture then yields materially better champion tracks than Directed/`top` fountain framing.

## 15. Recommended next implementation step

**Do not start V.6.** Optional follow-up (separate work order): a small production helper that, for capture only,

1. seeks with existing ClockMap / verified seek  
2. POSTs `/replay/render` `{cameraMode:"path", cameraAttached:false, cameraPosition: map(GST)}`  
3. re-applies after capture seek  
4. records `camera_controlled=true` + strategy in manifest provenance  

Then re-run V.4/V.5 on subject-visible windows. Attach/`selectionName` can be a second strategy behind path+GST.

## Files

- `spikes/replay_camera_control/run_spike.py`
- `spikes/replay_camera_control/resume_strategies.py`
- `spikes/replay_camera_control/coords.py`
- `spikes/replay_camera_control/tests/test_coords.py`
- `spikes/replay_camera_control/artifacts/camera_spike_report.json`
- `docs/architecture/replay-camera-control-spike-report.md` (this file)

No production camera policy changed. Large `.webm` not committed.
