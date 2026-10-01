"""
Shared permission system.

Works across every platform. Admins/mods are configured once in config
and apply to both Kick and (future) YouTube usernames.
Temporary permits are also tracked here.
"""

from __future__ import annotations

import time
from typing import Dict

from .models import ChatUser, PermissionLevel


class PermissionManager:
    def __init__(self, config: dict):
        perms = config.get("permissions", {})
        self.admins = self._names(perms.get("admin", []))
        self.mods = self._names(perms.get("mod", []))
        # public is always open; the "*" entry is just documentation
        self._temp_permits: Dict[str, float] = {}  # username -> expiry epoch

    @staticmethod
    def _names(val) -> set:
        """Accept a list or a single string from hand-edited YAML."""
        if not val:
            return set()
        if isinstance(val, str):
            name = val.lower().strip()
            return {name} if name else set()
        return {str(u).lower().strip() for u in val if str(u).strip()}

    def grant_temp(self, username: str, minutes: int = 10) -> None:
        key = username.lower().strip()
        if key:
            self._temp_permits[key] = time.time() + minutes * 60

    def clear_temp(self, username: str) -> None:
        self._temp_permits.pop(username.lower().strip(), None)

    def _is_temp_permitted(self, username: str) -> bool:
        key = username.lower().strip()
        exp = self._temp_permits.get(key)
        if exp is None:
            return False
        if exp < time.time():
            del self._temp_permits[key]
            return False
        return True

    def has_permission(self, user: ChatUser | str, required: PermissionLevel | str) -> bool:
        if isinstance(required, str):
            required = PermissionLevel(required.lower())

        if required == PermissionLevel.PUBLIC:
            return True

        name = (user.username if isinstance(user, ChatUser) else user).lower().strip()

        if name in self.admins:
            return True
        if required == PermissionLevel.ADMIN:
            return False

        if name in self.mods or self._is_temp_permitted(name):
            return True
        if required == PermissionLevel.MOD:
            return False

        return False

    def effective_level(self, user: ChatUser | str) -> PermissionLevel:
        name = (user.username if isinstance(user, ChatUser) else user).lower().strip()
        if name in self.admins:
            return PermissionLevel.ADMIN
        if name in self.mods or self._is_temp_permitted(name):
            return PermissionLevel.MOD
        return PermissionLevel.PUBLIC
