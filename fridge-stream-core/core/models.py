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


@dataclass
class ChatUser:
    username: str
    display_name: str = ""
    user_id: str = ""
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


@dataclass
class ChatEvent:
    user: ChatUser
    message: str
    platform: Platform
    raw: Any = None
    ts: float = field(default_factory=time.time)
    is_command: bool = False
    message_id: str = ""
    emotes: list[dict] = field(default_factory=list)
    paid: bool = False
    paid_amount: Any = None
    paid_currency: str = ""


@dataclass
class ExecuteRequest:
    command: str
    args: list[str] = field(default_factory=list)
    quantity: int = 1
    seconds: int = 0
    user: Optional[ChatUser] = None
    platform: Platform = Platform.SYSTEM
    template: str = ""
    meta: dict = field(default_factory=dict)


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
