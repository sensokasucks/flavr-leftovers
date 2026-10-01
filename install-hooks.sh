#!/usr/bin/env bash
set -euo pipefail
cd "$(dirname "$0")"

command -v git >/dev/null || { echo "git not found"; exit 1; }
[[ -d .git ]] || { echo "Not a git repo — run ./git-setup.sh first"; exit 1; }
[[ -f githooks/pre-commit ]] || { echo "githooks/ missing"; exit 1; }

chmod +x githooks/pre-commit githooks/commit-msg githooks/pre-push 2>/dev/null || true
git config core.hooksPath githooks
echo "core.hooksPath=$(git config --get core.hooksPath)"
echo "Hooks: pre-commit, commit-msg, pre-push"
echo "Skip: SKIP_HOOKS=1 git commit|push ..."
