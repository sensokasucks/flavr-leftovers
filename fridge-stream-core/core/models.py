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


class PermissionLevel(str, Enum):
    PUBLIC = "public"
    MOD = "mod"
    ADMIN = "admin"


@dataclass
class ChatUser:
    platform: Platform
    id: str
    username: str
    display_name: str = ""
    is_mod: bool = False
    is_vip: bool = False
    is_subscriber: bool = False
    badges: list[str] = field(default_factory=list)
    color: Optional[str] = None          # hex if available
    profile_image_url: Optional[str] = None

    def __post_init__(self):
        if not self.display_name:
            self.display_name = self.username
        # normalize username for permission lookups
        self.username = (self.username or "").lower().strip()

    def to_dict(self) -> dict:
        d = asdict(self)
        d["platform"] = self.platform.value
        return d


@dataclass
class ChatEvent:
    """Normalized chat message from any platform."""
    platform: Platform
    user: ChatUser
    message: str
    timestamp: float = field(default_factory=time.time)
    message_id: Optional[str] = None
    raw: dict = field(default_factory=dict)

    # Parsed command fields (filled by Core after routing)
    is_command: bool = False
    command_name: Optional[str] = None
    args: list[str] = field(default_factory=list)

    # Monetization (Channel Points / Super Chat / etc.)
    paid_amount: Optional[float] = None
    paid_currency: Optional[str] = None
    is_paid: bool = False
    reward_id: Optional[str] = None      # platform-specific reward/redemption id
    reward_title: Optional[str] = None

    def to_dict(self) -> dict:
        d = asdict(self)
        d["platform"] = self.platform.value
        d["user"] = self.user.to_dict()
        return d


@dataclass
class MetricsSnapshot:
    """Aggregated live metrics that game integrations and overlays consume."""
    viewers: int = 0                     # total or primary platform
    viewers_by_platform: dict[str, int] = field(default_factory=dict)
    cpm: float = 0.0                     # chat messages per minute (windowed)
    command_rate: float = 0.0            # successful commands in window
    power_level: int = 0                 # 0–15, same scale as Chat Dynamo
    timestamp: float = field(default_factory=time.time)

    def to_dict(self) -> dict:
        return asdict(self)


@dataclass
class CommandDefinition:
    """Loaded from config/commands.json. Platform-agnostic."""
    name: str
    aliases: list[str] = field(default_factory=list)
    permission: PermissionLevel = PermissionLevel.PUBLIC
    description: str = ""
    args: list[str] = field(default_factory=list)
    template: str = ""                   # e.g. "execute at {player} run summon {arg1} ..."
    qty_template: Optional[str] = None
    default_qty: int = 1
    max_qty: int = 8
    default_seconds: int = 30
    max_seconds: int = 120
    allowed_values: list[str] = field(default_factory=list)
    cost: int = 0                        # channel points / equivalent cost
    special: Optional[str] = None        # e.g. "show_inventory"
    examples: list[str] = field(default_factory=list)
    enabled: bool = True
    # Optional per-platform overrides later if needed
    platform_overrides: dict[str, Any] = field(default_factory=dict)

    def matches(self, name: str) -> bool:
        n = name.lower()
        return n == self.name.lower() or n in [a.lower() for a in self.aliases]


@dataclass
class ExecuteRequest:
    """What Core sends to a game integration when a command is approved."""
    command_name: str
    template: str                        # fully rendered command string or action
    args: list[str]
    qty: int = 1
    user: ChatUser | None = None
    original_message: str = ""
    platform: Platform = Platform.KICK
    special: Optional[str] = None
    cost: int = 0
    metadata: dict = field(default_factory=dict)

    def to_dict(self) -> dict:
        d = asdict(self)
        d["platform"] = self.platform.value
        if self.user:
            d["user"] = self.user.to_dict()
        return d
