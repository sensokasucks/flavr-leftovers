#!/usr/bin/env bash
# FlaVR Leftovers — one-time git setup
set -euo pipefail
cd "$(dirname "$0")"

if ! command -v git >/dev/null; then
  echo "git not found"; exit 1
fi

if [[ ! -d .git ]]; then
  git init -b main 2>/dev/null || { git init; git branch -M main; }
  echo "Initialized repo on main"
else
  echo "Git repo already present"
fi

if ! git remote get-url origin >/dev/null 2>&1; then
  git remote add origin https://github.com/sensokasucks/flavr-leftovers.git
  echo "Added origin -> https://github.com/sensokasucks/flavr-leftovers.git"
else
  echo "Origin: $(git remote get-url origin)"
fi

echo
echo "Next: ./git-push.sh   or   git add -A && git commit && git push -u origin main"

if [[ -f githooks/pre-commit ]]; then
  chmod +x githooks/* 2>/dev/null || true
  git config core.hooksPath githooks
  echo "Hooks path set to githooks/"
fi

