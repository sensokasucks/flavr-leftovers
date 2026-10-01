build streaming plugins based on user needs. Try to keep everything modular and documented.

## Feature checklists (required)

Before you call a change done, walk the lists in **[checklists/](checklists/)**.

1. Start at [checklists/INDEX.md](checklists/INDEX.md). Open every list the change can touch — not only the feature you meant to edit.
2. Treat **Must keep** as the contract. If an item is no longer true, restore it or update that checklist in the same change and say why.
3. Config / admin / overlay / new-game work also walks `workshop-conventions`, `admin-hub`, and (if YAML or commands moved) `commands-permissions-groups`.
4. Do not invent a second copy of a feature that a checklist already places in another folder.

Adding a feature: new `checklists/<feature>.md`, link it from INDEX, point at it from the package README if it has a home folder.
