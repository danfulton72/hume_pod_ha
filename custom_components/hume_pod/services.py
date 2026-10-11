"""Services for handling weigh-ins the integration couldn't attribute."""

from __future__ import annotations

from typing import TYPE_CHECKING

from homeassistant.config_entries import ConfigEntryState
from homeassistant.core import HomeAssistant, ServiceCall, callback
from homeassistant.exceptions import ServiceValidationError
from homeassistant.helpers import config_validation as cv, device_registry as dr
import voluptuous as vol

from .const import ATTR_PERSON, ATTR_SCALE, DOMAIN, SERVICE_ASSIGN, SERVICE_DISCARD

if TYPE_CHECKING:
    from .scale import HumePodScale

ASSIGN_SCHEMA = vol.Schema({vol.Required(ATTR_PERSON): cv.string})
DISCARD_SCHEMA = vol.Schema({vol.Required(ATTR_SCALE): cv.string})


def _resolve(hass: HomeAssistant, device_id: str) -> tuple[HumePodScale, str | None]:
    """Map a device to (scale, person subentry id or None for the scale device)."""
    device = dr.async_get(hass).async_get(device_id)
    if device:
        for entry_id, subentry_ids in device.config_entries_subentries.items():
            entry = hass.config_entries.async_get_entry(entry_id)
            if entry is None or entry.domain != DOMAIN:
                continue
            if entry.state is not ConfigEntryState.LOADED:
                raise ServiceValidationError(
                    translation_domain=DOMAIN, translation_key="scale_not_loaded"
                )
            return entry.runtime_data, next(iter(subentry_ids), None)
    raise ServiceValidationError(translation_domain=DOMAIN, translation_key="unknown_device")


@callback
def async_setup_services(hass: HomeAssistant) -> None:
    async def assign(call: ServiceCall) -> None:
        scale, person_id = _resolve(hass, call.data[ATTR_PERSON])
        if person_id is None:
            raise ServiceValidationError(translation_domain=DOMAIN, translation_key="not_a_person")
        scale.async_assign_pending(person_id)

    async def discard(call: ServiceCall) -> None:
        scale, _ = _resolve(hass, call.data[ATTR_SCALE])
        scale.async_discard_pending()

    hass.services.async_register(DOMAIN, SERVICE_ASSIGN, assign, schema=ASSIGN_SCHEMA)
    hass.services.async_register(DOMAIN, SERVICE_DISCARD, discard, schema=DISCARD_SCHEMA)
