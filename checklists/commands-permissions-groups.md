# Checklist — Commands / permissions / groups

Home: `core/command_router.py`, `core/command_groups.py`, `core/permissions.py`, `config/commands.json`.

## Must keep

- [ ] Prefix is `!` from `core.command_prefix`.
- [ ] Permission tiers: `admin` / `mod` / `public`. Entries match case-insensitively. Plain names match **Kick + Twitch** logins only; `kick:` / `twitch:` scope one platform; YouTube needs `youtube:<channel id>`. (Changed from "across all platforms": YouTube names are copyable display names, so a plain entry let anyone impersonate an admin.)
- [ ] Admin test bench injects its test admin as `platform:id`, not a plain name.
- [ ] `!permit` still exists on group `core`.
- [ ] Commands support aliases, quantity, and templates.
- [ ] `command_groups` in `config.yaml`: each group has `enabled`, optional `bind`, optional `always`, `description`.
- [ ] `core` is always on (`always: true`).
- [ ] Bind semantics:
  - `minecraft` / `factorio` / `openttd` / `granvir` → config enabled **and** integration running
  - `points` → `points.enabled`
  - `credits` → `credits.enabled`
  - `market` → `market.enabled`
  - `reactions` → `reactions.enabled` (reaction commands live in `config.yaml` → `reactions.entries`, not `commands.json`; a `commands.json` name wins)
- [ ] Groups and `commands.json` hot-reload from Admin (Save groups / Hot-reload / Save + hot-reload).
- [ ] Name/alias conflicts: higher `priority` wins; equal priority keeps the first definition. Admin banner lists token, winner, loser, reason.
- [ ] `core.command_groups` exports `resolve_active_groups` **and** `catalog_status` plus the `CommandGroups` wrapper.
- [ ] `main.py` group import stays inside the existing `try` (indentation bug in 0.11.1).
- [ ] Saving `config.yaml` from the GUI **must not drop** `command_groups` or any other unknown section.
- [ ] Built-in Core commands `!help` and `!points` / `!balance` stay available when their groups are on.
- [ ] Integrations command tester (`dry-run` / `live`) still goes through the real CommandRouter.

## Drop risks

- Config tab rewrite that serializes only the fields the form knows about.
- New command token colliding with Market / OpenTTD / Credits (`!tickers`, `!quote`, `!credit`, `!invest`).
- Moving `command_groups` import out of the `try` in `main.py`.

## After-change verify

- [ ] `config.example.yaml` still has groups: `core`, `points`, `minecraft`, `factorio`, `openttd`, `credits`, `market`, `reactions`.
- [ ] Admin → Config still has the group table and command editor (group, handler, priority, enabled).
- [ ] A dummy extra YAML key you add by hand survives a Config save (or is documented as stripped).
