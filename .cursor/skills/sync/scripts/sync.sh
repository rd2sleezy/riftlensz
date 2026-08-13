#!/usr/bin/env bash
# Fast-forward current branch to origin. Never discards local changes.
set -euo pipefail

cd "$(git rev-parse --show-toplevel)"

branch="$(git branch --show-current)"
echo "branch: ${branch}"

git fetch --all --prune --tags

if ! git rev-parse --abbrev-ref '@{u}' >/dev/null 2>&1; then
  echo "ERROR: no upstream for ${branch}. Set with: git push -u origin HEAD"
  exit 1
fi

upstream="$(git rev-parse --abbrev-ref '@{u}')"
local_h="$(git rev-parse HEAD)"
remote_h="$(git rev-parse '@{u}')"
counts="$(git rev-list --left-right --count '@{u}'...HEAD)"
behind="${counts%%[[:space:]]*}"
ahead="${counts##*[[:space:]]}"

echo "upstream: ${upstream}"
echo "local:    ${local_h}"
echo "remote:   ${remote_h}"
echo "ahead/behind (local/remote perspective via left-right @{u}...HEAD): ${counts}"

if [[ -n "$(git status --porcelain)" ]]; then
  echo "STATUS: dirty working tree — refusing to pull"
  git status -sb
  exit 2
fi

if [[ "${local_h}" == "${remote_h}" ]]; then
  echo "STATUS: already up to date"
  exit 0
fi

if [[ "${ahead}" != "0" && "${behind}" != "0" ]]; then
  echo "STATUS: diverged (ahead=${ahead} behind=${behind}) — refusing automatic merge/rebase"
  exit 3
fi

if [[ "${behind}" != "0" ]]; then
  git pull --ff-only
  echo "STATUS: pulled to $(git rev-parse HEAD)"
  exit 0
fi

echo "STATUS: local ahead by ${ahead}; nothing to pull (push when work is complete)"
exit 0
