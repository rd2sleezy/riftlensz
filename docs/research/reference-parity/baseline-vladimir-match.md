# Baseline: NA1_5620410094 / participant 6 / Vladimir TOP

**Adjudication label:** `PILOT_SELF_REVIEW`  
**This is not independent expert validation.**  
**Privacy:** no PUUID, summoner name, account id, API key, or raw DTO.

**Statement kinds in this file:** human judgment (pilot), observed (C.x/GST limitations), inference (what would be needed).

Regenerate:

```bash
cd services/analysis
python scripts/rp_parity.py baseline
```

## Context

First real C.x validation match. Role TOP, champion Vladimir, participant 6.

## Moments

### 7:07 — objective.presence — Human: PARTLY

Dragon existed and a rotate window existed, but allies lacked lane priority and jungler was not attempting dragon; rotating likely loses wave XP/gold for a low-value contest.

**Parity gap:** objective presence alone is not enough. Need contestability, priority, jungler/team intent, wave opportunity cost, cross-map value.

### 14:00 — clean lane — Human: AGREE

Won lane, good CS, no unnecessary deaths.

### 24:00 — roam without priority — Human: DISAGREE

Laning phase effectively over, dragon active; joining team immediately likely more valuable than first pushing top.

**Parity gap:** roam-cost reasoning needs game phase, urgency, objective timing, and teamfight risk.

### 24:06 — fight selection — Human: AGREE

Committed without adequately accounting for enemy positions; fed jungler arrived and death followed.

### 24:28 — unseen jungler — Human: AGREE

Jungler was not visible at initial commitment and appeared from fog afterward.

### 31:24 — fight selection — Human: PARTLY

Three enemies visible and the other two recently known nearby. Information awareness was largely sufficient. Actual mistake was **knowingly entering a 1v3 / overestimating impact**.

**CRITICAL parity gap:** current detector notices a problematic fight but assigns the **wrong reason** (`unaccounted_enemies` ≠ `knowingly_entered_1v3`).

### 25:56 / 28:07 / 35:21 — post-fight conversion — Human: AGREE (won + survived)

Overall conversion problem: **PARTLY**. Many enemy waves were pushed into allied side. Pushing those waves out was itself meaningful conversion. By the time waves were corrected, enemies were respawning.

**CRITICAL parity gap:** RiftLens cannot judge conversion correctly without **wave state**.

## Overall likely primary human lesson

**FIGHT SELECTION / COMMITMENT DISCIPLINE.**

Before committing, validate numbers, known/unknown threats, reinforcements, and whether the fight is realistically favorable.

Do not treat C.x teaching-copy issues (e.g. “contestorsecure”, “deliberatefarm”) as fixed here.
