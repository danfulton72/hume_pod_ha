"""The Hume Body Pod integration."""

from __future__ import annotations

from homeassistant.components import bluetooth
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import CONF_ADDRESS, Platform
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import ConfigEntryNotReady

from .scale import HumePodScale

PLATFORMS: list[Platform] = [Platform.SENSOR]

type HumePodConfigEntry = ConfigEntry[HumePodScale]


async def async_setup_entry(hass: HomeAssistant, entry: HumePodConfigEntry) -> bool:
    address: str = entry.data[CONF_ADDRESS]

    if not bluetooth.async_scanner_count(hass, connectable=True):
        raise ConfigEntryNotReady(
            "No connectable Bluetooth adapter or proxy is available to reach the Body Pod"
        )

    scale = HumePodScale(hass, entry, address)
    entry.runtime_data = scale

    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)
    entry.async_on_unload(scale.async_start())
    entry.async_on_unload(entry.add_update_listener(_async_update_listener))
    return True


async def _async_update_listener(hass: HomeAssistant, entry: HumePodConfigEntry) -> None:
    """Profile changed in options: nothing to rebuild, the next weigh-in reads it."""
    entry.runtime_data._notify()  # noqa: SLF001


async def async_unload_entry(hass: HomeAssistant, entry: HumePodConfigEntry) -> bool:
    return await hass.config_entries.async_unload_platforms(entry, PLATFORMS)
