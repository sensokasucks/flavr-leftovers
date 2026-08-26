"""Cross-platform permission checks (admin / mod / public)."""

from __future__ import annotations

from typing import Iterable, Set, Union

from .models import ChatUser, PermissionLevel


def _norm_list(values: Iterable[str] | str | None) -> Set[str]:
    if values is None:
        return set()
    if isinstance(values, str):
        values = [values]
    return {str(v).strip().lower() for v in values if str(v).strip()}


class Permissions:
    def __init__(self, config: dict | None = None) -> None:
        perms = (config or {}).get("permissions") or {}
        self.admins = _norm_list(perms.get("admin"))
        self.mods = _norm_list(perms.get("mod"))
        self._permits: dict[str, float] = {}

    def reload(self, config: dict | None) -> None:
        perms = (config or {}).get("permissions") or {}
        self.admins = _norm_list(perms.get("admin"))
        self.mods = _norm_list(perms.get("mod"))

    def permit(self, username: str, minutes: float = 5.0) -> None:
        import time
        self._permits[username.strip().lower()] = time.time() + max(0.1, minutes) * 60.0

    def grant_temp(self, username: str, minutes: float = 5.0) -> None:
        self.permit(username, minutes)

    def _has_permit(self, username: str) -> bool:
        import time
        key = username.strip().lower()
        exp = self._permits.get(key)
        if exp is None:
            return False
        if time.time() > exp:
            self._permits.pop(key, None)
            return False
        return True

    def role_of(self, user: ChatUser) -> str:
        name = (user.username or "").strip().lower()
        if name in self.admins or getattr(user, "is_broadcaster", False):
            return "admin"
        if name in self.mods or getattr(user, "is_mod", False):
            return "mod"
        if self._has_permit(name):
            return "mod"
        return "public"

    def allows(self, user: ChatUser, required: str) -> bool:
        order = {"public": 0, "sub": 0, "vip": 1, "mod": 1, "admin": 2}
        have = order.get(self.role_of(user), 0)
        need = order.get((required or "public").lower(), 0)
        return have >= need

    def has_permission(self, user: ChatUser, required: Union[str, PermissionLevel]) -> bool:
        if isinstance(required, PermissionLevel):
            required = required.value
        return self.allows(user, str(required or "public"))


class PermissionManager(Permissions):
    """Alias used by main.py / CommandRouter."""


__all__ = ["Permissions", "PermissionManager"]
