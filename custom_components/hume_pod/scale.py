"""Connection, session and per-person result management for a Hume Body Pod.

The scale sleeps until someone taps or steps on it, then advertises for ~30 s.
We listen for that advertisement (via any HA Bluetooth adapter or ESPHome
Bluetooth proxy), connect, start a measurement, collect weight + impedance
notifications, then work out who it was (see matching.py) and record the
result against that person.
"""

from __future__ import annotations

import asyncio
from collections.abc import Callable, Mapping, Sequence
import contextlib
from dataclasses import dataclass, field
from datetime import date, datetime
import logging
import time
from typing import Any

from bleak.backends.device import BLEDevice
from bleak.exc import BleakError
from bleak_retry_connector import BleakClientWithServiceCache, establish_connection
from homeassistant.components import bluetooth
from homeassistant.config_entries import ConfigEntry, ConfigSubentry
from homeassistant.const import CONF_ADDRESS
from homeassistant.core import CALLBACK_TYPE, HomeAssistant, callback
from homeassistant.exceptions import ServiceValidationError
from homeassistant.helpers.dispatcher import async_dispatcher_send
from homeassistant.helpers.storage import Store
from homeassistant.util import dt as dt_util

from .bia import compute_bmi, compute_body_composition, impedance_is_valid
from .const import (
    ACTIVITY_LEVELS,
    CONF_ACTIVITY,
    CONF_BIRTHDATE,
    CONF_EXPECTED_WEIGHT,
    CONF_FAT_TOLERANCE,
    CONF_HEIGHT,
    CONF_SEX,
    CONF_WEIGHT_TOLERANCE,
    COOLDOWN_AFTER_SESSION,
    DEFAULT_FAT_TOLERANCE,
    DEFAULT_WEIGHT_TOLERANCE,
    DOMAIN,
    EVENT_MEASUREMENT,
    POST_IMPEDANCE_GRACE,
    SESSION_TIMEOUT,
    SEX_MALE,
    SIGNAL_UPDATED,
    STORAGE_VERSION,
    SUBENTRY_PERSON,
)
from .matching import Candidate, MatchResult, match_person
from .protocol import (
    CHAR_NOTIFY_UUID,
    CHAR_RW_UUID,
    CHAR_WRITE_UUID,
    MIN_WEIGHT_KG,
    SEGMENTS,
    MeasurementSession,
    WeightPacket,
    build_user_command,
)

_LOGGER = logging.getLogger(__name__)

STATUS_IDLE = "idle"
STATUS_CONNECTING = "connecting"
STATUS_MEASURING = "measuring"
STATUS_ERROR = "error"
STATUSES = [STATUS_IDLE, STATUS_CONNECTING, STATUS_MEASURING, STATUS_ERROR]

REASON_MANUAL = "manual"

# Profile sent to the scale when no person is configured. The scale needs some
# profile to start a measurement; we compute composition ourselves afterwards.
_FALLBACK_PROFILE = {CONF_SEX: SEX_MALE, CONF_HEIGHT: 175, CONF_ACTIVITY: "moderate"}
_FALLBACK_AGE = 35

Impedance = tuple[float, ...]


def age_on(birthdate: date, on: date) -> int:
    return on.year - birthdate.year - ((on.month, on.day) < (birthdate.month, birthdate.day))


def _iso(value: datetime | None) -> str | None:
    return value.isoformat() if value else None


def _dt(value: str | None) -> datetime | None:
    return dt_util.parse_datetime(value) if value else None


@dataclass
class PersonState:
    """Latest results for one person."""

    data: dict[str, float | int] = field(default_factory=dict)
    impedance: dict[str, float] = field(default_factory=dict)
    measured_at: datetime | None = None
    composition_at: datetime | None = None

    def as_dict(self) -> dict[str, Any]:
        return {
            "data": self.data,
            "impedance": self.impedance,
            "measured_at": _iso(self.measured_at),
            "composition_at": _iso(self.composition_at),
        }

    @classmethod
    def from_dict(cls, raw: Mapping[str, Any]) -> PersonState:
        return cls(
            data=dict(raw.get("data", {})),
            impedance=dict(raw.get("impedance", {})),
            measured_at=_dt(raw.get("measured_at")),
            composition_at=_dt(raw.get("composition_at")),
        )


