# V.3 — Real finding-window validation (Vladimir)

**Status:** complete (local research spike, not production)  
**Date:** 2026-08-12  
**Branch:** `r1-gameplay-source-domain`  
**Does not change coaching, overlay, R.10 capture internals, R/P rules, or H.6/H.8.**

V.3 asks whether the **existing** V.2 detector + V.1 tracker produce useful temporal observations on a **real** R.10 finding window — and whether a small classical continuity refinement is justified.

## Target replacement

The original Kaisa `NA1_5617764200` ~22:20 T4 was **abandoned because that replay was no longer practically available through League**, not because the visual architecture failed.

Replacement real-world T4:

| Field | Value |
|---|---|
| Replay | `NA1-5614479225.rofl` |
| Match | `NA1_5614479225` |
| Subject champion | Vladimir |
| Subject pid | **6** (resolved from MATCH-V5, not assumed) |
| Result | WIN · TOP · team 200 · **14/2/12** |
| Patch | `16.15.801.3452` |
| Queue | 420 |
| Duration | 1936 s |
| Match↔timeline paired | **True** |
| ROFL identity | `NA1` / `5614479225` (filename) |

### Participant table (MATCH-V5)

| pid | champ | role | team | result | K/D/A |
|---:|---|---|---:|---|---|
| 1 | Zaahen | TOP | 100 | L | 10/10/0 |
| 2 | Graves | JUNGLE | 100 | L | 6/9/6 |
| 3 | Malzahar | MIDDLE | 100 | L | 6/9/10 |
| 4 | Smolder | BOTTOM | 100 | L | 5/12/12 |
| 5 | Nautilus | UTILITY | 100 | L | 5/13/14 |
| **6** | **Vladimir** | **TOP** | **200** | **W** | **14/2/12** |
| 7 | Shaco | JUNGLE | 200 | W | 11/6/15 |
| 8 | Anivia | MIDDLE | 200 | W | 9/5/12 |
| 9 | Caitlyn | BOTTOM | 200 | W | 10/6/9 |
| 10 | Jax | UTILITY | 200 | W | 9/14/18 |

## Review

Built via production GST → metrics → rules → H.8 (`build_review_from_dtos`). No hand-authored findings.

| Field | Value |
|---|---|
| Review ID | `01KZT1SW9NH14W0EV3P60HPDND` |
| Vladimir pid | 6 |

**Focus**

| Item | Timestamps |
|---|---|
| Do not walk forward unwared | 15:03 (`903411`) |
| Spend tempo after a won fight | 25:10, 29:58 |
| Show up for objectives | 7:45 |

**Secondary:** none  

**Strength**

| Item | Timestamps |
|---|---|
| Keep your clean early lane | 14:00 |

**All findings**

| ID | Rule | t | Severity | Title |
|---|---|---|---|---|
| `01KZT1SVVWKMZHVZM8222ETZ1V` | R-008 | 7:45 | CRITICAL | Missed the objective without a trade |
| `01KZT1SVZCZFSHHFJEEH5PBBYH` | P-001 | 14:00 | LOW | Clean lane phase |
| `01KZT1SW2SRV24TZF5499AR0ER` | R-003 | **15:03** | HIGH | Died in the enemy half with no recent ward |
| `01KZT1SVXJB3S0EK8HJH7MDFMV` | R-014 | 25:10–25:35 | MEDIUM | Tempo wasted after a won fight |
| `01KZT1SVXYNTQ7D8TNAQBE6WZY` | R-014 | 29:58–30:23 | HIGH | Tempo wasted after a won fight |

## Selected V.3 finding

**R-003** `01KZT1SW2SRV24TZF5499AR0ER` — *Died in the enemy half with no recent ward* @ **15:03.411** (`903411`).

Why this finding (not because it makes RiftLens look correct):

- Concrete multi-second fight/death, not an end-game summary.
- Nearby GST kill sequence (Vladimir kills Nautilus @ 14:57, dies to Zaahen+Nautilus @ 15:03).
- Subject death enables conservative correlation testing.
- “No recent ward” is a nuanced claim: visual occupancy can add context without claiming fog/minimap.
- Avoided R-008 (objective/minimap-shaped) and late R-014 tempo conversion (harder to see in a short clip).

Planned window (12 s before + 15 s after): **GAME `891411–918411`** (14:51–15:18).

## Capture (real T4)

