# RP roadmap

**RP.0 COMPLETE.** **RP.1 COMPLETE** (perception foundation). Do not auto-start RP.2/RP.3.

```bash
cd services/analysis
python scripts/rp_parity.py roadmap
python scripts/rp_parity.py gaps
python scripts/rp_perception.py audit
```

## Aggressive priority rule

HIGH when: (1) strong reference tools claim/do it, (2) RiftLens cannot, (3) it materially improves coaching, (4) the Vladimir pilot exposed it, (5) it unlocks downstream concepts.

## Order

| Track | Name | Depends on | Status |
| --- | --- | --- | --- |
| **RP.1** | Rich Replay Perception Foundation | — | **COMPLETE** (`riftlens.perception`) |
| **RP.2** | Wave + Recall Intelligence | RP.1 | NEXT — minion candidates exist; wave-state reasoning does not |
| **RP.3** | Fight Context + Fight Selection | RP.1 | NEXT — champion candidates/tracks exist; identity + knowledge do not |
| **RP.4** | Player Knowledge + Vision + Jungle | RP.1, RP.3 | Later |
| **RP.5** | Tempo + Objective Decision | RP.2, RP.3 | Later |
| **RP.6** | Mechanics + Cooldowns + Resources | RP.1 | Ability/item ROIs exist; cooldown OCR later |
| **RP.7** | Longitudinal / RP evaluation expansion | RP.2–RP.4 | Keep C.7 |

## Exactly one next track

Prefer **RP.2 Wave + Recall** when prioritizing Vladimir conversion / wave blockers.

Prefer **RP.3 Fight Context + Selection** when prioritizing 31:24 wrong-reason / commitment.

RP.2 and RP.3 are **partially parallelizable** on RP.1 interfaces; both still need real-replay labeling.

Details: [rp1-perception.md](./rp1-perception.md)
