"""CSV exports that are safe to open in Excel / LibreOffice.

Chat text ends up in exports. A cell that starts with = + - @ (or a tab / carriage
return) is run as a formula by spreadsheet apps, so a chatter could type
=HYPERLINK(...) and have it run on the streamer's PC. Such cells get a leading
apostrophe, which spreadsheets show as plain text.
"""

from __future__ import annotations

import csv
from typing import Any, Iterable

FORMULA_START = ("=", "+", "-", "@", "\t", "\r")


def safe_cell(value: Any) -> Any:
    if isinstance(value, str) and value.startswith(FORMULA_START):
        return "'" + value
    return value


class SafeWriter:
    """csv.writer that defuses formula cells (numbers are left alone)."""

    def __init__(self, buf, **kwargs) -> None:
        self._w = csv.writer(buf, **kwargs)

    def writerow(self, row: Iterable[Any]) -> Any:
        return self._w.writerow([safe_cell(v) for v in row])