Windows/Vanguard blocked spawning `League of Legends.exe` from the agent (**Access is denied**). The user opened the replay manually. An earlier production `open_session` path shell-opened the `.rofl` and **killed** the running game client. `scripts/v3_finding_capture.py` was updated to **attach only** (`UserAssistedStrategy`, no shell-open/direct-exe) once the Replay API is reachable.

| Field | Value |
|---|---|
| Capture ID | `01KZT2ZK13TPZP72070CEC9DEF` |
| Media artifact | `01KZT30ZS5AX3K261QZDRXQY7K` (`clip_g891411.webm`) |
| Gameplay source | `01KZT26PMDZ984ZYEEM172KCVB` |
| ClockMap | `01KZT2ZK0QNDCKWKV4EATV7PVM` |
| GAME interval | `891411–918411` (14:51–15:18) |
| SOURCE interval | `891626–918626` |
| Clock | confidence **GOOD**, verified **true** |
| Camera controlled | **false** → `UNCONTROLLED` |
| Codec / fps (capture) | webm / 30 |

Clip not committed (policy).

## V.2 baseline (before any refinement)

Pipeline: existing V.2 hybrid detector → temporal confirm → **unchanged** V.1 tracker → GST align → R.11.

| Metric | Value |
|---|---:|
| Sample rate | 4 fps |
| Decoded / analyzed | 109 / 109 |
| Informative / uninformative | 109 / 0 |
| Raw / confirmed detections | 60 / 60 |
| Detections / frame | 0.55 |
| Total tracks | 8 |
| Stable tracks | 4 |
| Tracks ≥1 s | 2 |
| Tracks ≥3 s | 2 |
| One-frame tracks | 4 |
| Fragmented / ambiguous | 0 |
| Avg observations / track | 7.5 |
| Median duration | 250 ms |
| Peak stable in one frame | 2 |
| Team estimates (tracks) | **8 ENEMY** / 0 ALLY / 0 UNKNOWN |
| Extract / detect / track / align | 17.7 s / 23.7 s / 3 ms / 1 ms |
| Total analysis | **41.4 s** |
| CPU / GPU | local Windows CPU; no GPU |

### Subject correlation (baseline)

| Field | Value |
|---|---|
| Status | **LIKELY** |
| Track | `trk_0003` |
| Confidence | **0.55** (cap) |
| Method | `gst_death_alignment` |
| Reasons | unique disappearance within ~734 ms of GST subject death `903411`; capture ownership ignored; does not prove identity |

R.11 inferred frame: `Source.VISUAL_INFERRED` / `subject_track_correlation` at GAME `902677`.

Not CORRELATED: camera is uncontrolled; all track team estimates are ENEMY (spectator/HUD-relative color is unreliable here), so team+controlled-camera escalation correctly did not fire.

## Continuity refinement

**Not implemented.**

Justification: the real-clip baseline already meets V.3 success criteria without a tracker change.

- Detector precision is usable (0.55/frame; not V.1 chrome floods).
- Zero tracker-marked fragmented/ambiguous tracks.
- Subject death alignment produced an honest **LIKELY** on `trk_0003`.
- Remaining one-frame tracks are short flashes around a multi-champion fight, not a clear miss-grace defect.
- Forcing merges in this window would risk false identity joins.

Per the V.2→V.3 order: measure the real clip first; only then add body-texture/motion; only then consider ONNX. Classical continuity was **not** justified by this baseline.

## Temporal visual timeline (established only)

Direct VISUAL (not coaching language):

| GAME | Observation |
|---|---|
| 14:51 | Two champion-like tracks enter (`trk_0001`, `trk_0002`); both one-frame / leave by 14:53 |
| 14:51–15:01 | Sparse detections (gap) |
| 14:57 | **GST:** Vladimir (6) kills Nautilus (5) — not visual identity |
| 15:01 | Stable-ish track `trk_0003` enters |
| 15:03 | `trk_0003` lost; **GST:** Zaahen (1) kills Vladimir (6) |
| 15:04 | `trk_0003` left view; `trk_0004` enters and persists ~12 s |
| 15:05–15:06 | **GST:** Shaco kills Graves; Malzahar kills Jax |
| 15:08–15:18 | Additional shorter tracks enter/leave (`trk_0005`…`trk_0008`); `trk_0004` remains until ~15:16–15:18 |

Camera: all 109 samples `USEFUL`; coverage sufficient for research on this window. Uncontrolled → cannot infer reviewed-player camera ownership.

## GST alignment (verified from current DB)

