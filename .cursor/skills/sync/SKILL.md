---
name: sync
description: >-
  Fetch and fast-forward the current branch from origin so this machine matches
  GitHub. Use when the user runs /sync, asks to pull latest, or switch machines
  (Mac ↔ Windows) and needs to be up to date before working.
disable-model-invocation: true
---

# /sync — match this machine to GitHub

Bring the **current branch** up to date with `origin` so Mac/Windows stay aligned.
Do not start new product work during `/sync`.

## Steps (run in repo root)

1. Show context:
   ```bash
   git rev-parse --show-toplevel
   git branch --show-current
   git status -sb
   ```
2. Fetch:
   ```bash
   git fetch --all --prune --tags
   ```
3. Compare to upstream (create tracking if missing with `git branch -vv`):
   ```bash
   git rev-list --left-right --count '@{u}'...HEAD 2>/dev/null || true
   git rev-parse HEAD
   git rev-parse '@{u}' 2>/dev/null || true
   ```
4. **Dirty tree** (`git status --porcelain` non-empty):
   - Do **not** `git reset --hard` or discard changes.
   - Report dirty files. Offer: stash → pull --ff-only → stash pop, **or** commit first.
   - Stop until the user chooses (unless they already said “stash and pull”).
5. **Clean tree**:
   ```bash
   git pull --ff-only
   ```
   If ff-only fails (diverged history), stop and report; do not rebase or merge unless the user asks.
6. Optional helper (same behavior):
   ```bash
   bash .cursor/skills/sync/scripts/sync.sh
   ```

## Report (always)

| Field | Value |
|---|---|
| Branch | … |
| Local HEAD | full hash |
| Remote tip (`@{u}`) | full hash |
| Ahead / behind | N / M |
| Working tree | clean / dirty |
| Action taken | fetched only / pulled / blocked (why) |
| Ready to work? | yes / no |

If local was already equal to `@{u}` and clean: say **already up to date**.
