"""Constants for Mealie Browser."""

from __future__ import annotations

import logging
from pathlib import Path

DOMAIN = "mealie_browser"
LOGGER = logging.getLogger(__package__)

# Action
SERVICE_OPEN_RECIPE_BY_VOICE = "open_recipe_by_voice"
ATTR_TEXT = "text"

# Frontend card, served by the integration itself
CARD_FILENAME = "mealie-browser-card.js"
CARD_PATH = Path(__file__).parent / "www" / CARD_FILENAME
CARD_URL = f"/{DOMAIN}/{CARD_FILENAME}"

# HTTP proxy
API_BASE = f"/api/{DOMAIN}"
REQUEST_TIMEOUT = 10

# How long a target pushed by the action waits for a card to pick it up
# (the tablet may still be waking up / navigating when the action runs).
PENDING_TARGET_TTL = 60
