# V.0 — Visual clip analysis proof of concept

**Status:** complete (local spike, not production)  
**Date:** 2026-08-11  
**Branch:** `r1-gameplay-source-domain`  
**Does not change coaching, overlay, R.10 capture, or H.6/H.7/H.8.**

V.0 asks whether a short R.10 `.webm` can be turned into trustworthy **R.11 temporal observations**. It does not coach.

## Approach

Staged local pipeline, no cloud VLMs:

1. Read R.10 `manifest.json` + clip path (no hardcoded replay path).
2. Sample frames with PyAV at **2 fps** (default).
3. Stamp each sample with `game_t_ms` and `source_t_ms` from the manifest start + decode offset.
4. Detect **horizontal saturated green/red health-bar-like regions** in a HUD-cropped viewport (OpenCV, already a service dependency).
5. Emit R.11 `FrameObservation` / `ObservationSequence`.
6. Print a research timeline and an R-012 diagnostic that **does not mutate findings**.

**Why 2 fps:** a 25 s clip yields 51 samples — enough to see occupancy change over seconds, cheap enough for a Windows CPU (~6 s total on this machine). 5 fps is available via `--fps`.

No new production dependencies. No Torch/ONNX/OCR/cloud APIs.

## Architecture

| Layer | Role |
|---|---|
| `riftlens.domain.observation` | R.11 contract (unchanged consumer) |
| `riftlens.visual` | V.0 spike: sample + detect + report |
| H.6 / H.7 / H.8 | untouched |

Import-linter: `visual spike isolation` forbids `analysis`, `coaching`, `pipeline`, `api`, `replay_host`, `gameplay`, and cloud SDKs. Domain/observation cannot import `riftlens.visual`.

Package is explicitly a spike (`analyzer_id=riftlens.visual.v0.healthbar`, `analyzer_version=v0.1`).

## Real clip

Not committed (policy: no large copyrighted replay media).

| Field | Value |
|---|---|
| Match | `NA1_5617764200` |
| Capture | `01KZQPZFMMZDR9DB4Y3NQ2ADSV` |
| Artifact | `01KZQQ09M8NHP1N06CCXAEJDAD` / `clip_g1110000.webm` |
| Gameplay source | `01KZMXVW4153FVKNXYRJWFM6YV` |
| ClockMap | `01KZMY2BN0GGHK7T6BCGH8Q6XS` |
| GAME interval | 18:30–18:55 (`1110000`–`1135000` ms) |
| SOURCE interval | `1110623`–`1135623` ms |
| `camera_controlled` | `false` → `UNCONTROLLED` |
| Sampling | 2 fps, 51/51 frames, no gaps |
| Extract | ~2.9 s |
| Analyze | ~3.3 s |
| Hardware | local Windows CPU (no GPU) |

Looked up by `--capture-id` under `%LOCALAPPDATA%\RiftLens\captures`. Replay `.rofl` path was not hardcoded.

This is the existing R.10 18:30–18:55 artifact. It is **not proven** to be the qualitative Kaisa fog-fight; that fight’s GST timestamp was not re-derived here. If it is a different play, V.0 still consumed a real capture and produced observations.

## What the analyzer established

- Clip decodes; every sample maps to integer GAME + SOURCE time.
- Viewport texture was informative on all 51 frames.
- Health-bar-like counts over time (tightened heuristic, noise-gated at >10):

| GAME | champion-like | ally-like | enemy-like |
|---|---:|---:|---:|
| 18:30 | 5 | 4 | 1 |
| 18:33 | 7–8 | 5–7 | 1–2 |
| 18:34–18:39 | 8–9 | 6–7 | 1–2 |
| 18:44–18:45 | 5 | 5 | 0 |
| 18:49–18:50 | 4 | 4 | 0 |
| 18:51 | 7–9 | 5 | 2–4 |
| 18:54 | 5 | 4 | 1 |

- Temporal change is real in the *detector output*: occupancy rises, falls, then rises again.
- Provenance is `Source.VISUAL`. HUD fields remain `UNKNOWN`. Minimap remains `UNKNOWN`.
- Subject visibility: **UNKNOWN**. Camera is uncontrolled; capture ownership ≠ Kaisa on screen.
- Champion / participant IDs: never set. `correlation_method=NONE`.

## What it could not establish (do not overclaim)

- **Not champion recognition.** “Ally-like” is green-bar color, not Blue team, not Kaisa.
- **Ally-like counts of 6–7 exceed five allies** → residual false positives (FX, UI, minions, duplicate bars). Counts are approximate occupancy, not a roster.
- **Not fog-of-war.** Off-camera ≠ unseen to the player. No minimap/vision OCR.
- **Not death/kill sequence, trajectory, or engage quality.**
- **Not proof that 18:30–18:55 is the R-012 fight.**
- OCR not attempted (would be unreliable for V.0).

## Visual vs R-012 (research only)

**Structured claim (R-012):** joined a fight with ≥2 enemies fogged, no numbers lead, lost ≥2. Copy: “You took a fight with {unknown} enemies fogged…”

**Visual diagnostic:** `PARTIALLY_SUPPORTED`

Meaning, narrowly:

- The clip is a usable gameplay viewport with changing health-bar-like occupancy.
- That is compatible with “more bodies entered the shot later,” which is one *possible* visual correlate of a later-rotation story.
- It does **not** confirm fogged enemies, a bad initial engage, or Kaisa overextending.
- It does **not** contradict R-012 either — the rule’s fog claim is invisible to this detector.

Future example (not production copy): if V.x later showed “two enemies visible early, two more enter after a won exchange, subject still in shot,” coaching could distinguish “fog engage” from “won the first 2v2 then overextended into rotators.” V.0 cannot make that distinction yet.

### Additional observations V.1 would need

- Subject identity / reviewed-champion track
- Deterministic or labeled camera target
- Kill/death/assist timing aligned to the same GAME clock (GST already has this — join, don’t replace)
- Reliable enemy-in-viewport vs fogged-to-player (minimap or vision state)
- Trajectory / whether the subject walked forward after the first exchange
- Lower false-positive entity detector (or a small local model)

## Performance / product envelope

| Metric | Result |
|---|---|
| Clip | 25 s, ~19 MB WebM |
| Samples | 51 @ 2 fps |
| Runtime | ~6 s CPU (decode + HSV bars) |
| Extra deps | none (uses existing `av`, `opencv-python-headless`, `numpy`) |
| GPU | not required |
| Cloud | not used |
| Memory | frame-at-a-time; no persistent frame dump |

Plausible as a future optional local feature if identity/false-positive quality improves. Not product-ready as a coaching input.

## Tests

Deterministic unit tests cover timestamp mapping, sampling cadence, missing/empty/malformed artifacts, synthetic bar detection, noise gate (>10 bars → UNKNOWN, no entities), R.11 round-trip, VISUAL provenance, UNKNOWN HUD, no RuleEngine import, and unchanged H.6 findings after importing the spike.

## Recommendation for V.1

1. Keep V.0’s **contract + sampling + provenance**; replace or heavily regularize the bar heuristic.
2. Add a **subject tracker** only with an explicit correlation method and the right to stay UNKNOWN.
3. Join GST kill timeline to the visual window before talking about “won then overextended.”
4. Do not wire visual evidence into R-012 (or any production rule) until fog vs off-camera is solved.
5. Capture the *finding’s* GAME window, not a convenient leftover 18:30 clip, when repeating T4.

V.1 should still be allowed to fail closed.
