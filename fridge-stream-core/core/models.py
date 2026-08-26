"""
Shared data models for Stream Core.

All platform adapters normalize into these types so the rest of the
system never cares which platform a message came from.
"""

from __future__ import annotations

from dataclasses import dataclass, field, asdict
from enum import Enum
from typing import Any, Optional
import time


class Platform(str, Enum):
    KICK = "kick"
    YOUTUBE = "youtube"
    TWITCH = "twitch"
    SYSTEM = "system"


class PermissionLevel(str, Enum):
    PUBLIC = "public"
    SUB = "sub"
    VIP = "vip"
    MOD = "mod"
    ADMIN = "admin"


@dataclass
class ChatUser:
    username: str
    display_name: str = ""
    user_id: str = ""
    id: str = ""
    platform: Platform = Platform.KICK
    is_mod: bool = False
    is_subscriber: bool = False
    is_vip: bool = False
    is_broadcaster: bool = False
    badges: list[str] = field(default_factory=list)
    color: str = ""

    def __post_init__(self) -> None:
        if not self.display_name:
            self.display_name = self.username
        if not self.id and self.user_id:
            self.id = self.user_id
        if not self.user_id and self.id:
            self.user_id = self.id


@dataclass
class ChatEvent:
    user: ChatUser
    message: str
    platform: Platform
    raw: Any = None
    ts: float = field(default_factory=time.time)
    timestamp: float = 0.0
    is_command: bool = False
    command_name: str = ""
    args: list[str] = field(default_factory=list)
    message_id: str = ""
    emotes: list[dict] = field(default_factory=list)
    paid: bool = False
    is_paid: bool = False
    paid_amount: Any = None
    paid_currency: str = ""

    def __post_init__(self) -> None:
        if not self.timestamp:
            self.timestamp = self.ts
        else:
            self.ts = self.timestamp
        if self.is_paid and not self.paid:
            self.paid = True
        if self.paid and not self.is_paid:
            self.is_paid = True


@dataclass
class CommandDefinition:
    name: str
    aliases: list[str] = field(default_factory=list)
    permission: PermissionLevel = PermissionLevel.PUBLIC
    description: str = ""
    args: list[str] = field(default_factory=list)
    template: str = ""
    qty_template: Optional[str] = None
    default_qty: int = 1
    max_qty: int = 8
    default_seconds: int = 30
    max_seconds: int = 120
    allowed_values: list[str] = field(default_factory=list)
    cost: int = 0
    special: Any = None
    examples: list[str] = field(default_factory=list)
    enabled: bool = True
    group: str = "core"


@dataclass
class ExecuteRequest:
    command: str = ""
    command_name: str = ""
    args: list[str] = field(default_factory=list)
    quantity: int = 1
    qty: int = 1
    seconds: int = 0
    user: Optional[ChatUser] = None
    platform: Platform = Platform.SYSTEM
    template: str = ""
    original_message: str = ""
    special: Any = None
    cost: int = 0
    meta: dict = field(default_factory=dict)
    metadata: dict = field(default_factory=dict)

    def __post_init__(self) -> None:
        if self.command_name and not self.command:
            self.command = self.command_name
        if self.command and not self.command_name:
            self.command_name = self.command
        if self.qty and self.quantity == 1:
            self.quantity = self.qty
        if self.quantity and self.qty == 1:
            self.qty = self.quantity
        if self.metadata and not self.meta:
            self.meta = self.metadata
        if self.meta and not self.metadata:
            self.metadata = self.meta
        if self.metadata.get("seconds") and not self.seconds:
            try:
                self.seconds = int(self.metadata["seconds"])
            except (TypeError, ValueError):
                pass


@dataclass
class MetricsSnapshot:
    viewers: int = 0
    viewers_by_platform: dict = field(default_factory=dict)
    cpm: float = 0.0
    command_rate: float = 0.0
    power_level: int = 0
    ts: float = field(default_factory=time.time)

    def to_dict(self) -> dict:
        return asdict(self)
