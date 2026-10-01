#!/usr/bin/env bash
set -euo pipefail
cd "$(dirname "$0")"
[[ -d .git ]] || { echo "Run ./git-setup.sh first"; exit 1; }
git pull --rebase origin main
