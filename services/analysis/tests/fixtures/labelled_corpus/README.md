# Labelled corpus (H.7) — **synthetic GSTs**

These 15 matches are **not** 15 real Riot games. They are hand-authored
`GameStateTimeline`s plus `expected.yaml` rule-id lists, used to compute
aggregate precision ≥ 0.8.

They do **not** mix unpaired `match.json` post-game stats with timeline GST.

| folder | intent | expected rule ids (non-suppressed) |
|---|---|---|
| S01_unseen_jungler | unseen jungler death | R-001 |
| S02_known_jungler | jungler seen 10s earlier (still unwarned forward death) | R-003 |
| S03_gold_death | 1600 gold at death | R-002 |
| S04_poor_gold_death | 200 gold at death | (none) |
| S05_cs_collapse | CS rate collapses after 2 deaths | R-005 |
| S06_cs_stable | deaths without CS collapse | (none) |
| S07_low_hp_gold | low HP + high gold in lane | R-006, R-007 |
| S08_healthy_gold | high gold, healthy HP | R-006 |
| S09_obj_noshow | far from enemy dragon, no trade | R-008 |
| S10_obj_trade | same but 2 plates taken | (none) |
| S11_no_antiheal | sustain enemies, no anti-heal | R-011 |
| S12_bought_antiheal | Oblivion Orb purchased | (none) |
| S13_fight_unknown | fight into fog, lost 2 | R-012 |
| S14_clean_lane | +CS at 14 with 0 deaths | P-001 |
| S15_recovered | −1500 gold then even by 25:00 | P-005 |

Builders live in `tests/helpers/h7_scenarios.py` (`LABELLED`). Precision counts
**non-suppressed** findings: `rule_id` in `expected.yaml` → TP, else FP.