| GAME | Killer | Victim | Subject role |
|---|---|---|---|
| 14:57.193 | 6 Vladimir | 5 Nautilus | killer |
| 15:03.411 | 1 Zaahen (+5) | **6 Vladimir** | **victim** |
| 15:05.381 | 7 Shaco | 2 Graves | — |
| 15:06.417 | 3 Malzahar (+2,+4) | 10 Jax | — |

GST not mutated.

## R-003 research classification (finding not mutated)

| Layer | Result |
|---|---|
| Overall | **PARTIALLY_SUPPORTED** |
| A. GST | Vladimir dies at 15:03 on a fight that includes his own kill 6 s earlier and further kills afterward. Compatible with a contested top-side fight; does **not** prove “no ward.” |
| B. Direct VISUAL | Champion-like occupancy before/around death; a track disappears near subject death; additional tracks appear after. Viewport was informative throughout. |
| C. VISUAL_INFERRED | Subject track **LIKELY** = `trk_0003` via death alignment (conf ≤ 0.55). |
| D. UNKNOWN | Ward placement/location, fog, minimap, exact champion IDs on screen, why team colors are all ENEMY, camera intent, whether death was “unwarded.” |

Visual context **adds** temporal occupancy and a candidate subject track beyond GST alone. It does **not** confirm or refute the ward claim. A nuanced finding remains nuanced — useful V.3 evidence, not a coaching rewrite.

## Case A vs Case B usefulness

Not classified. This window supports future work on “visible fight → subject dies while other tracks remain/enter,” but cannot distinguish bad engage vs failed disengage vs missing vision without minimap/fog/trajectory semantics (later phases).

## Performance

| Stage | Time |
|---|---|
| R.10 capture wall time | ~2 min attach+record (second attempt; first failed mid-record after API blip) |
| Decode (PyAV) | 17.7 s |
| V.2 detect | 23.7 s |
| Track | 3 ms |
| GST join | 1 ms |
| Total analyze | 41.4 s / 27 s clip @ 4 fps |

Plausible for research. No GPU.

## V.2 vs V.3 comparison

| | V.2 (18:30 unrelated) | V.3 (this 15:03 window) |
|---|---|---|
| Clip | Wrong finding window | **Exact R-003 window** |
| Subject corr | UNKNOWN | **LIKELY** |
| Dets/frame | 0.90 | 0.55 |
| Tracks | 14 | 8 |
| Continuity code | — | **none added** |
| Real finding utility | none | PARTIALLY_SUPPORTED research |

## Tests / lint

- `tests/unit/test_visual_v3.py` — finding selection, attach-only strategy, no forced continuity module
- Targeted V.0 / V.1 / V.2 / V.3 / R.11 / R.10: **98 passed**, 1 skipped
- Full `services/analysis` pytest: **521 passed**, 7 skipped, **1 failed** (pre-existing timing flake `test_engine_fixture_a_under_500ms`: 1463 ms vs 500 ms budget; not modified)
- ruff on V.3 files: pass
- mypy `--strict` `riftlens/visual`: pass
- lint-imports: **9 kept**

Gated env vars `RIFTLENS_R10_T4` / `RIFTLENS_V3_T4` unset for the full suite so real-machine capture tests did not fire.

## Recommendation for V.4 (do not implement)

Smallest next step based on this evidence:

1. **Team-color / spectator HUD calibration** — all tracks tagged ENEMY on a red-team subject is a detector semantics issue, not a tracker issue. Fix before more identity work.
2. Optional: short appearance/motion reassociation only if a future clip shows clear miss-grace fragmentation of a long subject track (not seen as the blocker here).
3. Do **not** jump to ONNX yet — real-clip subject LIKELY already works with V.2+V.1.
4. Minimap/fog still later; R-003’s ward claim specifically needs vision evidence V.3 correctly left UNKNOWN.

Do not start H.10 or R.12 from this spike.

## Limitations

- Manual replay open required (Vanguard blocks agent spawn of League).
- Attach-only research path; production launch chain can still disrupt a live replay if shell-open runs.
- First capture attempt failed with `REPLAY_API_UNAVAILABLE` mid-job; retry succeeded.
- Team estimates all ENEMY — not trustworthy for ally/enemy counts or CORRELATED escalation.
- No champion recognition; LIKELY ≠ proven Vladimir pixels.
- Ward/fog/minimap not analyzed.
- Clip/media not committed.

## Files

Created/updated:

- `scripts/v3_finding_capture.py` (Vladimir T4; attach-only session)
- `tests/unit/test_visual_v3.py`
- this report

Unchanged: V.0/V.1/V.2 detector/tracker core, coaching, overlay, R.10 capture internals, rules.
