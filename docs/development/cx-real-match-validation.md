# C.x real-match validation harness (developer only)

**Not a new C.x phase.** C.0–C.7 remain unchanged. This harness does **not** wire C.x into production H.8/H.11.

**Warning:** C.x output is experimental. **HUMAN QUALITY VALIDATION has NOT been performed.**

## Purpose

Run one real Riot match through:

GST + Finding[] → C.1 → C.2 → C.3 → C.4 → C.5 → human-readable report

Optional: single-game C.6 inspection and C.7 automated structural checks.

## Commands

From `services/analysis` (venv active):

```bash
python scripts/cx_run_real_match.py \
  --match-id '<PLATFORM_MATCH_ID>' \
  --pid <PARTICIPANT_ID>
```

With optional longitudinal + structural checks:

```bash
python scripts/cx_run_real_match.py \
  --match-id '<PLATFORM_MATCH_ID>' \
  --pid <PARTICIPANT_ID> \
  --include-c6 \
  --include-c7
```

JSON to stdout and/or safe out path (must be **outside** the git repo):

```bash
python scripts/cx_run_real_match.py \
  --match-id '<PLATFORM_MATCH_ID>' \
  --pid <PARTICIPANT_ID> \
  --json \
  --out ~/.riftlens/cx_validation/last.json
```

## How inputs are obtained

1. `ensure_match_ingested(match_id)` — reads Riot forever-cache when present; otherwise fetches MATCH-V5 + timeline (requires API key) and may write cache + match DB rows.
2. `build_review_from_dtos(..., persist=False)` — builds GST, runs RuleEngine findings, H.8 review assembly **without** writing review presentation/coaching persistence.
3. Bundled `PatchDataProvider().load_bundled(gst.patch)` when available.
4. Pure `run_cx_pipeline(gst, findings, pid)` for C.1–C.5 (+ optional C.6/C.7).

## Expected stdout sections

- Top summary banner (match / pid / episode & lesson counts / primary teaching / C.7 status)
- `## C.1 Episodes`
- `## C.2 Interpretations`
- `## C.3 Lesson Candidates` + capability readiness (BLOCKED surfaced)
- `## C.4 Prioritization` (MAJOR / SECONDARY / STRENGTHS / WITHHELD)
- `## C.5 Teaching` (via `render_teaching_lesson_set`)
- Optional C.6 / C.7 sections

Zero findings is a valid clean result (0 episodes / 0 majors).

## Privacy

Does **not** print PUUID, summoner names, Riot account ids, API keys, or raw Riot DTOs.

`--out` **refuses** paths under the repository root. Prefer `~/.riftlens/...` or `/tmp/...`.

Never commit real match JSON outputs.

## Persistence / cache side effects

| Action | Side effect |
| --- | --- |
| Cache hit | Read-only cache |
| Cache miss | Writes forever-cache + may upsert match/timeline in local SQLite |
| Harness review build | `persist=False` — no review presentation / coaching item write |
| C.x pipeline | In-memory only |

## Known limitations

- Single-game C.6 adapter is marked `C6_SINGLE_GAME_ADAPTER_PARTIAL` (no invented opportunity denominators).
- C.7 automated PASS ≠ coaching quality validated.
- Unpaired fixtures / sparse findings may yield empty teaching — that is informative, not a crash.
- Not available from ReviewScreen / production API.