@dataclass
class PendingWeighIn:
    """A weigh-in we couldn't confidently attribute to anyone."""

    weight: float
    low: Impedance | None
    high: Impedance | None
    measured_at: datetime
    reason: str
    distances: dict[str, float]

    def as_dict(self) -> dict[str, Any]:
        return {
            "weight": self.weight,
            "low": list(self.low) if self.low else None,
            "high": list(self.high) if self.high else None,
            "measured_at": _iso(self.measured_at),
            "reason": self.reason,
            "distances": self.distances,
        }

    @classmethod
    def from_dict(cls, raw: Mapping[str, Any]) -> PendingWeighIn:
        measured_at = _dt(raw.get("measured_at")) or dt_util.utcnow()
        return cls(
            weight=float(raw["weight"]),
            low=tuple(raw["low"]) if raw.get("low") else None,
            high=tuple(raw["high"]) if raw.get("high") else None,
            measured_at=measured_at,
            reason=raw.get("reason", ""),
            distances=dict(raw.get("distances", {})),
        )


class HumePodScale:
    """Owns the BLE session and every person's latest results for one scale."""

    def __init__(self, hass: HomeAssistant, entry: ConfigEntry) -> None:
        self.hass = hass
        self.entry = entry
        self.address: str = entry.data[CONF_ADDRESS]
        self.status = STATUS_IDLE
        self.live_weight: float | None = None
        self.last_weigh_in: datetime | None = None
        self.people: dict[str, PersonState] = {}
        self.pending: PendingWeighIn | None = None
        self._store: Store[dict[str, Any]] = Store(
            hass, STORAGE_VERSION, f"{DOMAIN}.{entry.entry_id}"
        )
        self._busy = False
        self._cooldown_until = 0.0
        self._listeners: list[Callable[[], None]] = []

    # ---- persistence -------------------------------------------------------

    async def async_load(self) -> None:
        stored = await self._store.async_load() or {}
        saved_people: dict[str, Any] = stored.get("people", {})
        self.people = {
            sid: PersonState.from_dict(saved_people.get(sid, {})) for sid in self.person_subentries
        }
        if raw_pending := stored.get("pending"):
            self.pending = PendingWeighIn.from_dict(raw_pending)
        self.last_weigh_in = _dt(stored.get("last_weigh_in"))

    def _data_to_save(self) -> dict[str, Any]:
        return {
            "people": {sid: p.as_dict() for sid, p in self.people.items()},
            "pending": self.pending.as_dict() if self.pending else None,
            "last_weigh_in": _iso(self.last_weigh_in),
        }

    def _save(self) -> None:
        self._store.async_delay_save(self._data_to_save, 1)

    async def async_flush(self) -> None:
        """Write any pending save now (e.g. before a reload)."""
        await self._store.async_save(self._data_to_save())

    async def async_remove_store(self) -> None:
        await self._store.async_remove()

    # ---- people ------------------------------------------------------------

    @property
    def person_subentries(self) -> dict[str, ConfigSubentry]:
        return {
            sid: sub
            for sid, sub in self.entry.subentries.items()
            if sub.subentry_type == SUBENTRY_PERSON
        }

    def _age(self, profile: Mapping[str, Any], on: datetime) -> int:
        birthdate = dt_util.parse_date(str(profile[CONF_BIRTHDATE]))
        if birthdate is None:
            return _FALLBACK_AGE
        return age_on(birthdate, dt_util.as_local(on).date())

    def _composition(
        self,
        profile: Mapping[str, Any],
        low: Impedance,
        high: Impedance,
        weight: float,
        on: datetime,
    ) -> dict[str, float | int]:
        return compute_body_composition(
            low,
            high,
            weight,
            float(profile[CONF_HEIGHT]),
            self._age(profile, on),
            profile[CONF_SEX] == SEX_MALE,
        )

    # ---- listener plumbing -------------------------------------------------

    @callback
    def async_add_listener(self, update_cb: Callable[[], None]) -> CALLBACK_TYPE:
        self._listeners.append(update_cb)

        @callback
        def _remove() -> None:
            self._listeners.remove(update_cb)

        return _remove

    @callback
    def _notify(self) -> None:
        for update_cb in list(self._listeners):
            update_cb()
        async_dispatcher_send(self.hass, SIGNAL_UPDATED)

    def _set_status(self, status: str) -> None:
        self.status = status
        self.hass.loop.call_soon_threadsafe(self._notify)

    # ---- bluetooth ---------------------------------------------------------

    @callback
    def async_start(self) -> CALLBACK_TYPE:
        """Start listening for wake-up advertisements."""
        return bluetooth.async_register_callback(
            self.hass,
            self._async_on_advertisement,
            bluetooth.BluetoothCallbackMatcher(address=self.address, connectable=True),
            bluetooth.BluetoothScanningMode.ACTIVE,
        )

    @callback
    def _async_on_advertisement(
        self,
        service_info: bluetooth.BluetoothServiceInfoBleak,
        change: bluetooth.BluetoothChange,
    ) -> None:
        if self._busy or time.monotonic() < self._cooldown_until:
            return
        self._busy = True  # set synchronously so bursts of adverts don't race
        _LOGGER.debug("%s woke up (RSSI %s), connecting", self.address, service_info.rssi)
        self.entry.async_create_background_task(
            self.hass, self._async_run_session(service_info.device), f"hume_pod {self.address}"
        )

    async def _async_run_session(self, ble_device: BLEDevice) -> None:
        try:
            await self._async_measure(ble_device)
            self._set_status(STATUS_IDLE)
        except (BleakError, TimeoutError) as err:
            _LOGGER.debug("Session with %s failed: %s", self.address, err)
            self._set_status(STATUS_ERROR)
        except Exception:
            _LOGGER.exception("Unexpected error talking to %s", self.address)
            self._set_status(STATUS_ERROR)
        finally:
            self.live_weight = None
            self._cooldown_until = time.monotonic() + COOLDOWN_AFTER_SESSION
            self._busy = False
            self._notify()

    def _scale_profile_command(self) -> bytes:
        """The scale needs *a* profile to start; who it really is gets decided afterwards."""
        people = list(self.person_subentries.values())
        profile = people[0].data if people else _FALLBACK_PROFILE
        age = self._age(profile, dt_util.utcnow()) if people else _FALLBACK_AGE
        return build_user_command(
            male=profile[CONF_SEX] == SEX_MALE,
            age=age,
            height_cm=float(profile[CONF_HEIGHT]),
            activity=ACTIVITY_LEVELS.index(profile[CONF_ACTIVITY]),
        )

    async def _async_measure(self, ble_device: BLEDevice) -> None:
        self._set_status(STATUS_CONNECTING)
        device = (
            bluetooth.async_ble_device_from_address(self.hass, self.address, connectable=True)
            or ble_device
        )
        disconnected = asyncio.Event()
        impedance_done = asyncio.Event()
        session = MeasurementSession()

        client = await establish_connection(
            BleakClientWithServiceCache,
            device,
            device.name or self.address,
            disconnected_callback=lambda _c: self.hass.loop.call_soon_threadsafe(disconnected.set),
            max_attempts=3,
        )

        def _on_notify(_char: Any, data: bytearray) -> None:
            pkt = session.feed(data)
            if isinstance(pkt, WeightPacket) and pkt.weight_kg > MIN_WEIGHT_KG:
                self.live_weight = pkt.weight_kg
                self.status = STATUS_MEASURING
                self.hass.loop.call_soon_threadsafe(self._notify)
            if session.has_impedance:
                self.hass.loop.call_soon_threadsafe(impedance_done.set)

        try:
            await client.start_notify(CHAR_NOTIFY_UUID, _on_notify)
            with contextlib.suppress(BleakError, ValueError):
                await client.start_notify(CHAR_RW_UUID, _on_notify)
            await client.write_gatt_char(
                CHAR_WRITE_UUID, self._scale_profile_command(), response=True
            )
            self._set_status(STATUS_MEASURING)

            await _wait_first((impedance_done, disconnected), SESSION_TIMEOUT)
            if impedance_done.is_set() and not disconnected.is_set():
                # Let the trailing DF/CF packets arrive before hanging up.
                await _wait_first((disconnected,), POST_IMPEDANCE_GRACE)
        finally:
            with contextlib.suppress(BleakError, TimeoutError):
                await client.disconnect()

        if (weight := session.weight_kg) is None:
            _LOGGER.debug("%s: session ended without a weight reading", self.address)
            return
        self.handle_weigh_in(
            weight, session.impedance.get(0), session.impedance.get(1), dt_util.utcnow()
        )

    # ---- attribution -------------------------------------------------------

    @callback
    def handle_weigh_in(
        self, weight: float, low: Impedance | None, high: Impedance | None, measured_at: datetime
    ) -> MatchResult:
        """Work out who this was and record it, or park it as unassigned."""
        self.last_weigh_in = measured_at
        if not (low and high and impedance_is_valid(low)):
            low = high = None

        candidates = []
        for sid, sub in self.person_subentries.items():
            state = self.people.setdefault(sid, PersonState())
            ref_weight = state.data.get("weight") or sub.data.get(CONF_EXPECTED_WEIGHT)
            fat_now = (
                self._composition(sub.data, low, high, weight, measured_at)["body_fat"]
                if low and high
                else None
            )
            candidates.append(
                Candidate(
                    person_id=sid,
                    ref_weight=float(ref_weight) if ref_weight else None,
                    ref_fat=state.data.get("body_fat") if state.composition_at else None,
                    fat_now=fat_now,
                )
            )

        opts = self.entry.options
        result = match_person(
            weight,
            candidates,
            float(opts.get(CONF_WEIGHT_TOLERANCE, DEFAULT_WEIGHT_TOLERANCE)),
            float(opts.get(CONF_FAT_TOLERANCE, DEFAULT_FAT_TOLERANCE)),
        )
        _LOGGER.debug("%s: %.2f kg -> %s", self.address, weight, result)

        if result.person_id is not None:
            self._record(
                result.person_id, weight, low, high, measured_at, result.reason, result.distances
            )
        else:
            self.pending = PendingWeighIn(
                weight, low, high, measured_at, result.reason, result.distances
            )
            self._fire_event(
                None, weight, low is not None, result.reason, result.distances, measured_at
            )
        self._save()
        self._notify()
        return result

    def _record(
        self,
        person_id: str,
        weight: float,
        low: Impedance | None,
        high: Impedance | None,
        measured_at: datetime,
        reason: str,
        distances: dict[str, float],
    ) -> None:
        sub = self.person_subentries[person_id]
        state = self.people.setdefault(person_id, PersonState())
        state.measured_at = measured_at
        if low and high:
            state.data = dict(self._composition(sub.data, low, high, weight, measured_at))
            state.impedance = {
                **{f"impedance_low_{s}": z for s, z in zip(SEGMENTS, low, strict=False)},
                **{f"impedance_high_{s}": z for s, z in zip(SEGMENTS, high, strict=False)},
            }
            state.composition_at = measured_at
        else:
            # Weight-only (socks on, stepped off early): refresh weight and BMI,
            # keep the previous body-composition figures.
            state.data = {
                **state.data,
                "weight": round(weight, 2),
                "bmi": compute_bmi(weight, float(sub.data[CONF_HEIGHT])),
            }
        self._fire_event(person_id, weight, low is not None, reason, distances, measured_at)

    def _fire_event(
        self,
        person_id: str | None,
        weight: float,
        composition: bool,
        reason: str,
        distances: dict[str, float],
        measured_at: datetime,
    ) -> None:
        subs = self.person_subentries
        payload: dict[str, Any] = {
            "scale_entry_id": self.entry.entry_id,
            "person_id": person_id,
            "person": subs[person_id].title if person_id else None,
            "match_reason": reason,
            "match_distances": {subs[k].title: v for k, v in distances.items() if k in subs},
            "composition": composition,
            "measured_at": measured_at.isoformat(),
            "weight": round(weight, 2),
        }
        if person_id:
            state = self.people[person_id]
            payload.update(state.data if composition else {"bmi": state.data.get("bmi")})
            if composition:
                payload.update(state.impedance)
        self.hass.bus.async_fire(EVENT_MEASUREMENT, payload)

    @callback
    def async_assign_pending(self, person_id: str) -> None:
        if self.pending is None:
            raise ServiceValidationError(
                translation_domain=DOMAIN, translation_key="no_pending_weigh_in"
            )
        if person_id not in self.person_subentries:
            raise ServiceValidationError(
                translation_domain=DOMAIN, translation_key="person_not_on_scale"
            )
        p, self.pending = self.pending, None
        self._record(person_id, p.weight, p.low, p.high, p.measured_at, REASON_MANUAL, {})
        self._save()
        self._notify()

    @callback
    def async_discard_pending(self) -> None:
        if self.pending is None:
            raise ServiceValidationError(
                translation_domain=DOMAIN, translation_key="no_pending_weigh_in"
            )
        self.pending = None
        self._save()
        self._notify()

    def diagnostics(self) -> dict[str, Any]:
        return {
            "status": self.status,
            "options": dict(self.entry.options),
            "people": {
                sid: {"has_history": bool(p.measured_at), **p.as_dict()}
                for sid, p in self.people.items()
            },
            "pending": self.pending.as_dict() if self.pending else None,
        }


async def _wait_first(events: Sequence[asyncio.Event], seconds: float) -> None:
    """Wait until any of the events is set, or the timeout passes."""
    tasks = [asyncio.create_task(ev.wait()) for ev in events]
    try:
        await asyncio.wait(tasks, timeout=seconds, return_when=asyncio.FIRST_COMPLETED)
    finally:
        for task in tasks:
            task.cancel()
