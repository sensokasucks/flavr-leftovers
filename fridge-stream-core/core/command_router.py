"""
Command loading, matching, permission checks, and template rendering.

Platform-agnostic. Adapters just hand ChatEvents to Core; this module
decides whether they become ExecuteRequests that get sent to games.
"""

from __future__ import annotations

import json
import logging
from pathlib import Path
from typing import Dict, List, Optional, Tuple

from .models import (
    ChatEvent,
    CommandDefinition,
    ExecuteRequest,
    PermissionLevel,
    Platform,
)
from .permissions import PermissionManager

log = logging.getLogger("core.commands")


class CommandRouter:
    def __init__(
        self,
        commands_path: Path | str,
        permission_manager: PermissionManager,
        command_prefix: str = "!",
        default_player: str = "Player",
    ):
        self.prefix = command_prefix
        self.player = default_player
        self.perms = permission_manager
        self.commands: Dict[str, CommandDefinition] = {}
        self._load(commands_path)

    def _load(self, path: Path | str) -> None:
        path = Path(path)
        if not path.exists():
            log.warning("commands file not found: %s", path)
            return

        raw = json.loads(path.read_text(encoding="utf-8"))
        for name, data in raw.items():
            perm = data.get("permission", "public")
            try:
                perm_level = PermissionLevel(perm.lower())
            except ValueError:
                perm_level = PermissionLevel.PUBLIC

            cmd = CommandDefinition(
                name=name.lower(),
                aliases=[a.lower() for a in data.get("aliases", [])],
                permission=perm_level,
                description=data.get("description", ""),
                args=data.get("args", []),
                template=data.get("template", ""),
                qty_template=data.get("qtyTemplate") or data.get("qty_template"),
                default_qty=int(data.get("defaultQty", data.get("default_qty", 1))),
                max_qty=int(data.get("maxQty", data.get("max_qty", 8))),
                default_seconds=int(data.get("defaultSeconds", data.get("default_seconds", 30))),
                max_seconds=int(data.get("maxSeconds", data.get("max_seconds", 120))),
                allowed_values=[str(v).lower() for v in data.get("allowedValues", data.get("allowed_values", []))],
                cost=int(data.get("cost", 0)),
                special=data.get("special"),
                examples=data.get("examples", []),
                enabled=bool(data.get("enabled", True)),
            )
            self.commands[cmd.name] = cmd
            for alias in cmd.aliases:
                # aliases point at the same object
                self.commands[alias] = cmd

        log.info("Loaded %d command definitions", len({c.name for c in self.commands.values()}))

    def find(self, name: str) -> Optional[CommandDefinition]:
        return self.commands.get(name.lower())

    def parse_message(self, event: ChatEvent) -> bool:
        """
        Mutates the ChatEvent in-place: sets is_command, command_name, args.
        Returns True if it looks like a command (starts with prefix).
        """
        text = (event.message or "").strip()
        if not text.startswith(self.prefix):
            return False

        parts = text[len(self.prefix):].strip().split()
        if not parts:
            return False

        event.is_command = True
        event.command_name = parts[0].lower()
        event.args = parts[1:]
        return True

    def try_execute(self, event: ChatEvent) -> Tuple[Optional[ExecuteRequest], Optional[str]]:
        """
        Full pipeline for a single chat event that already looks like a command.

        Returns (ExecuteRequest, None) on success
                (None, reason_string) on rejection
        """
        if not event.is_command or not event.command_name:
            return None, "not a command"

        # Built-in !permit (admin only)
        if event.command_name == "permit":
            if not self.perms.has_permission(event.user, PermissionLevel.ADMIN):
                return None, "no permission for permit"
            target = (event.args[0] if event.args else "").lower()
            minutes = 10
            if len(event.args) >= 2:
                try:
                    minutes = max(1, min(120, int(event.args[1])))
                except ValueError:
                    pass
            if target:
                self.perms.grant_temp(target, minutes)
                log.info("Temp permit: %s for %d min (by %s)", target, minutes, event.user.username)
            return None, "permit handled"  # not forwarded to game

        cmd = self.find(event.command_name)
        if not cmd or not cmd.enabled:
            return None, "unknown command"

        if not self.perms.has_permission(event.user, cmd.permission):
            return None, f"requires {cmd.permission.value}"

        # Cost gate (future Channel Points / Super Chat). For now just check field.
        # Real deduction will live in the platform adapters later.
        if cmd.cost > 0 and not event.is_paid:
            # still allow if the user is admin (testing convenience)
            if not self.perms.has_permission(event.user, PermissionLevel.ADMIN):
                return None, f"requires cost {cmd.cost}"

        # Build template context
        qty = cmd.default_qty
        seconds = cmd.default_seconds
        args = list(event.args)

        # Heuristic: if first arg looks like a number and the command has qty, treat it as qty
        if args and cmd.args and any("qty" in a for a in cmd.args):
            try:
                maybe_qty = int(args[-1])
                if 1 <= maybe_qty <= cmd.max_qty:
                    qty = maybe_qty
                    args = args[:-1]
            except ValueError:
                pass

        if args and any("sec" in a for a in cmd.args):
            try:
                maybe_sec = int(args[-1])
                if 1 <= maybe_sec <= cmd.max_seconds:
                    seconds = maybe_sec
                    args = args[:-1]
            except ValueError:
                pass

        # allowed_values check (e.g. weather clear/rain)
        if cmd.allowed_values and args:
            if args[0].lower() not in cmd.allowed_values:
                return None, f"invalid value, allowed: {cmd.allowed_values}"

        # Render template
        ctx = {
            "player": self.player,
            "qty": str(qty),
            "seconds": str(seconds),
            "arg1": args[0] if len(args) > 0 else "",
            "arg2": args[1] if len(args) > 1 else "",
            "arg3": args[2] if len(args) > 2 else "",
            "user": event.user.username,
            "display_name": event.user.display_name,
        }

        template = cmd.template
        if qty > 1 and cmd.qty_template:
            template = cmd.qty_template

        try:
            rendered = template.format(**ctx)
        except KeyError as e:
            log.error("Template missing key %s for command %s", e, cmd.name)
            return None, "template error"

        req = ExecuteRequest(
            command_name=cmd.name,
            template=rendered,
            args=args,
            qty=qty,
            user=event.user,
            original_message=event.message,
            platform=event.platform,
            special=cmd.special,
            cost=cmd.cost,
            metadata={"seconds": seconds},
        )
        return req, None
