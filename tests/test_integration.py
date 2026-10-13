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


def _uuid(short):
    return f"0000{short}-0000-1000-8000-00805f9b34fb"


class FakeChar:
    def __init__(self, short, props):
        self.uuid, self.properties = _uuid(short), props


class FakeService:
    def __init__(self, short, chars):
        self.uuid, self.characteristics = _uuid(short), chars


class FakeServices:
    """Enough of bleak's BleakGATTServiceCollection for the integration."""

    def __init__(self, layout):
        self._services = [
            FakeService(svc, [FakeChar(c, p) for c, p in chars.items()])
            for svc, chars in layout.items()
        ]

    def __iter__(self):
        return iter(self._services)

    def get_characteristic(self, uuid):
        for svc in self._services:
            for char in svc.characteristics:
                if char.uuid == uuid:
                    return char
        return None


# Layout reported by a real Body Pod 2
BODY_POD_LAYOUT = {
    "180a": {
        "2a24": ["read"],
        "2a25": ["read"],
        "2a26": ["read"],
        "2a27": ["read"],
        "2a29": ["read"],
    },
    "180f": {"2a19": ["read", "notify"]},
    "fff0": {
        "fff1": ["write"],
        "fff2": ["read", "write-without-response", "write", "notify"],
        "fff4": ["notify"],
    },
}

GATT_VALUES = {
    "2a19": bytes([87]),
    "2a24": b"Body Pod 2\x00",
    "2a26": b"002.000.004.000",
    "2a27": b"V1",
    "2a29": b"Lefu",
}

# The real Body Pod 2 weigh-in from a user's debug log (19:30, 13 Oct 2026):
# weight settles to 63.50 kg, byte 9 drops to 00 when locked, no impedance.
REAL_POD2_PACKETS = [
    bytes.fromhex(h)
    for h in [
        "cf0000ab1800000001017c",
        "cf0000ab1800000001017c",
        "cf0000e718000000010130",
        "cf00002e180000000101f9",
        "cf00009218000000010145",
        "cf00009c1800000001014b",
        "cf0000a618000000010171",
        "cf0000a618000000010171",
        "cf0000a118000000010176",
        "cf0000a118000000010176",
        "cf0000a118000000010176",
        "cf0000ab1800000001017c",
        "cf0000b018000000010167",
        "cf0000b018000000010167",
        "cf0000b518000000010162",
        "cf0000ba1800000001016d",
        "cf0000bf18000000010168",
        "cf0000c418000000010113",
        "cf0000c418000000010113",
        "cf0000c91800000001011e",
        "cf0000c91800000001011e",
        "cf0000c91800000001011e",
        "cf0000ce18000000010119",
        "cf0000ce18000000010119",
        "cf0000ce18000000010018",
    ]
]


class FakeClient:
    def __init__(self, packets, disconnect_cb, layout=None, disconnect_after=True):
        self.packets, self.disconnect_cb = packets, disconnect_cb
        self.handlers, self.written, self.responses = [], [], []
        self.services = FakeServices(layout or BODY_POD_LAYOUT)
        self.disconnect_after = disconnect_after

    async def start_notify(self, uuid, handler):
        if uuid.startswith("0000fff4"):
            self.handlers.append(handler)

    async def write_gatt_char(self, uuid, data, response=False):
        self.written.append(bytes(data))
        self.responses.append(response)
        asyncio.get_running_loop().create_task(self._stream())

    async def _stream(self):
        for p in self.packets:
            await asyncio.sleep(0)
            for h in self.handlers:
                h(FakeChar("fff4", ["notify"]), bytearray(p))
        await asyncio.sleep(0)
        if self.disconnect_after:
            self.disconnect_cb(self)

    async def read_gatt_char(self, uuid):
        return GATT_VALUES.get(uuid[4:8], b"")

    async def disconnect(self):
        pass


def advert(rssi=-55, mfr=None):
    adv = MagicMock(device=MagicMock(address=ADDR), rssi=rssi, source="proxy-1")
    adv.device.name = "Body Pod 2"
    adv.manufacturer_data = mfr or {94: bytes.fromhex("704bcad77bca") + bytes(12)}
    return adv


async def step_on(hass, ble, packets, connect=None, rssi=-55, **client_kw):
    clients = []

    async def default_connect(cls, device, name, disconnected_callback=None, **kw):
        clients.append(FakeClient(packets, disconnected_callback, **client_kw))
        return clients[-1]

    scale = hass.config_entries.async_entries(DOMAIN)[0].runtime_data
    scale._cooldown_until = 0
    with patch(
        "custom_components.hume_pod.scale.establish_connection",
        side_effect=connect or default_connect,
    ):
        ble["cb"](advert(rssi), None)
        ble["cb"](advert(rssi), None)  # burst of adverts must not start a 2nd session
        await hass.async_block_till_done(wait_background_tasks=True)
    if connect is None:
        assert len(clients) == 1
        return clients[0]
    return None


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


