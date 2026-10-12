# Checklist index

| Feature | File | Touch this when you change… |
|---------|------|-----------------------------|
| Workshop conventions | [workshop-conventions.md](workshop-conventions.md) | Ports, folders, bats, gitignore, rebrand, root README |
| Adapters / chat | [adapters-chat.md](adapters-chat.md) | Kick / Twitch / YouTube, EventBus chat, chat overlay |
| Commands / permissions / groups | [commands-permissions-groups.md](commands-permissions-groups.md) | Router, `commands.json`, `command_groups`, `!permit` |
| Points / users / chat log | [points-users-chatlog.md](points-users-chatlog.md) | SQLite store, identity links, Admin Users / Chat History |
| Chat reactions | [reactions.md](reactions.md) | `core/reactions.py`, Config → Reactions, `/overlay/reactions.html`, game WebSocket frames |
| Chat games | [chat-games.md](chat-games.md) | `core/chat_games/`, Admin Chat games page, `board` frames, streams / attendance tables |
| Paid list | [paid.md](paid.md) | `core/paid.py`, Admin → Paid, `/api/admin/paid*`, paid kinds on chat events |
| Alerts | [alerts.md](alerts.md) | Alert overlay, skins, custom CSS, test tab |
| Stored files | [stored-files.md](stored-files.md) | `core/media_library.py`, `data/media/`, `/media/`, Stored files page, picture / sound slots |
| Chat widgets | [widgets.md](widgets.md) | `core/widget_store.py`, `/overlay/widget.html`, `/widget-frame/`, Chat widgets page, StreamElements / Streamlabs event shapes |
| Credits (Core) | [credits-core.md](credits-core.md) | Built-in credits overlay, cast styles, Admin Credits |
| Gamer Stonks (the market) | [market.md](market.md) | Now a plugin in flavr-game-plugins; what Core still owes it |
| Admin hub | [admin-hub.md](admin-hub.md) | `/admin/` tabs, save/merge, APIs |
| Overlays (shared) | [overlays.md](overlays.md) | Webpage sources, ports, query filters |
| Plugins (games + features) | [plugins.md](plugins.md) | `plugins/`, `core/plugins.py`, `core/plugin_api.py`, `core/plugin_manifest.py`, Settings → Plugins |

## Always-on companions

| If you edit | Also walk |
|-------------|-----------|
| `core/config.py` or Config tab save | workshop-conventions, commands-permissions-groups, admin-hub, plus every feature whose YAML block you touch |
| `admin/index.html` / `admin.js` | admin-hub + the tab’s feature file |
| Overlay HTML/JS | overlays + that feature |
| A game plugin | plugins + that game + commands-permissions-groups (and Gamer Stonks' checklist in flavr-game-plugins if it prices or pays) |
| New command token | commands-permissions-groups (conflicts / groups) |
