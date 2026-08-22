# Evidence source map

Conservative labels: **PROVEN / LIKELY / POSSIBLE / UNKNOWN / NO**.

Authoritative table:

```bash
cd services/analysis
python scripts/rp_parity.py sources
```

## Highlights (highest-priority missing inputs)

| Input | Riot MATCH | Riot timeline | Video frames | CV/OCR | Tracking | Minimap | VLM | Live Client | Notes |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| Minion count | NO | NO | LIKELY | LIKELY detect | LIKELY | UNKNOWN | POSSIBLE | NO | V.0–V.2 treated minion-sized bars as noise. Dedicated detector required. |
| Minion HP | NO | NO | LIKELY | LIKELY if detected | LIKELY | NO | POSSIBLE | NO | |
| Wave position/direction | NO | NO | LIKELY | — | LIKELY | UNKNOWN | POSSIBLE | NO | Derived from minion tracks. CS delta ≠ wave. |
| Player HP at t | — | PROVEN ~60s | LIKELY | LIKELY HUD | — | NO | POSSIBLE | POSSIBLE | R.0: `/liveclientdata/activeplayer` HTTP 400 in replay. Do not assume activeplayer HP. |
| Mana / resource | NO | NO | POSSIBLE | LIKELY HUD | — | NO | POSSIBLE | POSSIBLE | Absent from production GST frames used today. |
| Dense champion positions | — | PROVEN ~60s + interpolation (omniscient) | LIKELY bars | LIKELY | LIKELY V.1–V.6 spike | POSSIBLE | POSSIBLE | NO | Identity-stable production tracks **not proven**. |
| True player vision | NO | NO | POSSIBLE | — | LIKELY if gated | POSSIBLE | POSSIBLE | NO | Omniscient timeline ≠ player knowledge. |
| Ward positions | — | NO position field (PROVEN gap) | POSSIBLE | POSSIBLE | — | POSSIBLE | POSSIBLE | NO | CURSOR.md: WARD_PLACED/KILL have no position. |
| Jungler last-seen | NO | omniscient ≠ last-seen | POSSIBLE | — | LIKELY | POSSIBLE | POSSIBLE | NO | Needs a visibility gate. |
| Cooldown state | summoner ids only | NO clocks | POSSIBLE | LIKELY HUD/scoreboard | — | NO | POSSIBLE | POSSIBLE | |
| Skillshot hit/miss | NO | NO | LIKELY | POSSIBLE | POSSIBLE | NO | POSSIBLE | NO | C.2 execution NOT_OBSERVABLE. |
| Replay seek | — | integer t_ms PROVEN | — | — | — | — | — | Replay API PROVEN | Navigation, not perception. |

**ROFL metadata:** identity/patch/duration/end stats — **not** live minions or fog.

**Manual annotation:** always PROVEN as a benchmark fallback; not a product perception path.

**Inference:** a shared RP.1 perception layer is the dependency for wave, fight-time resources, and (later) vision. Do not implement those detectors in RP.0.