def _service_info(address, name, uuids, mfr, connectable=True):
    from homeassistant.components.bluetooth import BluetoothServiceInfoBleak

    info = MagicMock(spec=BluetoothServiceInfoBleak)
    info.address, info.name, info.rssi = address, name, -60
    info.service_uuids, info.manufacturer_data, info.service_data = uuids, mfr, {}
    info.connectable = connectable
    return info


POD2_ADDR = "8C:8C:29:4E:33:42"
POD2_UUIDS = ["0000fff0-0000-1000-8000-00805f9b34fb", "00001812-0000-1000-8000-00805f9b34fb"]
POD2_MFR = {94: bytes.fromhex("8c8c294e3342") + bytes(12)}


async def test_nameless_body_pod2_discovered(hass):
    info = _service_info(POD2_ADDR, POD2_ADDR, POD2_UUIDS, POD2_MFR)
    with patch("custom_components.hume_pod.async_setup_entry", return_value=True):
        r = await hass.config_entries.flow.async_init(
            DOMAIN, context={"source": config_entries.SOURCE_BLUETOOTH}, data=info
        )
        assert r["step_id"] == "bluetooth_confirm"
        assert r["description_placeholders"] == {"name": "Body Pod"}
        r = await hass.config_entries.flow.async_configure(r["flow_id"], {})
        r = await hass.config_entries.flow.async_configure(r["flow_id"], {CONF_NAME: "Dan", **DAN})
    assert r["type"] is FlowResultType.CREATE_ENTRY
    assert r["result"].unique_id == POD2_ADDR


async def test_unrelated_fff0_device_aborts(hass):
    info = _service_info("11:22:33:44:55:66", "LED strip", POD2_UUIDS[:1], {76: bytes(10)})
    r = await hass.config_entries.flow.async_init(
        DOMAIN, context={"source": config_entries.SOURCE_BLUETOOTH}, data=info
    )
    assert r["type"] is FlowResultType.ABORT and r["reason"] == "not_supported"


async def test_user_flow_lists_nameless_pod(hass):
    info = _service_info(POD2_ADDR, POD2_ADDR, POD2_UUIDS, POD2_MFR)
    with patch(
        "custom_components.hume_pod.config_flow.async_discovered_service_info",
        return_value=[info],
    ):
        r = await hass.config_entries.flow.async_init(
            DOMAIN, context={"source": config_entries.SOURCE_USER}
        )
    assert r["step_id"] == "user"
    assert r["data_schema"].schema[CONF_ADDRESS].container == {POD2_ADDR: f"Body Pod ({POD2_ADDR})"}


async def test_user_flow_explains_passive_proxy(hass):
    info = _service_info(POD2_ADDR, POD2_ADDR, POD2_UUIDS, POD2_MFR, connectable=False)

    def discovered(hass, connectable=True):
        return [] if connectable else [info]

    with patch(
        "custom_components.hume_pod.config_flow.async_discovered_service_info",
        side_effect=discovered,
    ):
        r = await hass.config_entries.flow.async_init(
            DOMAIN, context={"source": config_entries.SOURCE_USER}
        )
    assert r["type"] is FlowResultType.ABORT and r["reason"] == "not_connectable"


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
    entry = await setup_scale(hass, [("Dan", DAN), ("Sam", SAM)])
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


# ---- date of birth entry ----------------------------------------------------


def test_parse_birthdate_formats():
    from datetime import date

    from custom_components.hume_pod.config_flow import parse_birthdate

    today = date(2026, 10, 13)
    assert parse_birthdate("1974-03-21", today) == "1974-03-21"
    assert parse_birthdate("21/03/1974", today) == "1974-03-21"  # UK day-first
    assert parse_birthdate("21.3.1974", today) == "1974-03-21"
    assert parse_birthdate(" 1-1-1990 ", today) == "1990-01-01"
    for bad in ("", None, "31/02/1990", "1974", "next tuesday", "2030-01-01", "1890-01-01"):
        assert parse_birthdate(bad, today) is None, bad


async def test_add_person_typed_uk_date_and_invalid_date(hass, ble):
    entry = await setup_scale(hass, [("Dan", DAN)])
    r = await hass.config_entries.subentries.async_init(
        (entry.entry_id, SUBENTRY_PERSON), context={"source": config_entries.SOURCE_USER}
    )
    r = await hass.config_entries.subentries.async_configure(
        r["flow_id"], {CONF_NAME: "Sam", **SAM, "birthdate": "not a date"}
    )
    assert r["errors"] == {"birthdate": "invalid_birthdate"}
    r = await hass.config_entries.subentries.async_configure(
        r["flow_id"], {CONF_NAME: "Sam", **SAM, "birthdate": "15/06/1990"}
    )
    assert r["type"] is FlowResultType.CREATE_ENTRY
    sam = next(s for s in entry.subentries.values() if s.title == "Sam")
    assert sam.data["birthdate"] == "1990-06-15"


