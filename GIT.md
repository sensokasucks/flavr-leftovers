# Git helpers — FlaVR Leftovers

Push this workshop folder to **https://github.com/sensokasucks/flavr-leftovers**.

## Windows (recommended)

1. Install [Git for Windows](https://git-scm.com/download/win) if needed.
2. Sign in once (`gh auth login` or credential manager).
3. In this folder:
   - **`git-setup.bat`** (once) — init repo, remote, **and git hooks**
   - **`git-push.bat`** — stage, commit, push

```bat
git-push.bat Sync Stream Core 0.11 and monorepo
```

## Linux / macOS

```bash
chmod +x git-setup.sh git-push.sh git-pull.sh install-hooks.sh
./git-setup.sh
./git-push.sh "Your message"
```

## Git hooks (automation)

Hooks live in **`githooks/`** (version-controlled) and are enabled via:

```bat
install-hooks.bat
```

```bash
./install-hooks.sh
```

`git-setup` also sets `core.hooksPath=githooks` when that folder exists.

| Hook | When | What it does |
|------|------|----------------|
| **pre-commit** | Every commit | Blocks `config/config.yaml`, `.env`, `data/`, `*.db`, jars/exes |
| **commit-msg** | Every commit | Rejects empty / tiny messages |
| **pre-push** | Every push | Runs `fridge-stream-core` tests if Python is available |

Skip hooks for one command:

```bat
set SKIP_HOOKS=1
git commit -m "emergency"
```

```bash
SKIP_HOOKS=1 git push
```

## What is never committed

Root **`.gitignore`** excludes:

- Live config (`config/config.yaml`)
- `data/`, databases, `.venv/`, `node_modules/`
- Built `*.jar` / dist outputs
- `.grok/`

Keep `*.example.*` files.

## If push is rejected

```bat
git-pull.bat
git-push.bat
```

## Auth note

Scripts run **on your machine**. The Grok sandbox can edit files and use the GitHub API, but does not hold your git credentials for `git push`.
