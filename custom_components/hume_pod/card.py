"""Serve the Body Pod dashboard card and load it into the HA frontend."""

from __future__ import annotations

import logging
from pathlib import Path

from homeassistant.components.http import StaticPathConfig
from homeassistant.core import HomeAssistant
from homeassistant.loader import async_get_integration

from .const import CARD_FILENAME, DOMAIN, FRONTEND_URL_BASE

_LOGGER = logging.getLogger(__name__)

FRONTEND_DIR = Path(__file__).parent / "frontend"


async def async_register_card(hass: HomeAssistant) -> None:
    """Expose the card's JS and add it to every dashboard, no resource setup needed."""
    if getattr(hass, "http", None) is None:  # e.g. tests without the http component
        return

    await hass.http.async_register_static_paths(
        [StaticPathConfig(FRONTEND_URL_BASE, str(FRONTEND_DIR), cache_headers=True)]
    )

    if "frontend" not in hass.config.components:
        _LOGGER.debug("Frontend not loaded; add %s as a dashboard resource", CARD_FILENAME)
        return

    # Imported lazily: the frontend package is only present when the UI is.
    from homeassistant.components.frontend import add_extra_js_url  # noqa: PLC0415

    version = (await async_get_integration(hass, DOMAIN)).version
    add_extra_js_url(hass, f"{FRONTEND_URL_BASE}/{CARD_FILENAME}?v={version}")
