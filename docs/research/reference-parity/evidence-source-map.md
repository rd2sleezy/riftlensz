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
| Minion count | NO | NO | LIKELY | **PARTIAL (RP.1 short-bar candidates)** | PARTIAL | UNKNOWN | POSSIBLE | NO | RP.1 `MINION_CANDIDATE` on synthetic + local frames. Not wave-state. Real-replay precision TBD. |
| Minion HP | NO | NO | LIKELY | PARTIAL (bar fill) | PARTIAL | NO | POSSIBLE | NO | Fractional estimate only. |
| Wave position/direction | NO | NO | LIKELY | — | LIKELY | UNKNOWN | POSSIBLE | NO | Derived from minion tracks. CS delta ≠ wave. **Still missing (RP.2).** |
| Player HP at t | — | PROVEN ~60s | LIKELY | **PARTIAL (RP.1 HUD fraction)** | — | NO | POSSIBLE | POSSIBLE | Fractional HUD when green bar visible; else UNKNOWN. |
| Mana / resource | NO | NO | POSSIBLE | **PARTIAL / UNKNOWN** | — | NO | POSSIBLE | POSSIBLE | UNKNOWN when blue bar absent — never fabricated 0. |
| Dense champion positions | — | PROVEN ~60s | LIKELY bars | PARTIAL (V.2 via RP.1) | PARTIAL RP.1 tracks | POSSIBLE | POSSIBLE | NO | Identity-stable production tracks **not proven**. |
| True player vision | NO | NO | POSSIBLE | — | LIKELY if gated | POSSIBLE | POSSIBLE | NO | Omniscient timeline ≠ player knowledge. |
| Ward positions | — | NO position field (PROVEN gap) | POSSIBLE | POSSIBLE | — | POSSIBLE | POSSIBLE | NO | CURSOR.md: WARD_PLACED/KILL have no position. |
| Jungler last-seen | NO | omniscient ≠ last-seen | POSSIBLE | — | LIKELY | POSSIBLE | POSSIBLE | NO | Needs a visibility gate. |
| Cooldown state | summoner ids only | NO clocks | POSSIBLE | LIKELY HUD/scoreboard | — | NO | POSSIBLE | POSSIBLE | |
| Skillshot hit/miss | NO | NO | LIKELY | POSSIBLE | POSSIBLE | NO | POSSIBLE | NO | C.2 execution NOT_OBSERVABLE. |
| Replay seek | — | integer t_ms PROVEN | — | — | — | — | — | Replay API PROVEN | Navigation, not perception. |

**ROFL metadata:** identity/patch/duration/end stats — **not** live minions or fog.

**Manual annotation:** always PROVEN as a benchmark fallback; not a product perception path.

**Inference:** RP.1 (`riftlens.perception`) provides candidate bars/HUD/minimap ROI. Wave/fight/knowledge semantics remain later tracks.

See [rp1-perception.md](./rp1-perception.md).
