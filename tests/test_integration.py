"""End-to-end: config flow + a simulated weigh-in through a fake BLE client."""
import asyncio
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from homeassistant import config_entries
from homeassistant.const import CONF_ADDRESS, CONF_NAME
from homeassistant.data_entry_flow import FlowResultType
from homeassistant.helpers import entity_registry as er
from homeassistant.setup import async_setup_component
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.hume_pod.const import DOMAIN, EVENT_MEASUREMENT

pytestmark = pytest.mark.usefixtures("enable_custom_integrations")

ADDR = "70:4B:CA:D7:7B:CA"
PROFILE = {"sex": "male", "birthdate": "1974-01-01", "height": 173, "activity": "moderate"}


def le(vals):
    return b"".join(v.to_bytes(2, "little") for v in vals)


PACKETS = [
    bytes.fromhex("cf000000000000000000cf"),
    bytes.fromhex("cf0000a2030000000000aa"),
    bytes.fromhex("cf0000452400000000000a"),
    bytes.fromhex("cf0080592400000000000a"),  # 93.05 stable
    bytes([0xBE, 0]) + le([3319, 3229, 270, 2307, 2321]) + b"\x00",
    bytes([0xBE, 1]) + le([2951, 2890, 209, 1997, 2037]) + b"\x00",
    bytes([0xDF, 0, 0, 0, 1, 2, 3]),
]


class FakeClient:
    def __init__(self, packets, disconnect_cb):
        self.packets, self.disconnect_cb, self.handlers, self.written = packets, disconnect_cb, [], []

    async def start_notify(self, uuid, handler):
        if uuid.startswith("0000fff4"):
            self.handlers.append(handler)

    async def write_gatt_char(self, uuid, data, response=False):
        self.written.append(bytes(data))
        asyncio.get_running_loop().create_task(self._stream())

    async def _stream(self):
        for p in self.packets:
            await asyncio.sleep(0)
            for h in self.handlers:
                h(None, bytearray(p))
        await asyncio.sleep(0)
        self.disconnect_cb(self)

    async def disconnect(self):
        pass


@pytest.fixture
def ble_patches():
    registered = {}

    def register(hass, cb, matcher, mode):
        registered["cb"] = cb
        return lambda: None

    with patch("custom_components.hume_pod.bluetooth.async_scanner_count", return_value=1), \
         patch("custom_components.hume_pod.scale.bluetooth.async_register_callback", side_effect=register), \
         patch("custom_components.hume_pod.scale.bluetooth.async_ble_device_from_address", return_value=None), \
         patch("homeassistant.components.bluetooth_adapters.async_setup", AsyncMock(return_value=True), create=True):
        yield registered


async def test_bluetooth_discovery_flow(hass):
    info = MagicMock(address=ADDR, rssi=-60, service_uuids=[], manufacturer_data={}, service_data={})
    info.name = "Body Pod 2"
    with patch("custom_components.hume_pod.async_setup_entry", return_value=True):
        r = await hass.config_entries.flow.async_init(
            DOMAIN, context={"source": config_entries.SOURCE_BLUETOOTH}, data=info)
        assert r["step_id"] == "bluetooth_confirm"
        r = await hass.config_entries.flow.async_configure(r["flow_id"], {})
        assert r["step_id"] == "profile"
        r = await hass.config_entries.flow.async_configure(r["flow_id"], {CONF_NAME: "Dan", **PROFILE})
    assert r["type"] is FlowResultType.CREATE_ENTRY
    assert r["title"] == "Body Pod (Dan)"
    assert r["data"] == {CONF_ADDRESS: ADDR, CONF_NAME: "Dan"}
    assert r["options"] == PROFILE


async def test_weigh_in(hass, ble_patches):
    entry = MockConfigEntry(domain=DOMAIN, unique_id=ADDR, title="Body Pod (Dan)",
                            data={CONF_ADDRESS: ADDR, CONF_NAME: "Dan"}, options=PROFILE)
    entry.add_to_hass(hass)
    assert await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()

    events = []
    hass.bus.async_listen(EVENT_MEASUREMENT, events.append)

    fake = {}

    async def connect(cls, device, name, disconnected_callback=None, **kw):
        fake["c"] = FakeClient(PACKETS, disconnected_callback)
        return fake["c"]

    adv = MagicMock(device=MagicMock(address=ADDR), rssi=-55)
    adv.device.name = "Body Pod 2"
    with patch("custom_components.hume_pod.scale.establish_connection", side_effect=connect):
        ble_patches["cb"](adv, None)
        ble_patches["cb"](adv, None)  # burst of adverts must not start a 2nd session
        await hass.async_block_till_done(wait_background_tasks=True)

    assert len(fake["c"].written) == 1 and fake["c"].written[0][0] == 0xFE
    assert hass.states.get("sensor.body_pod_dan_weight").state == "93.05"
    assert hass.states.get("sensor.body_pod_dan_body_fat").state == "34.7"
    assert hass.states.get("sensor.body_pod_dan_basal_metabolic_rate").state == "1658"
    assert hass.states.get("sensor.body_pod_dan_status").state == "idle"
    assert hass.states.get("sensor.body_pod_dan_last_measured").state not in ("unknown", None)
    assert len(events) == 1 and events[0].data["composition"] is True
    assert events[0].data["impedance_low_trunk"] == 27.0

    ent_reg = er.async_get(hass)
    assert ent_reg.async_get("sensor.body_pod_dan_muscle_left_leg").disabled_by is not None


async def test_weight_only_keeps_previous_composition(hass, ble_patches):
    entry = MockConfigEntry(domain=DOMAIN, unique_id=ADDR, title="Body Pod (Dan)",
                            data={CONF_ADDRESS: ADDR, CONF_NAME: "Dan"}, options=PROFILE)
    entry.add_to_hass(hass)
    assert await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()
    scale = entry.runtime_data
    scale.data = {"body_fat": 30.0}

    socks = [bytes.fromhex("cf0080592400000000000a"),
             bytes([0xBE, 0]) + le([0, 0, 0, 0, 0]) + b"\x00",
             bytes([0xBE, 1]) + le([0, 0, 0, 0, 0]) + b"\x00"]

    async def connect(cls, device, name, disconnected_callback=None, **kw):
        return FakeClient(socks, disconnected_callback)

    adv = MagicMock(device=MagicMock(address=ADDR), rssi=-55)
    with patch("custom_components.hume_pod.scale.establish_connection", side_effect=connect):
        ble_patches["cb"](adv, None)
        await hass.async_block_till_done(wait_background_tasks=True)

    assert hass.states.get("sensor.body_pod_dan_weight").state == "93.05"
    assert hass.states.get("sensor.body_pod_dan_body_fat").state == "30.0"
