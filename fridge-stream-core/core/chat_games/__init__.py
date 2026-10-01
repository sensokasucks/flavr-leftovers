"""Chat games and crowd moments (config block `chat_games:`, docs/CHAT_GAMES.md)."""

from .config import DEFAULTS, FORM, normalize_config
from .engine import ChatGames

__all__ = ["ChatGames", "DEFAULTS", "FORM", "normalize_config"]
