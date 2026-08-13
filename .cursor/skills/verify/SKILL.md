---
name: verify
description: >-
  Run the RiftLens acceptance gate (pytest, mypy --strict, ruff, lint-imports,
  and desktop typecheck/lint when relevant). Use when the user runs /verify,
  finishes an H/R/V work unit, or asks to run the full regression / acceptance
  suite before declaring work complete.
disable-model-invocation: true
---

# /verify — acceptance + regression gate

Run from the **repo root**. Fix failures before declaring a work unit complete.
Do not start the next work order from `/verify`.

## Environment

Prefer the project toolchain on PATH (Mac or Git Bash):

```bash
REPO="$(git rev-parse --show-toplevel)"
export PATH="${HOME}/.local/bin:${REPO}/.tools/node/bin:${REPO}/services/analysis/.venv/bin:${PATH}"
```

On Windows PowerShell, put the equivalent directories first on `$env:PATH` (`.tools\node`, `services\analysis\.venv\Scripts`, and wherever `uv`/`pnpm` live).

If `.venv` or `.tools/node` is missing, report that and stop — do not invent a different Python/Node.

## Default suite (always)

```bash
cd services/analysis
python -m pytest -q --tb=line
ruff check riftlens tests
mypy --strict riftlens
lint-imports
```

Or:

```bash
bash .cursor/skills/verify/scripts/verify.sh
```

## Desktop (when UI / IPC / Electron touched, or user says `full`)

From repo root:

```bash
cd apps/desktop
pnpm typecheck
pnpm lint
pnpm exec vitest run
```

Add `pnpm exec electron-vite build` and `pnpm exec playwright test` when the change is H.9-class UI or the user asks for e2e/`full`.

## Modes

| User says | Run |
|---|---|
| `/verify` | Sidecar suite only |
| `/verify full` or desktop files changed | Sidecar + desktop typecheck/lint/vitest |
| `/verify e2e` | Sidecar + desktop including build + playwright |

## Report

Print a pass/fail table for each command. Stop at first hard failure only if the user wants a fast loop; otherwise run the full selected suite and list all failures.

Never claim “verified” if any selected check failed.
