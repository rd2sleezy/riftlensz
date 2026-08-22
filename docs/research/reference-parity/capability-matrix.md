# Capability matrix

Regenerate from code (authoritative):

```bash
cd services/analysis
python scripts/rp_parity.py matrix
```

Vocabulary:

| Cell | Meaning |
| --- | --- |
| DEMONSTRATED | Publicly verified in our evidence class (or human-reference FULL). |
| CLAIMED | Vendor claim of coverage. **Never** upgraded from VENDOR_CLAIM. |
| PARTIAL | Partial coverage (claim or demonstrated). |
| UNKNOWN | Insufficient project knowledge. |
| N/A | Not applicable to that product. |

RiftLens column uses `READY | PARTIAL | BLOCKED | UNTESTED | REFERENCE_ONLY` from the capability registry, aligned with C.3 GST evidence — not with marketing.

## RiftLens today (registry)

| Capability | RiftLens | Primary blocker | Track |
| --- | --- | --- | --- |
| RP-CAP-WAVE-STATE | BLOCKED | No minion-level GST; MATCH-V5 has no wave geometry | RP.2 ← RP.1 |
| RP-CAP-WAVE-ACTION | BLOCKED | Requires wave state | RP.2 |
| RP-CAP-RECALL | PARTIAL | Gold/HP/purchase without wave-dependent recall | RP.2 |
| RP-CAP-FIGHT-CONTEXT | PARTIAL | ~60s positions; no production identity-stable tracks | RP.3 ← RP.1 |
| RP-CAP-FIGHT-SELECTION | BLOCKED | Cannot split unaccounted vs knowingly outnumbered | RP.3 |
| RP-CAP-PLAYER-KNOWLEDGE | BLOCKED | No true fog in Riot timeline | RP.4 |
| RP-CAP-JUNGLE-INFORMATION | BLOCKED | No player-vision / last-seen proof | RP.4 |
| RP-CAP-VISION | BLOCKED | Ward events have no positions | RP.4 |
| RP-CAP-RESOURCE-STATE | PARTIAL | HP/gold/xp at ~60s; mana/buffs absent | RP.6 |
| RP-CAP-COOLDOWNS | BLOCKED | No cooldown/cast timeline in GST | RP.6 |
| RP-CAP-MECHANICS | BLOCKED | C.2 execution NOT_OBSERVABLE | RP.6 |
| RP-CAP-TEMPO-CONVERSION | PARTIAL | R-014 exists; cannot judge wave push-out as conversion | RP.5 |
| RP-CAP-OBJECTIVE-DECISION | PARTIAL | Presence ≠ contestability/priority/cost | RP.5 |
| RP-CAP-ROAM | PARTIAL | Missing phase/urgency/wave cost | RP.5 |
| RP-CAP-LANE-PERFORMANCE | PARTIAL | CS/deaths exist; not per-minion or trade quality | RP.2 |
| RP-CAP-ITEMIZATION | PARTIAL | Purchase events; weak situational eval | RP.6 |
| RP-CAP-LONGITUDINAL | PARTIAL | C.6 engine exists; not production-wired | RP.7 |
| RP-CAP-HUMAN-DECISION-REASONING | PARTIAL | C.2/C.5 scaffold; fight decisions often UNKNOWN | RP.7 |
| RP-CAP-REPLAY-NAVIGATION | PARTIAL | Seek works; auto key-moments are a vendor claim elsewhere | R-series |

Full competitor columns: `python scripts/rp_parity.py matrix`.
