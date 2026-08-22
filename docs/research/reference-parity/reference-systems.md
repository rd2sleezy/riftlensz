# Reference systems

**Statement kinds:** vendor claim · observed (in this repo) · human judgment · inference.

No competitor internals are claimed. Public product behavior and C.3/C.6 generic analogs are the only sources used here. Cells in the matrix are derived: a `VENDOR_CLAIM` **cannot** serialize as `DEMONSTRATED`.

| system_id | Display | Kind | Evidence posture | Uncertainty |
| --- | --- | --- | --- | --- |
| middiff | middiff | replay coaching | Vendor claim | Timestamped replay + per-minion / skillshot / vision claims are **not** independently verified in-repo. |
| questie | Questie | screen understanding | Vendor claim | Wave, recall, positions, map, resources, vision, combat — **claims**, no captured output in-repo. |
| hakko | Hakko | live overlay | Vendor claim | Minion/wave, minimap/jungle, scoreboard, recall, memory — **claims**, no captured output. |
| replays_lol | Replays.lol | recording / review | Vendor claim | Auto-record, key moments, navigation, event labels. Coaching depth **unknown**. |
| trenix | Trenix | longitudinal review | Vendor claim (+ C.6 analog) | C.6 documents *Trenix-like* multi-game priority as a generic style, **not** a teardown. |
| mobalytics | Mobalytics | skill profile | Vendor claim (+ C.6 analog) | C.6 documents *Mobalytics-like* persistent focus. Not a teardown. |
| itero | iTero | macro trends | Vendor claim (+ C.6 analog) | C.6 documents *iTero-like* process tracking. Not a teardown. |
| skill_capped | Skill Capped | curriculum | Vendor claim | High-quality principles/curriculum. Teaching reference, not a perception engine we can audit. |
| human_coach | Metafy / human VOD coaching | human reference | Human reference | Humans demonstrably do intent, alternatives, decision quality, cues, and plans. Quality varies by coach. |

## Catalogued public capability themes (vendor claim unless noted)

**middiff (vendor claim):** timestamped replay coaching; per-minion / missed-CS; skillshot outcomes; cooldown/mana/item/buff claims; player-vision reconstruction claim; longitudinal one-habit focus.

**Questie (vendor claim):** screen understanding; wave management; recalls; visible positions; map state; resources/inventory; vision; combat/positioning.

**Hakko (vendor claim):** minion position/health/wave-state; minimap/jungle tracking; scoreboard/summoner tracking; recall coaching; persistent memory.

**Replays.lol (vendor claim):** automatic recording; key replay moments; instant review navigation; broad event labels.

**Trenix (vendor claim):** cross-game patterns; key moments; post-game structured review; next-game priorities.

**Mobalytics (vendor claim):** role-aware skill profiling; persistent strengths/weaknesses; skill-to-focus.

**iTero (vendor claim):** recurring macro patterns; process trend analysis; historical behavioral focus.

**Skill Capped (vendor claim):** concept/reference curriculum; role/champion-specific principles.

**Human coach (human reference):** player intent; reasoning; counterfactual alternatives; why a decision was good/bad; cue and improvement plan.

Registry updates belong in `riftlens.coaching.parity.references` so the CLI matrix stays the source of generated truth.