async def test_first_person_invalid_date_shows_error(hass):
    info = MagicMock(
        address=ADDR, rssi=-60, service_uuids=[], manufacturer_data={}, service_data={}
    )
    info.name = "Body Pod 2"
    with patch("custom_components.hume_pod.async_setup_entry", return_value=True):
        r = await hass.config_entries.flow.async_init(
            DOMAIN, context={"source": config_entries.SOURCE_BLUETOOTH}, data=info
        )
        r = await hass.config_entries.flow.async_configure(r["flow_id"], {})
        r = await hass.config_entries.flow.async_configure(
            r["flow_id"], {CONF_NAME: "Dan", **DAN, "birthdate": "2099-01-01"}
        )
        assert r["type"] is FlowResultType.FORM and r["errors"] == {
            "birthdate": "invalid_birthdate"
        }
        r = await hass.config_entries.flow.async_configure(
            r["flow_id"], {CONF_NAME: "Dan", **DAN, "birthdate": "01/01/1974"}
        )
    assert r["type"] is FlowResultType.CREATE_ENTRY
    (sub,) = r["result"].subentries.values()
    assert sub.data["birthdate"] == "1974-01-01"


# ---- connection diagnostics -------------------------------------------------


async def test_connect_failure_reported(hass, ble, caplog):
    from bleak.exc import BleakError

    await setup_scale(hass, [("Dan", DAN)])

    async def fail(*a, **kw):
        raise BleakError("Device disappeared")

    await step_on(hass, ble, [], connect=fail, rssi=-94)
    st = hass.states.get("sensor.body_pod_status")
    assert st.state == "error"
    assert "couldn't connect" in st.attributes["last_error"]
    assert "-94" in st.attributes["last_error"]
    assert st.attributes["via"] == "proxy-1"
    assert hass.states.get("sensor.body_pod_signal_strength").state == "-94"
    assert "couldn't connect" in caplog.text and "WARNING" in caplog.text


async def test_silent_scale_gives_up_quickly(hass, ble):
    await setup_scale(hass, [("Dan", DAN)])
    with patch("custom_components.hume_pod.scale.NO_DATA_TIMEOUT", 0.05):
        await step_on(hass, ble, [], disconnect_after=False)
    st = hass.states.get("sensor.body_pod_status")
    assert st.state == "error"
    assert "sent no data" in st.attributes["last_error"]


async def test_unexpected_gatt_layout_reported(hass, ble):
    await setup_scale(hass, [("Dan", DAN)])
    client = await step_on(hass, ble, weigh_in(93.05), layout={"ffe0": {"ffe1": ["notify"]}})
    assert client.written == []  # nothing sent to an unknown device
    st = hass.states.get("sensor.body_pod_status")
    assert st.state == "error"
    assert "missing fff1, fff4" in st.attributes["last_error"]
    assert "ffe1(notify)" in st.attributes["last_error"]


async def test_write_without_response_when_required(hass, ble):
    await setup_scale(hass, [("Dan", DAN)])
    layout = {"fff0": {"fff1": ["write-without-response"], "fff4": ["notify"]}}
    client = await step_on(hass, ble, weigh_in(93.05), layout=layout)
    assert client.responses == [False]
    assert hass.states.get("sensor.dan_weight").state == "93.05"
    st = hass.states.get("sensor.body_pod_status")
    assert st.state == "idle" and st.attributes["last_error"] is None


# ---- real Body Pod 2 behaviour --------------------------------------------------


async def test_real_pod2_weigh_in_replay(hass, ble):
    """Single person whose setup estimate was well off still gets the reading."""
    entry = await setup_scale(hass, [("Dan", {**DAN, "expected_weight": 75.0})])
    statuses = []
    hass.bus.async_listen(
        "state_changed",
        lambda ev: (
            statuses.append(ev.data["new_state"].state)
            if ev.data["entity_id"] == "sensor.body_pod_status" and ev.data["new_state"]
            else None
        ),
    )
    events = []
    hass.bus.async_listen(EVENT_MEASUREMENT, events.append)

    await step_on(hass, ble, REAL_POD2_PACKETS)

    assert hass.states.get("sensor.dan_weight").state == "63.5"
    assert events[-1].data["person"] == "Dan"
    assert events[-1].data["match_reason"] == "only_new_person"
    assert events[-1].data["composition"] is False
    assert "analysing" in statuses  # weight-locked stage shown while waiting
    assert hass.states.get("sensor.body_pod_status").state == "idle"

    # Battery and device info read from the standard GATT services
    assert hass.states.get("sensor.body_pod_battery").state == "87"
    device = dr.async_get(hass).async_get_device({(DOMAIN, entry.entry_id)})
    assert device.sw_version == "002.000.004.000"
    assert device.model_id == "Body Pod 2"
    assert device.hw_version == "V1"
