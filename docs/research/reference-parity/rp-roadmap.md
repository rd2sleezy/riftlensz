# RP roadmap

**Do not start RP.1 from this document automatically.** RP.0 only recommends.

```bash
cd services/analysis
python scripts/rp_parity.py roadmap
python scripts/rp_parity.py gaps
```

## Aggressive priority rule

HIGH when: (1) strong reference tools claim/do it, (2) RiftLens cannot, (3) it materially improves coaching, (4) the Vladimir pilot exposed it, (5) it unlocks downstream concepts.

Cosmetic copy and easy UI are out of scope until those intelligence gaps move.

## Recommended order (dependency-adjusted)

The work-order sketch listed Tempo as RP.4 and Player-knowledge as RP.5. **Architecture + baseline evidence change that.**

31:24 fails because the detector uses the **wrong reason** (unaccounted vs knowingly 1v3). That is a player-knowledge / fight-selection problem, not a tempo problem. Tempo/objective work (7:07, 24:00, conversion) **depends on wave + fight context**.

| Track | Name | Depends on | Why this slot |
| --- | --- | --- | --- |
| **RP.1** | Rich Replay Perception Foundation | — | Shared upstream. Minions, dense champions, HUD resources are not in MATCH-V5. |
| **RP.2** | Wave + Recall Intelligence | RP.1 | Conversion PARTLY because pushing waves *was* conversion. Unlock recall/roam cost. Chain: minion perception → tracking → lane geometry → wave-state → wave-action. |
| **RP.3** | Fight Context + Fight Selection | RP.1 | Primary human lesson: commitment discipline. Chain: positions → resources → identity → temporal tracking → local numbers → decision reasoning. |
| **RP.4** | Player Knowledge + Vision + Jungle | RP.1, RP.3 | Distinguishes 24:28 true fog from 31:24 known 1v3. A minimal last-seen model should land *with* fight selection, not after tempo. |
| **RP.5** | Tempo + Objective Decision | RP.2, RP.3 | Presence/roam heuristics without contestability, priority, phase, wave cost. |
| **RP.6** | Mechanics + Cooldowns + Resources | RP.1 | High middiff-like value; not the pilot’s primary lesson. HUD/LCD can densify resources first. |
| **RP.7** | Longitudinal / RP evaluation expansion | RP.2–RP.4 | Same-case competitor/human refs. **Keep C.7.** |

## Exactly one next track

**RP.1 — Rich Replay Perception Foundation.**

Not: wave engine, fight engine, OCR productization, or VLM integration as a coaching path. Those are later tracks that consume RP.1 outputs.

## Acceptance (provisional)

A capability is **not** READY because a demo worked once, one real match looked correct, a vendor claims something similar, or synthetic tests passed.

READY (provisional) requires: deterministic tests, curated edge cases, real replay cases, no epistemic regressions, human adjudication when the judgment is strategic.

REFERENCE-COMPARABLE (provisional) requires: same-case comparisons, competitor or human reference, acceptable agreement, no severe false-confidence.

Sample-size N is **not** invented in RP.0.
