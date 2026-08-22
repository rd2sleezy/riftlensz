# Reference Parity (RP.0)

**Not C.8.** C.0–C.7 remain the coaching architecture. RP.x is a separate program for **behavioral parity** with leading League coaching products.

**Package:** `riftlens.coaching.parity` (schema `rp.0`)  
**CLI:** `python scripts/rp_parity.py {matrix|baseline|gaps|roadmap|sources}`  
**C.7:** kept. C.7 = coaching quality/safety. RP = “can RiftLens perform the specialized capability as well as the reference?”

## Verdict distinction

| Layer | Status |
| --- | --- |
| **RP.0 benchmark / registry infrastructure** | COMPLETE |
| **Capability implementation (wave, fight, CV, …)** | NOT STARTED (later RP tracks) |
| **HUMAN QUALITY VALIDATION** | NOT YET PERFORMED |
| **Independent expert validation of the Vladimir match** | NOT PERFORMED (pilot is `PILOT_SELF_REVIEW`) |

## What RP.0 is

1. Registry of public reference systems and evidence class (claim vs demonstrated).
2. Capability taxonomy with RiftLens READY / PARTIAL / BLOCKED / UNTESTED / REFERENCE_ONLY.
3. Required vs available vs missing inputs, and candidate upstream sources.
4. Parity dimensions and levels 0–5 (not a single score).
5. Anonymized first-real-match baseline cases.
6. Manual competitor-output ingestion seam (no scraping).
7. A recommended RP.1+ order with dependencies.

## What RP.0 is not

- Not production review, H.8, H.11, API, or UI.
- Not CV / OCR / wave engine / fight engine / VLM work.
- Not a replacement for C.7.
- Not a license to copy proprietary source, private APIs, or copyrighted coaching text.

## Laws

> If another coaching product can look at a League situation and produce a useful judgment that RiftLens cannot, that is a RiftLens parity gap.

> Vendor claims are not demonstrated capabilities.

> An external tool demonstrating a capability does not mean RiftLens has the evidence to reproduce it.

> Missing mappings print as gaps, not invented timestamps or invented vision.

> C.7 evaluates coaching quality/safety. RP evaluates specialized capability parity.

## Future pipeline

```
specialized perception/reasoning (later RP tracks)
        → C.1–C.6
        → C.7 safety/quality
        + RP parity benchmark
```

## Documents

| File | Contents |
| --- | --- |
| [reference-systems.md](./reference-systems.md) | Systems, claims, uncertainty |
| [capability-matrix.md](./capability-matrix.md) | Matrix + how to regenerate |
| [baseline-vladimir-match.md](./baseline-vladimir-match.md) | NA1_5620410094 pid 6 pilot |
| [evidence-source-map.md](./evidence-source-map.md) | Where missing inputs could come from |
| [rp-roadmap.md](./rp-roadmap.md) | RP.1+ dependencies and next track |

## Privacy

RP records must not store PUUID, summoner name, Riot account ids, API keys, or raw DTO dumps. Match id, participant id, champion, rule ids, and game timestamps are allowed.
