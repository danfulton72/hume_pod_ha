"""Diagnostics for the Hume Body Pod."""

from __future__ import annotations

from typing import Any

from homeassistant.components.diagnostics import async_redact_data
from homeassistant.const import CONF_ADDRESS
from homeassistant.core import HomeAssistant

from . import HumePodConfigEntry
from .const import CONF_BIRTHDATE

TO_REDACT = {CONF_ADDRESS, CONF_BIRTHDATE, "title", "unique_id"}


async def async_get_config_entry_diagnostics(
    hass: HomeAssistant, entry: HumePodConfigEntry
) -> dict[str, Any]:
    scale = entry.runtime_data
    return {
        # as_dict() includes the person subentries; names and birthdates are redacted.
        "entry": async_redact_data(entry.as_dict(), TO_REDACT),
        "scale": scale.diagnostics(),
    }
