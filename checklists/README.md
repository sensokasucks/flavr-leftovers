# Feature checklists

One file per workshop feature. Walk the relevant lists **before you call a change done**.

These exist because pieces have already been dropped once (Credits admin API after 0.13.0, `command_groups` wiped by Config save, Minecraft `enabled` default flipped, Market knobs wiped from Config, OpenTTD share-slot design). A changelog line is not enough.

## How to use (every change)

1. Open [INDEX.md](INDEX.md). Pick every list the change can touch — not only the feature you meant to edit.
2. Read that file end to end. The **Must keep** section is the contract.
3. After the edit, tick through **Must keep** and **After-change verify**. If an item is no longer true, either restore it or update the checklist in the same change and say why.
4. Cross-cutting work (admin save, config merge, overlay rewrite, new game slot) always also walks:
   - [workshop-conventions.md](workshop-conventions.md)
   - [admin-hub.md](admin-hub.md)
   - [commands-permissions-groups.md](commands-permissions-groups.md) if `config.yaml` / `commands.json` are involved

Do not invent a second copy of a feature in another folder. If the checklist says it lives in Core, keep it in Core.

## What a checklist is not

- Not a design spec (those stay in `docs/` and package READMEs).
- Not a changelog (that stays in `fridge-stream-core/CHANGELOG.md`).
- Not optional for agents. `AGENTS.md` requires this pass.

## Adding a feature

1. Add `checklists/<feature>.md` using the same headings as the others.
2. Link it from [INDEX.md](INDEX.md).
3. Add a one-line pointer from the package README if the feature has a home folder.
4. Record the new path in project memory.
