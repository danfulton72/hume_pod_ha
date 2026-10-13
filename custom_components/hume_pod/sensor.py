"""Sensors for the Hume Body Pod.

The scale gets one device (status, live weight, unassigned weigh-in) and each
person gets their own device, linked via the scale, holding their results.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime
from typing import Any

from homeassistant.components.sensor import (
    SensorDeviceClass,
    SensorEntity,
    SensorEntityDescription,
    SensorStateClass,
)
from homeassistant.config_entries import ConfigSubentry
from homeassistant.const import (
    PERCENTAGE,
    SIGNAL_STRENGTH_DECIBELS_MILLIWATT,
    EntityCategory,
    UnitOfMass,
    UnitOfTime,
)
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers.device_registry import CONNECTION_BLUETOOTH, DeviceInfo
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback

from . import HumePodConfigEntry
from .const import DOMAIN, MANUFACTURER, MODEL, MODEL_PERSON
from .protocol import SEGMENTS
from .scale import STATUSES, HumePodScale

PARALLEL_UPDATES = 0

KG = UnitOfMass.KILOGRAMS
OHM = "Ω"


def _mass(key: str, *, enabled: bool = True, precision: int = 1) -> SensorEntityDescription:
    return SensorEntityDescription(
        key=key,
        translation_key=key,
        native_unit_of_measurement=KG,
        device_class=SensorDeviceClass.WEIGHT,
        state_class=SensorStateClass.MEASUREMENT,
        suggested_display_precision=precision,
        entity_registry_enabled_default=enabled,
    )


def _pct(key: str, *, enabled: bool = True) -> SensorEntityDescription:
    return SensorEntityDescription(
        key=key,
        translation_key=key,
        native_unit_of_measurement=PERCENTAGE,
        state_class=SensorStateClass.MEASUREMENT,
        suggested_display_precision=1,
        entity_registry_enabled_default=enabled,
    )


def _plain(key: str, unit: str | None, precision: int) -> SensorEntityDescription:
    return SensorEntityDescription(
        key=key,
        translation_key=key,
        native_unit_of_measurement=unit,
        state_class=SensorStateClass.MEASUREMENT,
        suggested_display_precision=precision,
    )


# Headline metrics are enabled by default; the long tail is one click away.
METRICS: tuple[SensorEntityDescription, ...] = (
    _mass("weight", precision=2),
    _plain("bmi", None, 1),
    _pct("body_fat"),
    _mass("fat_mass"),
    _mass("subcutaneous_fat_mass", enabled=False),
    _pct("subcutaneous_fat", enabled=False),
    _plain("visceral_fat", None, 0),
    _mass("android_fat", enabled=False),
    _mass("gynoid_fat", enabled=False),
    _pct("android_gynoid_ratio", enabled=False),
    _mass("lean_mass"),
    _pct("lean_mass_percentage", enabled=False),
    _mass("skeletal_muscle_mass"),
    _mass("body_cell_mass", enabled=False),
    _pct("body_water"),
    _mass("total_body_water", enabled=False),
    _mass("extracellular_water", enabled=False),
    _mass("intracellular_water", enabled=False),
    _mass("bone_mineral"),
    _mass("mineral_mass", enabled=False),
    _mass("skeletal_mass", enabled=False),
    _mass("organ_mass", enabled=False),
    _plain("bmr", "kcal/d", 0),
    _plain("metabolic_age", UnitOfTime.YEARS, 0),
    *(
        d
        for seg in SEGMENTS
        for d in (
            _mass(f"{seg}_muscle", enabled=False),
            _pct(f"{seg}_fat", enabled=False),
            _mass(f"{seg}_fat_mass", enabled=False),
        )
    ),
)

IMPEDANCE: tuple[SensorEntityDescription, ...] = tuple(
    SensorEntityDescription(
        key=f"impedance_{band}_{seg}",
        translation_key=f"impedance_{band}_{seg}",
        native_unit_of_measurement=OHM,
        state_class=SensorStateClass.MEASUREMENT,
        suggested_display_precision=1,
        entity_category=EntityCategory.DIAGNOSTIC,
        entity_registry_enabled_default=False,
    )
    for band in ("low", "high")
    for seg in SEGMENTS
)


@dataclass(frozen=True, kw_only=True)
class ScaleSensorDescription(SensorEntityDescription):
    value_fn: Callable[[HumePodScale], Any]
    attrs_fn: Callable[[HumePodScale], dict[str, Any] | None] = lambda _s: None


def _pending_attrs(scale: HumePodScale) -> dict[str, Any] | None:
    if (p := scale.pending) is None:
        return None
    people = scale.person_subentries
    return {
        "measured_at": p.measured_at.isoformat(),
        "reason": p.reason,
        "has_body_composition": p.low is not None,
        "match_distances": {people[k].title: v for k, v in p.distances.items() if k in people},
    }


SCALE_SENSORS: tuple[ScaleSensorDescription, ...] = (
    ScaleSensorDescription(
        key="status",
        translation_key="status",
        device_class=SensorDeviceClass.ENUM,
        options=STATUSES,
        entity_category=EntityCategory.DIAGNOSTIC,
        value_fn=lambda s: s.status,
        attrs_fn=lambda s: {
            "last_error": s.last_error,
            "last_attempt": s.last_attempt.isoformat() if s.last_attempt else None,
            "via": s.via,
        },
    ),
    ScaleSensorDescription(
        key="battery",
        device_class=SensorDeviceClass.BATTERY,
        native_unit_of_measurement=PERCENTAGE,
        state_class=SensorStateClass.MEASUREMENT,
        entity_category=EntityCategory.DIAGNOSTIC,
        value_fn=lambda s: s.battery,
    ),
    ScaleSensorDescription(
        key="signal_strength",
        translation_key="signal_strength",
        device_class=SensorDeviceClass.SIGNAL_STRENGTH,
        native_unit_of_measurement=SIGNAL_STRENGTH_DECIBELS_MILLIWATT,
        state_class=SensorStateClass.MEASUREMENT,
        entity_category=EntityCategory.DIAGNOSTIC,
        value_fn=lambda s: s.rssi,
        attrs_fn=lambda s: {"via": s.via},
    ),
    ScaleSensorDescription(
        key="live_weight",
        translation_key="live_weight",
        native_unit_of_measurement=KG,
        device_class=SensorDeviceClass.WEIGHT,
        suggested_display_precision=2,
        entity_registry_enabled_default=False,
        value_fn=lambda s: s.live_weight,
    ),
    ScaleSensorDescription(
        key="unassigned_weigh_in",
        translation_key="unassigned_weigh_in",
        native_unit_of_measurement=KG,
        device_class=SensorDeviceClass.WEIGHT,
        suggested_display_precision=2,
        value_fn=lambda s: s.pending.weight if s.pending else None,
        attrs_fn=_pending_attrs,
    ),
    ScaleSensorDescription(
        key="last_weigh_in",
        translation_key="last_weigh_in",
        device_class=SensorDeviceClass.TIMESTAMP,
        value_fn=lambda s: s.last_weigh_in,
    ),
)


async def async_setup_entry(
    hass: HomeAssistant,
    entry: HumePodConfigEntry,
    async_add_entities: AddConfigEntryEntitiesCallback,
) -> None:
    scale = entry.runtime_data
    async_add_entities(HumePodScaleSensor(scale, d) for d in SCALE_SENSORS)

    for subentry in scale.person_subentries.values():
        async_add_entities(
            [
                *(HumePodPersonSensor(scale, subentry, d) for d in (*METRICS, *IMPEDANCE)),
                HumePodPersonLastMeasured(scale, subentry),
            ],
            config_subentry_id=subentry.subentry_id,
        )


class HumePodEntity(SensorEntity):
    _attr_has_entity_name = True
    _attr_should_poll = False

    def __init__(self, scale: HumePodScale) -> None:
        self.scale = scale

    async def async_added_to_hass(self) -> None:
        await super().async_added_to_hass()
        self.async_on_remove(self.scale.async_add_listener(self._handle_update))

    @callback
    def _handle_update(self) -> None:
        self.async_write_ha_state()


class HumePodScaleSensor(HumePodEntity):
    """Entity on the scale's own device."""

    entity_description: ScaleSensorDescription

    def __init__(self, scale: HumePodScale, description: ScaleSensorDescription) -> None:
        super().__init__(scale)
        self.entity_description = description
        entry = scale.entry
        self._attr_unique_id = f"{entry.entry_id}_{description.key}"
        self._attr_device_info = DeviceInfo(
            identifiers={(DOMAIN, entry.entry_id)},
            connections={(CONNECTION_BLUETOOTH, scale.address)},
            name=entry.title,
            manufacturer=MANUFACTURER,
            model=MODEL,
        )

    @property
    def native_value(self) -> Any:
        return self.entity_description.value_fn(self.scale)

    @property
    def extra_state_attributes(self) -> dict[str, Any] | None:
        return self.entity_description.attrs_fn(self.scale)


