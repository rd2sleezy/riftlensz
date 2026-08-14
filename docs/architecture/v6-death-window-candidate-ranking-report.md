# V.6 death-window candidate ranking report

**Status:** complete (research spike; not wired to coaching/rules/review/overlay)  
**Date:** 2026-08-14  
**Branch:** `integrate/ui-r1`  
**Modules:** `riftlens/visual/death_candidate.py`, `correlate_v6.py`, `v6_analyze.py`  
**Match / subject / death:** `NA1_5620410094` · Vladimir pid 6 · `839881`  
**Capture:** `01M00NSCH421BEY2SP3PADQT8A` (path+GST, full 17 s)

## 1. Hypothesis

A conservative scored ranking over existing champion-like tracks near a GST death can promote `UNKNOWN → LIKELY` when one track has a uniquely strong evidence bundle — without widening `DEATH_ALIGN_MS` as a binary gate, without inventing `CORRELATED`, and without depending on subject camera attachment (`SUBJECT_ATTACH_PARTIAL`).

## 2. Algorithm

1. Pool champion-like, non-ambiguous tracks with presence in `±CANDIDATE_POOL_MS` (5000 ms) of GST death.  
2. Score each candidate with documented terms (below). Hard conflicts zero eligibility.  
3. Require `temporal_join` (last_seen in `[death − pool, death + 250]`) for promotion. Tracks that remain observed past `death + POST_DEATH_ABSENCE_MS` are not temporal joins.  
4. Rank eligible candidates by score. Fail if top-two margin `< MIN_WINNER_MARGIN` (0.12).  
5. Require ≥1 **independent** support beyond temporal. Trajectory score can strengthen but **does not** count as that independent support. Unique disappearance counts only when `observation_count ≥ 3`.  
6. Emit `LIKELY` capped at `0.55`. Never emit `CORRELATED` from V.6.  
7. Camera ownership / subject attachment flags alone → fail closed.

`DEATH_ALIGN_MS` remains **2000** (V.4 binary unique-disappearance). Pooling ≠ widening that constant.

## 3. Evidence families

| Family | Role |
|---|---|
| GST death timestamp | Required context |
| Track first/last span | Raw timing |
| Unique disappearance (`DEATH_ALIGN_MS`) | Independent support + score |
| Pre-death continuity/density | Independent support |
| V.5 trajectory | Score only when temporal join holds; not sole independent support |
| Calibrated team label | Independent support / hard mismatch conflict |
| Alive-after-death | Hard conflict |
| Competing candidates | Uniqueness via margin (not per-track zeroing) |
| Fragmentation | Continuity CONFLICT when gaps too large |
| Post-death reappearance | Hard conflict |
| Camera ownership / attachment | Never score; hard reject if treated as identity |

### Score terms

| Term | Weight | Notes |
|---|---:|---|
| Temporal proximity | 0.40 | Linear decay over pool; 0 at pool edge |
| Unique disappearance | 0.20 | Only if exactly one `disappearing_near` hit |
| Continuity SUPPORT | 0.15 | V.5 pre-death cue |
| Trajectory SUPPORT | 0.10 | Only if temporal join already true |
| Team agree | 0.10 | Calibrated ALLY vs subject |

Raw values are retained on each candidate (`score_terms`, continuity bundle, observation_count).

## 4. Confidence / status policy

| Transition | Rule |
|---|---|
| Stay UNKNOWN | No temporal join; conflicts; close scores; ownership/attachment alone; weak sparse unique |
| UNKNOWN → LIKELY | Temporal join + unique winner margin + ≥1 independent support; conf ≤ 0.55 |
| → CORRELATED | **Blocked** in V.6 |

Provenance: identity conclusions remain `VISUAL_INFERRED`. GST death is Riot-derived evidence. GST is not mutated.

## 5. Synthetic tests

