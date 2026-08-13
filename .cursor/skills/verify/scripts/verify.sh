#!/usr/bin/env bash
# Sidecar acceptance gate. Exit non-zero on first failure.
set -euo pipefail

REPO="$(git rev-parse --show-toplevel)"
cd "${REPO}"

export PATH="${HOME}/.local/bin:${REPO}/.tools/node/bin:${REPO}/services/analysis/.venv/bin:${PATH}"

cd "${REPO}/services/analysis"

if [[ ! -x .venv/bin/python && ! -x .venv/Scripts/python.exe ]]; then
  echo "ERROR: services/analysis/.venv missing — create with uv sync in services/analysis"
  exit 1
fi

PY=python
if [[ -x .venv/bin/python ]]; then
  PY=".venv/bin/python"
elif [[ -x .venv/Scripts/python.exe ]]; then
  PY=".venv/Scripts/python.exe"
fi

echo "== pytest =="
${PY} -m pytest -q --tb=line

echo "== ruff =="
${PY} -m ruff check riftlens tests

echo "== mypy --strict =="
${PY} -m mypy --strict riftlens

echo "== lint-imports =="
lint-imports

echo "STATUS: sidecar verify OK"
