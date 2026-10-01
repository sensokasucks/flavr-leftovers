"""
Shared permission system.

Admins/mods are configured once in config and apply across platforms.
Temporary permits (!permit) are also tracked here.

Entry formats in ``permissions.admin`` / ``permissions.mod``:

  sensoka              plain name — Kick and Twitch only (their usernames
                       are unique logins)
  kick:sensoka         one platform, matched by username or user id
  twitch:sensoka
  youtube:UCxxxxxxxx   YouTube needs the channel id. A YouTube "username" is
                       only a display name that anyone can copy, so plain
                       names never grant anything on YouTube.
"""

from __future__ import annotations

import logging
import time
from typing import Dict

from .models import ChatUser, PermissionLevel

log = logging.getLogger("core.permissions")

# Platforms whose chat username is a unique, non-spoofable login.
UNIQUE_NAME_PLATFORMS = {"kick", "twitch"}


def _plat(user: ChatUser) -> str:
    p = user.platform
    return str(getattr(p, "value", p) or "").lower()


class PermissionManager:
    def __init__(self, config: dict):
        perms = config.get("permissions", {})
        self.admins = self._names(perms.get("admin", []))
        self.mods = self._names(perms.get("mod", []))
        # public is always open; the "*" entry is just documentation
        self._temp_permits: Dict[str, float] = {}  # key -> expiry epoch
        self._hinted: set[str] = set()

    @staticmethod
    def _names(val) -> set:
        """Accept a list or a single string from hand-edited YAML."""
        if not val:
            return set()
        if isinstance(val, str):
            name = val.lower().strip()
            return {name} if name else set()
        return {str(u).lower().strip() for u in val if str(u).strip()}

    # ------------------------------------------------------------------
    @staticmethod
    def identity_keys(user: ChatUser | str) -> set[str]:
        """Keys this user may be listed under. Plain names only where unique."""
        if not isinstance(user, ChatUser):
            name = str(user or "").lower().strip()
            return {name} if name else set()
        plat = _plat(user)
        uid = str(user.id or "").lower().strip()
        name = str(user.username or "").lower().strip()
        keys: set[str] = set()
        if plat and uid:
            keys.add(f"{plat}:{uid}")
        if plat in UNIQUE_NAME_PLATFORMS and name:
            keys.add(name)
            keys.add(f"{plat}:{name}")
        return keys

    def _temp_keys(self, user: ChatUser | str) -> set[str]:
        keys = self.identity_keys(user)
        # !permit youtube:<name> (spaces removed) — short-lived, admin-issued.
        if isinstance(user, ChatUser) and _plat(user) == "youtube":
            name = "".join(str(user.username or "").lower().split())
            if name:
                keys.add(f"youtube:{name}")
        return keys

    def _hint_youtube(self, user: ChatUser) -> None:
        if _plat(user) != "youtube":
            return
        name = str(user.username or "").lower().strip()
        if name and (name in self.admins or name in self.mods) and name not in self._hinted:
            self._hinted.add(name)
            log.warning(
                "YouTube user '%s' matches a plain permissions entry, which no longer "
                "applies on YouTube (display names can be copied). If this is really you, "
                "add 'youtube:%s' to permissions instead.",
                user.username, user.id,
            )

    # ------------------------------------------------------------------
    def grant_temp(self, username: str, minutes: int = 10) -> None:
        key = str(username or "").lower().strip().lstrip("@")
        if key:
            self._temp_permits[key] = time.time() + minutes * 60

    def clear_temp(self, username: str) -> None:
        self._temp_permits.pop(str(username or "").lower().strip().lstrip("@"), None)

    def _is_temp_permitted(self, user: ChatUser | str) -> bool:
        now = time.time()
        for key in self._temp_keys(user):
            exp = self._temp_permits.get(key)
            if exp is None:
                continue
            if exp < now:
                del self._temp_permits[key]
                continue
            return True
        return False

    def is_admin(self, user: ChatUser | str) -> bool:
        return bool(self.identity_keys(user) & self.admins)

    def is_mod(self, user: ChatUser | str) -> bool:
        return bool(self.identity_keys(user) & self.mods) or self._is_temp_permitted(user)

    def has_permission(self, user: ChatUser | str, required: PermissionLevel | str) -> bool:
        if isinstance(required, str):
            required = PermissionLevel(required.lower())

        if required == PermissionLevel.PUBLIC:
            return True

        if isinstance(user, ChatUser):
            self._hint_youtube(user)

        if self.is_admin(user):
            return True
        if required == PermissionLevel.ADMIN:
            return False

        return self.is_mod(user)

    def effective_level(self, user: ChatUser | str) -> PermissionLevel:
        if self.is_admin(user):
            return PermissionLevel.ADMIN
        if self.is_mod(user):
            return PermissionLevel.MOD
        return PermissionLevel.PUBLIC