`tests/unit/test_visual_v6.py` (16 cases): unique+team → LIKELY; two similar → UNKNOWN; alive-after → UNKNOWN; team mismatch → UNKNOWN; no temporal join → UNKNOWN; fragmented-OK → LIKELY; duplicates → uniqueness fail; trajectory-only/sparse → UNKNOWN; camera ownership alone → UNKNOWN; attachment alone → UNKNOWN; never CORRELATED; LIKELY cap; sparse no crash; GST fact-list identical; `DEATH_ALIGN_MS` unchanged; V.4 path still works with V.6 confirm.

## 6. Real candidate table

Capture `01M00NSCH421BEY2SP3PADQT8A`, death `839881`:

| track | team | first | last | dur ms | Δdeath | temp join | cont | traj | alive after | conflicts | score | rank |
|---|---|---:|---:|---:|---:|---|---|---|---|---|---:|---:|
| trk_0007 | ENEMY | 835148 | 837157 | 2009 | −2724 | yes | no | UNCERTAIN | no | team_mismatch | 0.182 | 1 |
| trk_0008 | ENEMY | 837157 | 837157 | 0 | −2724 | yes | no | SPARSE | no | team_mismatch | 0.182 | 2 |
| trk_0002 | ENEMY | 829917 | 846634 | 16717 | +6753 | no | yes | STATIONARY | **yes** | team_mismatch, alive_after_death, reappearance | 0.15 | 3 |
| trk_0003 | ENEMY | 829917 | 846634 | 16717 | +6753 | no | yes | STATIONARY | **yes** | team_mismatch, alive_after_death, reappearance | 0.15 | 4 |

Reject: `temporal_candidates_conflicted_or_weak` (team mismatch on near-death ends; long tracks alive after death). No unique disappearance within ±2000 ms.

## 7. V.4 → V.5 → V.6 comparison

| Layer | Status | Track | Notes |
|---|---|---|---|
| V.4 | UNKNOWN | — | `disappearing_tracks=0` |
| V.5 | UNKNOWN | — | no base LIKELY |
| V.6 | **UNKNOWN** | — | ranking fail-closed; honest |

Selected candidate: none. Confidence: 0. Winner margin: 0.

## 8. Fail-closed cases (observed)

- Alive-after-death long tracks (trk_0002/0003)  
- Team mismatch (all calibrated ENEMY vs expected ALLY)  
- No unique death-aligned disappearance  
- Subject attachment not used (by design)  
- Camera framing ownership ignored for identity  

## 9. Runtime

| Metric | Value |
|---|---:|
| Ranking only | **0.36 ms** |
| Continuity (V.5) | ~0.1–1 ms typical |
| Full V.6 analyze wall | ~1.73 s (dominated by detect/sample) |
| Detect | ~timing.detect_ms from artifact |
| Track count | 8 champion-like in prior diagnostic; 4 pooled here |

Ranking is negligible vs detection.

## 10. Limitations

- Path+GST keeps world-stable tracks that **survive through death**, so disappearance evidence is scarce.  
- Team calibration on this window labels survivors ENEMY; subject-relative ALLY expectation conflicts.  
- No Replay API participant id; V.6 does not depend on attachment.  
- Secondary death `1062798` not re-run (prior V.5 alt clip had no stable tracks; primary clip does not cover it).  
- Still no pixel champion identity.

## 11. Final verdict

**`PARTIALLY_SUPPORTED`**

The ranking model, fail-closed policy, synthetic coverage, and real-table honesty are in place. This replay correctly remains UNKNOWN; V.6 was **not** tuned to force LIKELY.

## 12. Recommended next visual step

Do **not** widen `DEATH_ALIGN_MS`. Prefer classical continuity improvements that create a true death-aligned disappearance (or a unique pre-death fragment that ends near death with subject-consistent team), then re-run V.6 unchanged. Subject attachment remains `PARTIAL` and is not an identity substitute. Keep V.6 isolated from coaching until a second real window yields a clean LIKELY without threshold cheats.

## Isolation

Not wired into coaching, rules, review, overlay, or production gameplay services.

## Artifacts

- `services/analysis/artifacts/v6_mac_5620410094_validation.json`  
- `services/analysis/scripts/v6_mac_validation.py`  
- `services/analysis/tests/unit/test_visual_v6.py`
