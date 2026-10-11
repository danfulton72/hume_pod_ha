"""End-to-end tests: config/subentry/options flows and simulated weigh-ins."""

import asyncio
from unittest.mock import MagicMock, patch

from homeassistant import config_entries
from homeassistant.config_entries import ConfigSubentryData
from homeassistant.const import CONF_ADDRESS, CONF_NAME
from homeassistant.data_entry_flow import FlowResultType
from homeassistant.exceptions import ServiceValidationError
from homeassistant.helpers import device_registry as dr, entity_registry as er
import pytest
from pytest_homeassistant_custom_component.common import MockConfigEntry
from pytest_homeassistant_custom_component.components.diagnostics import (
    get_diagnostics_for_config_entry,
)

from custom_components.hume_pod.const import DOMAIN, EVENT_MEASUREMENT, SUBENTRY_PERSON

pytestmark = pytest.mark.usefixtures("enable_custom_integrations")

ADDR = "70:4B:CA:D7:7B:CA"
DAN = {
    "sex": "male",
    "birthdate": "1974-01-01",
    "height": 173,
    "activity": "moderate",
    "expected_weight": 93.0,
}
SAM = {
    "sex": "female",
    "birthdate": "1990-06-15",
    "height": 165,
    "activity": "active",
    "expected_weight": 62.0,
}


def le(vals):
    return b"".join(v.to_bytes(2, "little") for v in vals)


def weight_pkt(kg, stable=True):
    return bytes([0xCF, 0, 0x80 if stable else 0]) + le([round(kg * 100)]) + bytes(6)


LOW = [3319, 3229, 270, 2307, 2321]
HIGH = [2951, 2890, 209, 1997, 2037]


def weigh_in(kg, impedance=True):
    pkts = [weight_pkt(0, False), weight_pkt(kg - 3, False), weight_pkt(kg)]
    if impedance:
        pkts += [
            bytes([0xBE, 0]) + le(LOW) + b"\x00",
            bytes([0xBE, 1]) + le(HIGH) + b"\x00",
            bytes([0xDF, 0, 0, 0, 1, 2, 3]),
        ]
    return pkts


class FakeClient:
    def __init__(self, packets, disconnect_cb):
        self.packets, self.disconnect_cb, self.handlers, self.written = (
            packets,
            disconnect_cb,
            [],
            [],
        )

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


async def step_on(hass, ble, packets):
    clients = []

    async def connect(cls, device, name, disconnected_callback=None, **kw):
        clients.append(FakeClient(packets, disconnected_callback))
        return clients[-1]

    adv = MagicMock(device=MagicMock(address=ADDR), rssi=-55)
    adv.device.name = "Body Pod 2"
    scale = hass.config_entries.async_entries(DOMAIN)[0].runtime_data
    scale._cooldown_until = 0
    with patch("custom_components.hume_pod.scale.establish_connection", side_effect=connect):
        ble["cb"](adv, None)
        ble["cb"](adv, None)  # burst of adverts must not start a 2nd session
        await hass.async_block_till_done(wait_background_tasks=True)
    assert len(clients) == 1
    return clients[0]


async def setup_scale(hass, people):
    entry = MockConfigEntry(
        domain=DOMAIN,
        unique_id=ADDR,
        title="Body Pod",
        version=1,
        data={CONF_ADDRESS: ADDR},
        options={"weight_tolerance": 3.0, "fat_tolerance": 4.0},
        subentries_data=[
            ConfigSubentryData(subentry_type=SUBENTRY_PERSON, title=name, data=data, unique_id=None)
            for name, data in people
        ],
    )
    entry.add_to_hass(hass)
    assert await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()
    return entry


def state(hass, entity_id):
    return hass.states.get(entity_id).state


def person_device(hass, entry, name):
    sid = next(s for s, sub in entry.subentries.items() if sub.title == name)
    return dr.async_get(hass).async_get_device({(DOMAIN, f"{entry.entry_id}_{sid}")})


