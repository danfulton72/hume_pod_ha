"""Config flow for the Hume Body Pod integration."""

from __future__ import annotations

from typing import Any

import voluptuous as vol

from homeassistant.components.bluetooth import (
    BluetoothServiceInfoBleak,
    async_discovered_service_info,
)
from homeassistant.config_entries import ConfigFlow, ConfigFlowResult, OptionsFlow
from homeassistant.const import CONF_ADDRESS, CONF_NAME
from homeassistant.core import callback
from homeassistant.helpers import selector

from .const import (
    ACTIVITY_LEVELS,
    CONF_ACTIVITY,
    CONF_BIRTHDATE,
    CONF_HEIGHT,
    CONF_SEX,
    DOMAIN,
    SEX_FEMALE,
    SEX_MALE,
)
from .protocol import SERVICE_UUID

NAME_PREFIXES = ("body pod", "hume")


def _is_body_pod(info: BluetoothServiceInfoBleak) -> bool:
    name = (info.name or "").lower()
    return name.startswith(NAME_PREFIXES) or (
        SERVICE_UUID in info.service_uuids and name.startswith("pod")
    )


def _profile_schema(defaults: dict[str, Any]) -> vol.Schema:
    return vol.Schema(
        {
            vol.Required(CONF_SEX, default=defaults.get(CONF_SEX, SEX_MALE)): selector.SelectSelector(
                selector.SelectSelectorConfig(
                    options=[SEX_MALE, SEX_FEMALE], translation_key=CONF_SEX
                )
            ),
            vol.Required(
                CONF_BIRTHDATE, default=defaults.get(CONF_BIRTHDATE, vol.UNDEFINED)
            ): selector.DateSelector(),
            vol.Required(CONF_HEIGHT, default=defaults.get(CONF_HEIGHT, 175)): selector.NumberSelector(
                selector.NumberSelectorConfig(
                    min=100, max=250, step=1, unit_of_measurement="cm",
                    mode=selector.NumberSelectorMode.BOX,
                )
            ),
            vol.Required(
                CONF_ACTIVITY, default=defaults.get(CONF_ACTIVITY, "moderate")
            ): selector.SelectSelector(
                selector.SelectSelectorConfig(
                    options=ACTIVITY_LEVELS, translation_key=CONF_ACTIVITY
                )
            ),
        }
    )


class HumePodConfigFlow(ConfigFlow, domain=DOMAIN):
    VERSION = 1

    def __init__(self) -> None:
        self._address: str | None = None
        self._device_name: str | None = None
        self._discovered: dict[str, str] = {}

    async def async_step_bluetooth(
        self, discovery_info: BluetoothServiceInfoBleak
    ) -> ConfigFlowResult:
        await self.async_set_unique_id(discovery_info.address)
        self._abort_if_unique_id_configured()
        self._address = discovery_info.address
        self._device_name = discovery_info.name or "Body Pod"
        self.context["title_placeholders"] = {"name": self._device_name}
        return await self.async_step_bluetooth_confirm()

    async def async_step_bluetooth_confirm(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        if user_input is not None:
            return await self.async_step_profile()
        self._set_confirm_only()
        return self.async_show_form(
            step_id="bluetooth_confirm",
            description_placeholders={"name": self._device_name or "Body Pod"},
        )

    async def async_step_user(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        if user_input is not None:
            address = user_input[CONF_ADDRESS]
            await self.async_set_unique_id(address, raise_on_progress=False)
            self._abort_if_unique_id_configured()
            self._address = address
            self._device_name = self._discovered.get(address, "Body Pod")
            return await self.async_step_profile()

        configured = self._async_current_ids(include_ignore=False)
        for info in async_discovered_service_info(self.hass, connectable=True):
            if info.address in configured or not _is_body_pod(info):
                continue
            self._discovered[info.address] = f"{info.name} ({info.address})"

        if not self._discovered:
            return self.async_abort(reason="no_devices_found")

        return self.async_show_form(
            step_id="user",
            data_schema=vol.Schema({vol.Required(CONF_ADDRESS): vol.In(self._discovered)}),
        )

    async def async_step_profile(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        if user_input is not None:
            person = user_input.pop(CONF_NAME)
            return self.async_create_entry(
                title=f"Body Pod ({person})",
                data={CONF_ADDRESS: self._address, CONF_NAME: person},
                options=user_input,
            )
        schema = vol.Schema({vol.Required(CONF_NAME): str}).extend(_profile_schema({}).schema)
        return self.async_show_form(step_id="profile", data_schema=schema)

    @staticmethod
    @callback
    def async_get_options_flow(config_entry) -> HumePodOptionsFlow:
        return HumePodOptionsFlow()


class HumePodOptionsFlow(OptionsFlow):
    """Edit the body profile used for BIA calculations."""

    async def async_step_init(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        if user_input is not None:
            return self.async_create_entry(data=user_input)
        return self.async_show_form(
            step_id="init", data_schema=_profile_schema(dict(self.config_entry.options))
        )
