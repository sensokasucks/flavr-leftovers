# Checklist — Workshop conventions

Home: repo root. Map: [README.md](../README.md).

## Must keep

- [ ] Project prefix is `fridge-`. No new `xsplit-*` folders.
- [ ] One concern per folder. Platforms = adapters. Games = plugins (`fridge-stream-core/plugins/<id>/`). Overlays = dumb HTML.
- [ ] Bind loopback (`127.0.0.1`) by default. Do not expose ports to the internet in examples or start scripts.
- [ ] Loopback is not enough: browsers can reach it. HTTP apps keep the local guard — Python apps via `core/local_guard.py` (Core + Chat Credits copies stay in sync), game bridges via Core's `X-Fridge-Core: 1` header + no `Origin` + loopback `Host`. No `Access-Control-Allow-Origin: *` on write endpoints.
- [ ] Ports stay put:

  | Port | Owner |
  |------|--------|
  | 3847 | Factorio bridge (flavr-game-plugins repo) |
  | 3850 | Stream Core HTTP / WS / overlays / admin |
  | 3851 | Reactive Image HTTP (flavr-reactive-image repo) |
  | 3852 | Minecraft client mod (flavr-game-plugins repo) |
  | 3853 | Minecraft server mod / NeoForge bridge (flavr-game-plugins repo) |
  | 3854 | Standalone Chat Credits |
  | 3855 | Granvir Stats (flavr-game-plugins repo) |

- [ ] Live secrets stay out of git: `config/config.yaml`, `.env`, `data/`, `*.db`, jars, `.venv`, `.grok/`.
- [ ] Examples stay committed: `*.example.*`, `config.example.yaml`, `commands.example.json`.
- [ ] Root start/install bats still exist and still point at the current folders:
  - `INSTALL Stream Core.bat` / `START Stream Core.bat`
  - `INSTALL Chat Credits.bat` / `START Chat Credits.bat`
- [ ] Root README table lists every live package + its port.
- [ ] Stream Core changelog remains the workshop changelog: `fridge-stream-core/CHANGELOG.md`.
- [ ] Git hooks in `githooks/` still block secrets and built binaries (turned on with `git config core.hooksPath githooks`, see GIT.md).
- [ ] No backups, tarballs, patch files or one-off scripts committed at the root; old versions live in git history.
- [ ] Root `CLAUDE.md` stays the Claude Code entry (map + hard rules). It must keep pointing at `AGENTS.md` and `checklists/`.

## Drop risks

- Saving Config from the admin GUI used to wipe whole YAML sections (`command_groups`, `minecraft.market`). Merge, do not replace blindly.
- Rebrand leftovers: overlay comments and encoder docs may still say XSplit / OBS — that is fine. Folder names must stay `fridge-*`.
- A “fresh zip” must not include secrets, jars, or `.venv`.

## After-change verify

- [ ] Root README ports and project table still match reality.
- [ ] No second top-level folder invented for a feature that already has a home.
- [ ] `.gitignore` still covers live config and `data/`.
