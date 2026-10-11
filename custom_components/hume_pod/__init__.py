"""The Hume Body Pod integration."""

from __future__ import annotations

from homeassistant.components import bluetooth
from homeassistant.config_entries import ConfigEntry, ConfigEntryState
from homeassistant.const import Platform
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import ConfigEntryNotReady
from homeassistant.helpers import config_validation as cv
from homeassistant.helpers.dispatcher import async_dispatcher_send
from homeassistant.helpers.typing import ConfigType

from .card import async_register_card
from .const import DOMAIN, SIGNAL_UPDATED
from .scale import HumePodScale
from .services import async_setup_services
from .websocket import async_setup_websocket

PLATFORMS: list[Platform] = [Platform.SENSOR]

CONFIG_SCHEMA = cv.config_entry_only_config_schema(DOMAIN)

type HumePodConfigEntry = ConfigEntry[HumePodScale]


async def async_setup(hass: HomeAssistant, config: ConfigType) -> bool:
    async_setup_services(hass)
    async_setup_websocket(hass)
    await async_register_card(hass)
    return True


async def async_setup_entry(hass: HomeAssistant, entry: HumePodConfigEntry) -> bool:
    if not bluetooth.async_scanner_count(hass, connectable=True):
        raise ConfigEntryNotReady(translation_domain=DOMAIN, translation_key="no_scanner")

    scale = HumePodScale(hass, entry)
    await scale.async_load()
    entry.runtime_data = scale

    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)
    entry.async_on_unload(scale.async_start())
    # People (subentries) added/removed or options changed -> rebuild entities.
    entry.async_on_unload(entry.add_update_listener(_async_reload))
    async_dispatcher_send(hass, SIGNAL_UPDATED)  # tell open dashboards
    return True


async def _async_reload(hass: HomeAssistant, entry: HumePodConfigEntry) -> None:
    if entry.state is ConfigEntryState.LOADED:
        hass.config_entries.async_schedule_reload(entry.entry_id)


async def async_unload_entry(hass: HomeAssistant, entry: HumePodConfigEntry) -> bool:
    if unloaded := await hass.config_entries.async_unload_platforms(entry, PLATFORMS):
        await entry.runtime_data.async_flush()
        # Once the entry is marked unloaded, refresh open dashboards.
        hass.loop.call_soon(async_dispatcher_send, hass, SIGNAL_UPDATED)
    return unloaded


async def async_remove_entry(hass: HomeAssistant, entry: HumePodConfigEntry) -> None:
    """Delete stored weigh-in history when the scale is removed."""
    await HumePodScale(hass, entry).async_remove_store()
