"""The admin token can't be blanked or reset from the dashboard, and isn't printed whole.

    python -m pytest tests/test_admin_token.py -q
"""

from __future__ import annotations

import copy
import logging
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

import main  # noqa: E402
from api import admin_routes  # noqa: E402
from api.server import CoreState  # noqa: E402
from core.config import DEFAULTS, _deep_merge  # noqa: E402

TOKEN = "tok-123456789abc"


class KeepTokenTests(unittest.TestCase):
    def _put(self, form_points):
        from fastapi import FastAPI
        from fastapi.testclient import TestClient

        state = CoreState()
        state.config = _deep_merge(DEFAULTS, {"points": {"admin_token": TOKEN}})
        saved = {}

        def fake_save(cfg):
            saved.update(copy.deepcopy(cfg))
            return Path("config.yaml")

        app = FastAPI()
        app.include_router(admin_routes.create_admin_router(state))
        client = TestClient(app)
        form = copy.deepcopy(state.config)
        if form_points is None:
            form.pop("points")
        else:
            form["points"] = {**form["points"], **form_points}
        with mock.patch.object(admin_routes, "save_config", side_effect=fake_save), \
                mock.patch.object(admin_routes, "load_config", side_effect=lambda: copy.deepcopy(saved)):
            res = client.put("/api/admin/config", json={"config": form}, headers={"X-Admin-Token": TOKEN})
        self.assertEqual(res.status_code, 200, res.text)
        return saved["points"]["admin_token"]

    def test_reset_to_change_me_keeps_token(self):
        self.assertEqual(self._put({"admin_token": "change-me"}), TOKEN)

    def test_blank_keeps_token(self):
        self.assertEqual(self._put({"admin_token": ""}), TOKEN)

    def test_missing_points_section_keeps_token(self):
        self.assertEqual(self._put(None), TOKEN)

    def test_new_real_token_is_saved(self):
        self.assertEqual(self._put({"admin_token": "my-new-token-42"}), "my-new-token-42")


class AnnounceTests(unittest.TestCase):
    def test_log_masks_token_and_shortcut_signs_in(self):
        with tempfile.TemporaryDirectory() as tmp, mock.patch.object(main, "ROOT", Path(tmp)):
            cfg = _deep_merge(DEFAULTS, {"points": {"admin_token": TOKEN}})
            with self.assertLogs("main", level=logging.INFO) as logs:
                link = main.announce_dashboard(cfg, "0.0.0.0", 3850)
            text = "\n".join(logs.output)
            self.assertNotIn(TOKEN, text)
            self.assertIn("http://127.0.0.1:3850/admin/", text)
            self.assertIn("tok-…", text)
            self.assertEqual(link, f"http://127.0.0.1:3850/admin/#token={TOKEN}")
            shortcut = (Path(tmp) / "data" / "Open dashboard.url").read_text(encoding="utf-8")
            self.assertIn(f"URL={link}", shortcut)


if __name__ == "__main__":
    unittest.main()
