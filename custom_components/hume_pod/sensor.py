"""Sensors for the Hume Body Pod."""

from __future__ import annotations

from datetime import datetime

from homeassistant.components.sensor import (
    RestoreSensor,
    SensorDeviceClass,
    SensorEntity,
    SensorEntityDescription,
    SensorStateClass,
)
from homeassistant.const import CONF_NAME, PERCENTAGE, EntityCategory, UnitOfMass, UnitOfTime
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers.device_registry import CONNECTION_BLUETOOTH, DeviceInfo
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback
from homeassistant.util import dt as dt_util

from . import HumePodConfigEntry
from .const import DOMAIN, MANUFACTURER, MODEL
from .protocol import SEGMENTS
from .scale import STATUSES, HumePodScale

KG = UnitOfMass.KILOGRAMS
OHM = "Ω"


def _mass(key: str, *, enabled: bool = True, precision: int = 1) -> SensorEntityDescription:
    return SensorEntityDescription(
        key=key, translation_key=key, native_unit_of_measurement=KG,
        device_class=SensorDeviceClass.WEIGHT, state_class=SensorStateClass.MEASUREMENT,
        suggested_display_precision=precision, entity_registry_enabled_default=enabled,
    )


def _pct(key: str, *, enabled: bool = True) -> SensorEntityDescription:
    return SensorEntityDescription(
        key=key, translation_key=key, native_unit_of_measurement=PERCENTAGE,
        state_class=SensorStateClass.MEASUREMENT, suggested_display_precision=1,
        entity_registry_enabled_default=enabled,
    )


def _plain(key: str, unit: str | None = None, precision: int | None = None, icon: str | None = None,
           *, enabled: bool = True) -> SensorEntityDescription:
    return SensorEntityDescription(
        key=key, translation_key=key, native_unit_of_measurement=unit, icon=icon,
        state_class=SensorStateClass.MEASUREMENT, suggested_display_precision=precision,
        entity_registry_enabled_default=enabled,
    )


# Headline metrics are enabled by default; the long tail is one click away.
METRICS: tuple[SensorEntityDescription, ...] = (
    _mass("weight", precision=2),
    _plain("bmi", None, 1, "mdi:human"),
    _pct("body_fat"),
    _mass("fat_mass"),
    _mass("subcutaneous_fat_mass", enabled=False),
    _pct("subcutaneous_fat", enabled=False),
    _plain("visceral_fat", None, 0, "mdi:stomach"),
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
    _plain("bmr", "kcal/d", 0, "mdi:fire"),
    _plain("metabolic_age", UnitOfTime.YEARS, 0, "mdi:calendar-account"),
    *(d for seg in SEGMENTS for d in (
        _mass(f"{seg}_muscle", enabled=False),
        _pct(f"{seg}_fat", enabled=False),
        _mass(f"{seg}_fat_mass", enabled=False),
    )),
)

IMPEDANCE: tuple[SensorEntityDescription, ...] = tuple(
    SensorEntityDescription(
        key=f"impedance_{band}_{seg}", translation_key=f"impedance_{band}_{seg}",
        native_unit_of_measurement=OHM, state_class=SensorStateClass.MEASUREMENT,
        suggested_display_precision=1, entity_category=EntityCategory.DIAGNOSTIC,
        entity_registry_enabled_default=False, icon="mdi:omega",
    )
    for band in ("low", "high")
    for seg in SEGMENTS
)


async def async_setup_entry(
    hass: HomeAssistant,
    entry: HumePodConfigEntry,
    async_add_entities: AddConfigEntryEntitiesCallback,
) -> None:
    scale = entry.runtime_data
    entities: list[SensorEntity] = [
        *(HumePodMetricSensor(scale, d) for d in METRICS),
        *(HumePodMetricSensor(scale, d) for d in IMPEDANCE),
        HumePodLiveWeightSensor(scale),
        HumePodStatusSensor(scale),
        HumePodLastMeasuredSensor(scale),
    ]
    async_add_entities(entities)


class HumePodEntity(SensorEntity):
    _attr_has_entity_name = True
    _attr_should_poll = False

    def __init__(self, scale: HumePodScale, description: SensorEntityDescription) -> None:
        self.scale = scale
        self.entity_description = description
        entry = scale.entry
        self._attr_unique_id = f"{entry.entry_id}_{description.key}"
        self._attr_device_info = DeviceInfo(
            # One device per person-profile so each person's sensors group together.
            identifiers={(DOMAIN, entry.entry_id)},
            connections={(CONNECTION_BLUETOOTH, scale.address)},
            name=entry.title,
            manufacturer=MANUFACTURER,
            model=MODEL,
        )
        self._person = entry.data.get(CONF_NAME)

    async def async_added_to_hass(self) -> None:
        await super().async_added_to_hass()
        self.async_on_remove(self.scale.async_add_listener(self._handle_update))

    @callback
    def _handle_update(self) -> None:
        self.async_write_ha_state()


class HumePodMetricSensor(HumePodEntity, RestoreSensor):
    """A measurement result. Restored across restarts since the scale is offline most of the day."""

    def __init__(self, scale: HumePodScale, description: SensorEntityDescription) -> None:
        super().__init__(scale, description)
        self._source_attr = "impedance" if description.key.startswith("impedance_") else "data"
        self._restored: float | int | None = None

    async def async_added_to_hass(self) -> None:
        await super().async_added_to_hass()
        if (last := await self.async_get_last_sensor_data()) is not None:
            value = last.native_value
            if isinstance(value, (int, float)) or value is None:
                self._restored = value
            else:
                try:
                    self._restored = float(value)
                except (TypeError, ValueError):
                    self._restored = None

    @property
    def native_value(self) -> float | int | None:
        source: dict = getattr(self.scale, self._source_attr)
        return source.get(self.entity_description.key, self._restored)


class HumePodLiveWeightSensor(HumePodEntity):
    """Weight while someone is on the scale; unknown otherwise."""

    def __init__(self, scale: HumePodScale) -> None:
        super().__init__(scale, SensorEntityDescription(
            key="live_weight", translation_key="live_weight", native_unit_of_measurement=KG,
            device_class=SensorDeviceClass.WEIGHT, suggested_display_precision=2,
            entity_registry_enabled_default=False,
        ))

    @property
    def native_value(self) -> float | None:
        return self.scale.live_weight


class HumePodStatusSensor(HumePodEntity):
    def __init__(self, scale: HumePodScale) -> None:
        super().__init__(scale, SensorEntityDescription(
            key="status", translation_key="status", device_class=SensorDeviceClass.ENUM,
            options=STATUSES, entity_category=EntityCategory.DIAGNOSTIC,
        ))

    @property
    def native_value(self) -> str:
        return self.scale.status


class HumePodLastMeasuredSensor(HumePodEntity, RestoreSensor):
    def __init__(self, scale: HumePodScale) -> None:
        super().__init__(scale, SensorEntityDescription(
            key="last_measured", translation_key="last_measured",
            device_class=SensorDeviceClass.TIMESTAMP,
        ))
        self._restored: datetime | None = None

    async def async_added_to_hass(self) -> None:
        await super().async_added_to_hass()
        if (last := await self.async_get_last_state()) is not None:
            self._restored = dt_util.parse_datetime(last.state)

    @property
    def native_value(self) -> datetime | None:
        return self.scale.last_measured or self._restored

    @property
    def extra_state_attributes(self) -> dict:
        return {"last_body_composition": self.scale.last_composition}
