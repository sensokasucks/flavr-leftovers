# Git — FlaVR Leftovers

Repo: **https://github.com/sensokasucks/flavr-leftovers** (branch `main`). Changes come in as pull
requests; after one is merged, update your copy with:

```bat
git pull
```

Then restart Stream Core.

Related repos (not part of this one):

- **[flavr-game-plugins](https://github.com/sensokasucks/flavr-game-plugins)** — Minecraft, Factorio, Granvir, OpenTTD plugins and their mods / bridges
- **[flavr-reactive-image](https://github.com/sensokasucks/flavr-reactive-image)** — the audio-reactive avatar app
- **[fridge-chat-credits](https://github.com/sensokasucks/fridge-chat-credits)** — standalone Chat Credits (for streams without Core)

## Git hooks (optional)

Hooks live in **`githooks/`**. Turn them on once per checkout:

```bat
git config core.hooksPath githooks
```

| Hook | When | What it does |
|------|------|----------------|
| **pre-commit** | Every commit | Blocks `config/config.yaml`, `.env`, `data/`, `*.db`, jars/exes |
| **commit-msg** | Every commit | Rejects empty / tiny messages |
| **pre-push** | Every push | Runs `fridge-stream-core` tests if Python is available |

Skip them for one command with `SKIP_HOOKS=1` (`set SKIP_HOOKS=1` on Windows).

## What is never committed

Root **`.gitignore`** excludes live config (`config/config.yaml`), `data/`, databases, `.venv/`,
`node_modules/`, built jars / dist output, `.grok/`, and game plugin folders installed into
`fridge-stream-core/plugins/`. Keep `*.example.*` files.
