"""Config flow for the Hume Body Pod integration.

The config entry is the scale; each person who uses it is a "person"
subentry, added or edited from the integration page.
"""

from __future__ import annotations

from datetime import date
import re
from typing import Any

from homeassistant.components.bluetooth import (
    BluetoothServiceInfoBleak,
    async_discovered_service_info,
)
from homeassistant.config_entries import (
    ConfigEntry,
    ConfigEntryState,
    ConfigFlow,
    ConfigFlowResult,
    ConfigSubentryFlow,
    OptionsFlow,
    SubentryFlowResult,
)
from homeassistant.const import CONF_ADDRESS, CONF_NAME
from homeassistant.core import callback
from homeassistant.helpers import selector
from homeassistant.util import dt as dt_util
import voluptuous as vol

from .const import (
    ACTIVITY_LEVELS,
    CONF_ACTIVITY,
    CONF_BIRTHDATE,
    CONF_EXPECTED_WEIGHT,
    CONF_FAT_TOLERANCE,
    CONF_HEIGHT,
    CONF_SEX,
    CONF_WEIGHT_TOLERANCE,
    DEFAULT_FAT_TOLERANCE,
    DEFAULT_WEIGHT_TOLERANCE,
    DOMAIN,
    SEX_FEMALE,
    SEX_MALE,
    SUBENTRY_PERSON,
)
from .protocol import is_placeholder_name, looks_like_body_pod


def _is_body_pod(info: BluetoothServiceInfoBleak) -> bool:
    return looks_like_body_pod(info.name, info.address, info.service_uuids, info.manufacturer_data)


def _display_name(info: BluetoothServiceInfoBleak) -> str:
    return "Body Pod" if is_placeholder_name(info.name, info.address) else info.name


PERSON_SCHEMA = vol.Schema(
    {
        vol.Required(CONF_NAME): selector.TextSelector(),
        vol.Required(CONF_SEX): selector.SelectSelector(
            selector.SelectSelectorConfig(options=[SEX_MALE, SEX_FEMALE], translation_key=CONF_SEX)
        ),
        # A typed date field: the browser's own date input lets you type the
        # year (or pick it on a phone) instead of paging back month by month.
        vol.Required(CONF_BIRTHDATE): selector.TextSelector(
            selector.TextSelectorConfig(type=selector.TextSelectorType.DATE)
        ),
        vol.Required(CONF_HEIGHT): selector.NumberSelector(
            selector.NumberSelectorConfig(
                min=100,
                max=250,
                step=1,
                unit_of_measurement="cm",
                mode=selector.NumberSelectorMode.BOX,
            )
        ),
        vol.Required(CONF_ACTIVITY, default="moderate"): selector.SelectSelector(
            selector.SelectSelectorConfig(options=ACTIVITY_LEVELS, translation_key=CONF_ACTIVITY)
        ),
        vol.Optional(CONF_EXPECTED_WEIGHT): selector.NumberSelector(
            selector.NumberSelectorConfig(
                min=10,
                max=300,
                step=0.1,
                unit_of_measurement="kg",
                mode=selector.NumberSelectorMode.BOX,
            )
        ),
    }
)


_DMY = re.compile(r"^\s*(\d{1,2})[/.\-\s](\d{1,2})[/.\-\s](\d{4})\s*$")


def parse_birthdate(value: Any, today: date | None = None) -> str | None:
    """Return an ISO date for 1974-03-21 or 21/03/1974 style input, else None.

    Browsers without a native date input fall back to free text, so day-first
    dates (as written in the UK and most of the world) are accepted too.
    Implausible dates (future, or an age outside 5-120) are rejected.
    """
    text = str(value or "").strip()
    parsed = dt_util.parse_date(text)
    if parsed is None and (m := _DMY.match(text)):
        day, month, year = (int(g) for g in m.groups())
        try:
            parsed = date(year, month, day)
        except ValueError:
            return None
    if parsed is None:
        return None
    today = today or dt_util.now().date()
    age = today.year - parsed.year - ((today.month, today.day) < (parsed.month, parsed.day))
    if not 5 <= age <= 120:
        return None
    return parsed.isoformat()


def _split_person(user_input: dict[str, Any], errors: dict[str, str]) -> tuple[str, dict[str, Any]]:
    """Separate the name from the profile and normalise/validate the birthdate."""
    data = dict(user_input)
    name = data.pop(CONF_NAME).strip()
    if (birthdate := parse_birthdate(data.get(CONF_BIRTHDATE))) is None:
        errors[CONF_BIRTHDATE] = "invalid_birthdate"
    else:
        data[CONF_BIRTHDATE] = birthdate
    return name, data


