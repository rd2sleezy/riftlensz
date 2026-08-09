# rule_lab

```bash
cd /Users/rylanddunn/riftlens
PYTHONPATH=services/analysis python -m tools.rule_lab run --rule R-001 --matches cache --limit 200
```

Prints fire rate (% of matches), findings per firing match, severity histogram,
confidence histogram, and up to 10 random findings with full evidence dumps.

## Corpus (honest)

This repo’s committed Riot fixtures are **one unpaired match+timeline copied as A/B/C**.
The on-disk Riot cache (`~/.riftlens/cache`) may be empty. `rule_lab` **does not**
fabricate a 200-match live Riot crawl.

`--matches` sources:

| value | behavior |
|---|---|
| `cache` | Use paired match+timeline rows from the local Riot cache if present. If the cache is empty, **fall back to the synthetic corpus** and say so in the report `corpus` line. |
| `fixtures` | Committed `services/analysis/tests/fixtures/riot/NA1_fixture_*` GSTs (timeline-grounded; unpaired match.json is not mixed in as if it were the same game). |
| `synthetic` | Labelled H.7 scenarios + must-fire builders + quiet games with **diverse** durations/gold (not 3 identical copies). |
| `all` | cache, then fixtures, then synthetic, up to `--limit`. |

The 50% fire-rate gate is evaluated on the **synthetic diverse GST corpus** (labelled +
must-fire + quiet). A rule that fires on every quiet game is describing normal play.

How the synthetic fire-rate corpus is built: `riftlens.analysis.rules.lab._from_synthetic`
loads `tests/helpers/h7_scenarios.py` — 15 labelled stories, 25 must-fire stories, then
`quiet_game(n)` variants (duration and unspent gold jitter). All facts are authored GST,
not Riot JSON.