# ---- flows --------------------------------------------------------------------


async def test_bluetooth_discovery_flow(hass):
    info = MagicMock(
        address=ADDR, rssi=-60, service_uuids=[], manufacturer_data={}, service_data={}
    )
    info.name = "Body Pod 2"
    with patch("custom_components.hume_pod.async_setup_entry", return_value=True):
        r = await hass.config_entries.flow.async_init(
            DOMAIN, context={"source": config_entries.SOURCE_BLUETOOTH}, data=info
        )
        assert r["step_id"] == "bluetooth_confirm"
        r = await hass.config_entries.flow.async_configure(r["flow_id"], {})
        assert r["step_id"] == "person"
        r = await hass.config_entries.flow.async_configure(
            r["flow_id"], {CONF_NAME: " Dan ", **DAN}
        )
    assert r["type"] is FlowResultType.CREATE_ENTRY
    entry = r["result"]
    assert entry.title == "Body Pod" and entry.data == {CONF_ADDRESS: ADDR}
    (sub,) = entry.subentries.values()
    assert sub.title == "Dan" and sub.data == DAN and sub.subentry_type == SUBENTRY_PERSON


async def test_add_and_edit_person(hass, ble):
    entry = await setup_scale(hass, [("Dan", DAN)])

    r = await hass.config_entries.subentries.async_init(
        (entry.entry_id, SUBENTRY_PERSON), context={"source": config_entries.SOURCE_USER}
    )
    r = await hass.config_entries.subentries.async_configure(
        r["flow_id"], {CONF_NAME: "dan", **SAM}
    )
    assert r["errors"] == {CONF_NAME: "name_taken"}
    r = await hass.config_entries.subentries.async_configure(
        r["flow_id"], {CONF_NAME: "Sam", **SAM}
    )
    assert r["type"] is FlowResultType.CREATE_ENTRY
    await hass.async_block_till_done()

    # Reloaded with a new device + entities for Sam
    assert state(hass, "sensor.sam_weight") == "unknown"

    sam_id = next(s for s, sub in entry.subentries.items() if sub.title == "Sam")
    r = await hass.config_entries.subentries.async_init(
        (entry.entry_id, SUBENTRY_PERSON),
        context={"source": config_entries.SOURCE_RECONFIGURE, "subentry_id": sam_id},
    )
    r = await hass.config_entries.subentries.async_configure(
        r["flow_id"], {CONF_NAME: "Sam", **SAM, "height": 168}
    )
    assert r["reason"] == "reconfigure_successful"
    assert entry.subentries[sam_id].data["height"] == 168


async def test_options_flow(hass, ble):
    entry = await setup_scale(hass, [("Dan", DAN)])
    r = await hass.config_entries.options.async_init(entry.entry_id)
    r = await hass.config_entries.options.async_configure(
        r["flow_id"], {"weight_tolerance": 5.0, "fat_tolerance": 3.0}
    )
    assert r["type"] is FlowResultType.CREATE_ENTRY
    assert entry.options == {"weight_tolerance": 5.0, "fat_tolerance": 3.0}


# ---- weigh-ins ----------------------------------------------------------------


async def test_two_people_matched_automatically(hass, ble):
    await setup_scale(hass, [("Dan", DAN), ("Sam", SAM)])
    events = []
    hass.bus.async_listen(EVENT_MEASUREMENT, events.append)

    client = await step_on(hass, ble, weigh_in(93.05))
    assert client.written[0][0] == 0xFE
    assert state(hass, "sensor.dan_weight") == "93.05"
    assert state(hass, "sensor.dan_body_fat") == "34.7"
    assert state(hass, "sensor.dan_basal_metabolic_rate") == "1658"
    assert state(hass, "sensor.sam_weight") == "unknown"
    assert events[-1].data["person"] == "Dan"
    assert events[-1].data["match_reason"] == "matched"
    assert events[-1].data["impedance_low_trunk"] == 27.0

    await step_on(hass, ble, weigh_in(61.2))
    assert state(hass, "sensor.sam_weight") == "61.2"
    # Sam's composition is computed with Sam's own profile (female, 165 cm)
    assert state(hass, "sensor.sam_body_fat") != state(hass, "sensor.dan_body_fat")
    assert state(hass, "sensor.dan_weight") == "93.05"
    assert state(hass, "sensor.body_pod_status") == "idle"
    assert state(hass, "sensor.body_pod_last_weigh_in") not in ("unknown", None)

    assert er.async_get(hass).async_get("sensor.dan_muscle_left_leg").disabled_by is not None


