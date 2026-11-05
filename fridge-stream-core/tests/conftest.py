"""Shared pytest setup for Core's tests.

Every test that signs in to the admin API goes through admin_routes._auth, which notes the
first good sign-in in data/dashboard_signed_in (core/dashboard_signin.mark_signed_in). Tests run
inside the real Core folder, so that note would land in the streamer's own data folder and stop
Core opening the dashboard on its first start. Mark it as already done for the whole test run;
tests/test_dashboard_signin.py resets it where it checks the note itself.
"""

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from core import dashboard_signin  # noqa: E402

dashboard_signin._marked = True
