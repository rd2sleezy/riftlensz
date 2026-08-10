# Follow-up: post-fight coaching must require an alive/actionable player

**Status:** open — do not fix in R.9  
**Kind:** coaching-quality defect (H.7/H.8), **not** a native-replay or R.9 failure  
**Discovered:** 2026-08-09 during R.9 Windows desktop T4 on `NA1_5617764200`

## Observation

Review `01KZMXE3JHJT9PG9H5VR02E1FR`, Kaisa pid 9.

At approximately **14:37** (`t_ms` ≈ 877435) the secondary item **“Spend tempo after a won fight.”** fired.

Manual League replay inspection showed Kaisa was **dead** during the actionable post-fight window. She appears to have received an **assist on a team kill despite already being dead**, so the rule attributed post-fight agency to a player who could not act.

Replay seek to that timestamp worked; the defect is the coaching attribution, not clock conversion or reveal.

## Intended follow-up

> Post-fight coaching rules must verify reviewed-player alive/actionable state before assigning tempo/conversion recommendations.

Do **not** change H.7/H.8 until this is scheduled as its own work. Do not treat it as R.10/H.10 scope.