async def test_guest_unassigned_then_assigned(hass, ble):
    entry = await setup_scale(hass, [("Dan", DAN), ("Sam", SAM)])
    events = []
    hass.bus.async_listen(EVENT_MEASUREMENT, events.append)

    await step_on(hass, ble, weigh_in(75.0))
    st = hass.states.get("sensor.body_pod_unassigned_weigh_in")
    assert st.state == "75.0"
    assert st.attributes["reason"] == "no_match"
    assert st.attributes["has_body_composition"] is True
    assert events[-1].data["person"] is None
    assert state(hass, "sensor.dan_weight") == "unknown"

    # Assigning to the scale device is rejected
    scale_dev = dr.async_get(hass).async_get_device({(DOMAIN, entry.entry_id)})
    with pytest.raises(ServiceValidationError):
        await hass.services.async_call(
            DOMAIN, "assign_weigh_in", {"person": scale_dev.id}, blocking=True
        )

    sam = person_device(hass, entry, "Sam")
    await hass.services.async_call(DOMAIN, "assign_weigh_in", {"person": sam.id}, blocking=True)
    await hass.async_block_till_done()
    assert state(hass, "sensor.sam_weight") == "75.0"
    assert state(hass, "sensor.body_pod_unassigned_weigh_in") == "unknown"
    assert events[-1].data["person"] == "Sam" and events[-1].data["match_reason"] == "manual"

    with pytest.raises(ServiceValidationError):
        await hass.services.async_call(DOMAIN, "assign_weigh_in", {"person": sam.id}, blocking=True)


async def test_discard(hass, ble):
    entry = await setup_scale(hass, [("Dan", DAN)])
    await step_on(hass, ble, weigh_in(130.0))
    assert state(hass, "sensor.body_pod_unassigned_weigh_in") == "130.0"
    scale_dev = dr.async_get(hass).async_get_device({(DOMAIN, entry.entry_id)})
    await hass.services.async_call(
        DOMAIN, "discard_weigh_in", {"scale": scale_dev.id}, blocking=True
    )
    await hass.async_block_till_done()
    assert state(hass, "sensor.body_pod_unassigned_weigh_in") == "unknown"


async def test_weight_only_keeps_previous_composition_and_survives_reload(hass, ble):
    entry = await setup_scale(hass, [("Dan", DAN), ("Sam", SAM)])
    await step_on(hass, ble, weigh_in(93.05))
    fat = state(hass, "sensor.dan_body_fat")

    await step_on(hass, ble, weigh_in(92.5, impedance=False))  # socks on
    assert state(hass, "sensor.dan_weight") == "92.5"
    assert state(hass, "sensor.dan_body_fat") == fat

    assert await hass.config_entries.async_reload(entry.entry_id)
    await hass.async_block_till_done()
    assert state(hass, "sensor.dan_weight") == "92.5"
    assert state(hass, "sensor.dan_body_fat") == fat


async def test_diagnostics_redacted(hass, hass_client, ble):
    entry = await setup_scale(hass, [("Dan", DAN)])
    await step_on(hass, ble, weigh_in(93.05))
    diag = await get_diagnostics_for_config_entry(hass, hass_client, entry)
    text = str(diag)
    assert ADDR not in text and "1974-01-01" not in text and "'Dan'" not in text
    assert diag["scale"]["status"] == "idle"