class HumePodConfigFlow(ConfigFlow, domain=DOMAIN):
    VERSION = 1

    def __init__(self) -> None:
        self._address: str | None = None
        self._device_name: str | None = None
        self._discovered: dict[str, str] = {}

    @classmethod
    @callback
    def async_get_supported_subentry_types(
        cls, config_entry: ConfigEntry
    ) -> dict[str, type[ConfigSubentryFlow]]:
        return {SUBENTRY_PERSON: PersonSubentryFlow}

    @staticmethod
    @callback
    def async_get_options_flow(config_entry: ConfigEntry) -> HumePodOptionsFlow:
        return HumePodOptionsFlow()

    async def async_step_bluetooth(
        self, discovery_info: BluetoothServiceInfoBleak
    ) -> ConfigFlowResult:
        # The manifest matches any FFF0 device, which is a common service on
        # unrelated gadgets, so confirm it really is a Body Pod first.
        if not _is_body_pod(discovery_info):
            return self.async_abort(reason="not_supported")
        await self.async_set_unique_id(discovery_info.address)
        self._abort_if_unique_id_configured()
        self._address = discovery_info.address
        self._device_name = _display_name(discovery_info)
        self.context["title_placeholders"] = {"name": self._device_name}
        return await self.async_step_bluetooth_confirm()

    async def async_step_bluetooth_confirm(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        if user_input is not None:
            return await self.async_step_person()
        self._set_confirm_only()
        return self.async_show_form(
            step_id="bluetooth_confirm",
            description_placeholders={"name": self._device_name or "Body Pod"},
        )

    async def async_step_user(self, user_input: dict[str, Any] | None = None) -> ConfigFlowResult:
        if user_input is not None:
            address = user_input[CONF_ADDRESS]
            await self.async_set_unique_id(address, raise_on_progress=False)
            self._abort_if_unique_id_configured()
            self._address = address
            self._device_name = self._discovered.get(address, "Body Pod")
            return await self.async_step_person()

        configured = self._async_current_ids(include_ignore=False)
        for info in async_discovered_service_info(self.hass, connectable=True):
            if info.address in configured or not _is_body_pod(info):
                continue
            self._discovered[info.address] = f"{_display_name(info)} ({info.address})"

        if not self._discovered:
            # Seen, but only by adapters/proxies that can't make connections?
            if any(
                _is_body_pod(info) and info.address not in configured
                for info in async_discovered_service_info(self.hass, connectable=False)
            ):
                return self.async_abort(reason="not_connectable")
            return self.async_abort(reason="no_devices_found")

        return self.async_show_form(
            step_id="user",
            data_schema=vol.Schema({vol.Required(CONF_ADDRESS): vol.In(self._discovered)}),
        )

    async def async_step_person(self, user_input: dict[str, Any] | None = None) -> ConfigFlowResult:
        """First person; more can be added afterwards from the integration page."""
        errors: dict[str, str] = {}
        if user_input is not None:
            name, data = _split_person(user_input, errors)
        if user_input is not None and not errors:
            return self.async_create_entry(
                title="Body Pod",
                data={CONF_ADDRESS: self._address},
                options={
                    CONF_WEIGHT_TOLERANCE: DEFAULT_WEIGHT_TOLERANCE,
                    CONF_FAT_TOLERANCE: DEFAULT_FAT_TOLERANCE,
                },
                subentries=[
                    {
                        "subentry_type": SUBENTRY_PERSON,
                        "title": name,
                        "data": data,
                        "unique_id": None,
                    }
                ],
            )
        return self.async_show_form(
            step_id="person",
            data_schema=self.add_suggested_values_to_schema(PERSON_SCHEMA, user_input or {}),
            errors=errors,
        )


class PersonSubentryFlow(ConfigSubentryFlow):
    """Add or edit a person who uses the scale."""

    def _name_taken(self, name: str, exclude: str | None = None) -> bool:
        return any(
            sub.title.casefold() == name.casefold()
            for sid, sub in self._get_entry().subentries.items()
            if sid != exclude and sub.subentry_type == SUBENTRY_PERSON
        )

    async def async_step_user(self, user_input: dict[str, Any] | None = None) -> SubentryFlowResult:
        if self._get_entry().state is not ConfigEntryState.LOADED:
            return self.async_abort(reason="entry_not_loaded")
        errors: dict[str, str] = {}
        if user_input is not None:
            name, data = _split_person(user_input, errors)
            if self._name_taken(name):
                errors[CONF_NAME] = "name_taken"
            if not errors:
                return self.async_create_entry(title=name, data=data)
        return self.async_show_form(
            step_id="user",
            data_schema=self.add_suggested_values_to_schema(PERSON_SCHEMA, user_input or {}),
            errors=errors,
        )

    async def async_step_reconfigure(
        self, user_input: dict[str, Any] | None = None
    ) -> SubentryFlowResult:
        subentry = self._get_reconfigure_subentry()
        errors: dict[str, str] = {}
        if user_input is not None:
            name, data = _split_person(user_input, errors)
            if self._name_taken(name, exclude=subentry.subentry_id):
                errors[CONF_NAME] = "name_taken"
            if not errors:
                return self.async_update_and_abort(
                    self._get_entry(), subentry, title=name, data=data
                )
        current = user_input or {CONF_NAME: subentry.title, **subentry.data}
        return self.async_show_form(
            step_id="reconfigure",
            data_schema=self.add_suggested_values_to_schema(PERSON_SCHEMA, current),
            errors=errors,
        )


class HumePodOptionsFlow(OptionsFlow):
    """Tune how strictly weigh-ins are matched to people."""

    async def async_step_init(self, user_input: dict[str, Any] | None = None) -> ConfigFlowResult:
        if user_input is not None:
            return self.async_create_entry(data=user_input)
        schema = vol.Schema(
            {
                vol.Required(CONF_WEIGHT_TOLERANCE): selector.NumberSelector(
                    selector.NumberSelectorConfig(
                        min=0.5,
                        max=15,
                        step=0.5,
                        unit_of_measurement="kg",
                        mode=selector.NumberSelectorMode.BOX,
                    )
                ),
                vol.Required(CONF_FAT_TOLERANCE): selector.NumberSelector(
                    selector.NumberSelectorConfig(
                        min=0.5,
                        max=20,
                        step=0.5,
                        unit_of_measurement="%",
                        mode=selector.NumberSelectorMode.BOX,
                    )
                ),
            }
        )
        defaults = {
            CONF_WEIGHT_TOLERANCE: DEFAULT_WEIGHT_TOLERANCE,
            CONF_FAT_TOLERANCE: DEFAULT_FAT_TOLERANCE,
            **self.config_entry.options,
        }
        return self.async_show_form(
            step_id="init", data_schema=self.add_suggested_values_to_schema(schema, defaults)
        )
