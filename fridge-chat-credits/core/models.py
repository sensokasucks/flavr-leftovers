"""Normalized chat types shared by every adapter."""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from enum import Enum
from typing import Any, Optional
import time


class Platform(str, Enum):
    KICK = "kick"
    TWITCH = "twitch"
    YOUTUBE = "youtube"
    MANUAL = "manual"


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
    color: Optional[str] = None

    def __post_init__(self):
        if not self.display_name:
            self.display_name = self.username
        self.username = (self.username or "").lower().strip()

    def to_dict(self) -> dict:
        d = asdict(self)
        d["platform"] = self.platform.value
        return d


@dataclass
class ChatEvent:
    platform: Platform
    user: ChatUser
    message: str
    timestamp: float = field(default_factory=time.time)
    message_id: Optional[str] = None
    raw: dict = field(default_factory=dict)

    def to_dict(self) -> dict:
        d = asdict(self)
        d["platform"] = self.platform.value
        d["user"] = self.user.to_dict()
        return d


@dataclass
class Chatter:
    """One unique person on one platform for this session."""

    platform: str
    username: str
    display_name: str
    first_seen: float
    last_seen: float
    messages: int = 1
    color: Optional[str] = None
    is_mod: bool = False
    is_vip: bool = False
    is_subscriber: bool = False

    @property
    def key(self) -> str:
        return f"{self.platform}:{self.username}"

    def to_dict(self) -> dict:
        return asdict(self)

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "Chatter":
        return cls(
            platform=str(data.get("platform") or ""),
            username=str(data.get("username") or ""),
            display_name=str(data.get("display_name") or data.get("username") or ""),
            first_seen=float(data.get("first_seen") or 0),
            last_seen=float(data.get("last_seen") or 0),
            messages=int(data.get("messages") or 1),
            color=data.get("color"),
            is_mod=bool(data.get("is_mod")),
            is_vip=bool(data.get("is_vip")),
            is_subscriber=bool(data.get("is_subscriber")),
        )