class HumePodPersonEntity(HumePodEntity):
    """Entity on a person's device."""

    def __init__(self, scale: HumePodScale, subentry: ConfigSubentry, key: str) -> None:
        super().__init__(scale)
        entry = scale.entry
        self.person_id = subentry.subentry_id
        self._attr_unique_id = f"{entry.entry_id}_{subentry.subentry_id}_{key}"
        self._attr_device_info = DeviceInfo(
            identifiers={(DOMAIN, f"{entry.entry_id}_{subentry.subentry_id}")},
            name=subentry.title,
            manufacturer=MANUFACTURER,
            model=MODEL_PERSON,
            via_device=(DOMAIN, entry.entry_id),
        )

    @property
    def _state(self):
        return self.scale.people.get(self.person_id)


class HumePodPersonSensor(HumePodPersonEntity):
    def __init__(
        self, scale: HumePodScale, subentry: ConfigSubentry, description: SensorEntityDescription
    ) -> None:
        super().__init__(scale, subentry, description.key)
        self.entity_description = description
        self._is_impedance = description.key.startswith("impedance_")

    @property
    def native_value(self) -> float | int | None:
        if (state := self._state) is None:
            return None
        source = state.impedance if self._is_impedance else state.data
        return source.get(self.entity_description.key)


class HumePodPersonLastMeasured(HumePodPersonEntity):
    def __init__(self, scale: HumePodScale, subentry: ConfigSubentry) -> None:
        super().__init__(scale, subentry, "last_measured")
        self.entity_description = SensorEntityDescription(
            key="last_measured",
            translation_key="last_measured",
            device_class=SensorDeviceClass.TIMESTAMP,
        )

    @property
    def native_value(self) -> datetime | None:
        return self._state.measured_at if self._state else None

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        at = self._state.composition_at if self._state else None
        return {"last_body_composition": at.isoformat() if at else None}
