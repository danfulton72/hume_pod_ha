"""Connection/session manager for a Hume Body Pod.

The scale sleeps until someone taps or steps on it, then advertises for ~30 s.
We listen for that advertisement (via any HA Bluetooth adapter or ESPHome
Bluetooth proxy), connect, send the user profile, and collect weight and
impedance notifications until the measurement completes.
"""

from __future__ import annotations

import asyncio
import contextlib
import logging
import time
from collections.abc import Callable
from datetime import date, datetime
from typing import Any

from bleak.backends.device import BLEDevice
from bleak.exc import BleakError
from bleak_retry_connector import (
    BleakClientWithServiceCache,
    establish_connection,
)

from homeassistant.components import bluetooth
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import CALLBACK_TYPE, HomeAssistant, callback
from homeassistant.util import dt as dt_util

from .bia import compute_bmi, compute_body_composition, impedance_is_valid
from .const import (
    ACTIVITY_LEVELS,
    CONF_ACTIVITY,
    CONF_BIRTHDATE,
    CONF_HEIGHT,
    CONF_SEX,
    COOLDOWN_AFTER_SESSION,
    EVENT_MEASUREMENT,
    POST_IMPEDANCE_GRACE,
    SESSION_TIMEOUT,
    SEX_MALE,
)
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


def age_on(birthdate: date, today: date) -> int:
    return today.year - birthdate.year - ((today.month, today.day) < (birthdate.month, birthdate.day))


class HumePodScale:
    """Owns the BLE session and the latest results for one scale + profile."""

    def __init__(self, hass: HomeAssistant, entry: ConfigEntry, address: str) -> None:
        self.hass = hass
        self.entry = entry
        self.address = address
        self.status = STATUS_IDLE
        self.live_weight: float | None = None
        self.data: dict[str, float | int] = {}
        self.impedance: dict[str, float] = {}
        self.last_measured: datetime | None = None
        self.last_composition: datetime | None = None
        self._busy = False
        self._cooldown_until = 0.0
        self._listeners: list[Callable[[], None]] = []

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

            opts = self.entry.options
            cmd = build_user_command(
                male=opts[CONF_SEX] == SEX_MALE,
                age=self._age(),
                height_cm=opts[CONF_HEIGHT],
                activity=ACTIVITY_LEVELS.index(opts[CONF_ACTIVITY]),
            )
            await client.write_gatt_char(CHAR_WRITE_UUID, cmd, response=True)
            self._set_status(STATUS_MEASURING)

            await _wait_first((impedance_done, disconnected), SESSION_TIMEOUT)
            if impedance_done.is_set() and not disconnected.is_set():
                # Let the trailing DF/CF packets arrive before hanging up.
                await _wait_first((disconnected,), POST_IMPEDANCE_GRACE)
        finally:
            with contextlib.suppress(BleakError, TimeoutError):
                await client.disconnect()

        self._publish(session)

    # ---- results -----------------------------------------------------------

    def _age(self) -> int:
        birthdate = dt_util.parse_date(self.entry.options[CONF_BIRTHDATE])
        assert birthdate is not None
        return age_on(birthdate, dt_util.now().date())

    def _publish(self, session: MeasurementSession) -> None:
        weight = session.weight_kg
        if weight is None:
            _LOGGER.debug("%s: session ended without a weight reading", self.address)
            return

        opts = self.entry.options
        height = float(opts[CONF_HEIGHT])
        male = opts[CONF_SEX] == SEX_MALE
        now = dt_util.utcnow()
        self.last_measured = now

        low = session.impedance.get(0)
        high = session.impedance.get(1)
        composition_ok = bool(low and high and impedance_is_valid(low))

        if composition_ok:
            assert low is not None and high is not None
            self.data = dict(
                compute_body_composition(low, high, weight, height, self._age(), male)
            )
            self.impedance = {
                **{f"impedance_low_{s}": z for s, z in zip(SEGMENTS, low, strict=False)},
                **{f"impedance_high_{s}": z for s, z in zip(SEGMENTS, high, strict=False)},
            }
            self.last_composition = now
        else:
            # Weight-only weigh-in (socks on, stepped off early...): keep the
            # previous body-composition figures, refresh weight and BMI.
            _LOGGER.info(
                "%s: weight %.2f kg recorded without valid impedance; "
                "stand barefoot on all four pads for body composition",
                self.address,
                weight,
            )
            self.data = {**self.data, "weight": round(weight, 2), "bmi": compute_bmi(weight, height)}

        self.hass.bus.async_fire(
            EVENT_MEASUREMENT,
            {
                "device_id": self.entry.unique_id,
                "address": self.address,
                "profile": self.entry.title,
                "composition": composition_ok,
                "measured_at": now.isoformat(),
                **{k: v for k, v in self.data.items() if composition_ok or k in ("weight", "bmi")},
                **(self.impedance if composition_ok else {}),
            },
        )


async def _wait_first(events: tuple[asyncio.Event, ...], timeout: float) -> None:
    """Wait until any of the events is set, or the timeout passes."""
    tasks = [asyncio.create_task(ev.wait()) for ev in events]
    try:
        await asyncio.wait(tasks, timeout=timeout, return_when=asyncio.FIRST_COMPLETED)
    finally:
        for task in tasks:
            task.cancel()
