#!/usr/bin/env bash
# FlaVR Leftovers — stage, commit, push
set -euo pipefail
cd "$(dirname "$0")"

if [[ ! -d .git ]]; then
  echo "Not a git repo — run ./git-setup.sh first"; exit 1
fi

if ! git remote get-url origin >/dev/null 2>&1; then
  git remote add origin https://github.com/sensokasucks/flavr-leftovers.git
fi

git add -A
git status -sb

if git diff --cached --quiet; then
  echo "Nothing to commit; pushing anyway..."
  git push -u origin main || git push -u origin HEAD:main
  exit 0
fi

MSG="${*:-Sync FlaVR Leftovers from workshop tree}"
git commit -m "$MSG"
git push -u origin main || git push -u origin HEAD:main
echo "Done: https://github.com/sensokasucks/flavr-leftovers"
