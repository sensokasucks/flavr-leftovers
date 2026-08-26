"""Game integrations registered with Stream Core.

Add a new game by:
  1. Implementing BaseGameIntegration in games/<id>.py
  2. Listing the id here
  3. Starting it from main.py when config.<id>.enabled is true
"""

KNOWN_GAMES = ("minecraft", "factorio")
