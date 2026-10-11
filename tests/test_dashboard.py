"""Tests for the dashboard card feed and card serving."""

import json
import pathlib
import re

from homeassistant.setup import async_setup_component
import pytest

from .test_integration import DAN, SAM, setup_scale, step_on, weigh_in

pytestmark = pytest.mark.usefixtures("enable_custom_integrations")

COMPONENT = pathlib.Path(__file__).parents[1] / "custom_components" / "hume_pod"


def test_card_version_matches_manifest():
    manifest = json.loads((COMPONENT / "manifest.json").read_text())
    card = (COMPONENT / "frontend" / "hume-pod-card.js").read_text()
    assert re.search(r'const CARD_VERSION = "([^"]+)"', card).group(1) == manifest["version"]


async def test_websocket_feed(hass, hass_ws_client, ble):
    entry = await setup_scale(hass, [("Dan", DAN), ("Sam", SAM)])
    client = await hass_ws_client(hass)
    await client.send_json_auto_id({"type": "hume_pod/subscribe"})
    assert (await client.receive_json())["success"]

    snap = (await client.receive_json())["event"]
    (scale,) = snap["scales"]
    assert scale["entry_id"] == entry.entry_id and scale["device_id"]
    names = {p["name"]: p for p in scale["people"]}
    assert set(names) == {"Dan", "Sam"}
    assert names["Dan"]["sex"] == "male" and names["Dan"]["measured_at"] is None
    assert names["Dan"]["entities"]["weight"] == "sensor.dan_weight"
    # Disabled-by-default sensors aren't offered for charting
    assert "trunk_muscle" not in names["Dan"]["entities"]

    await step_on(hass, ble, weigh_in(93.05))
    latest = None
    while True:  # status/live-weight updates arrive first; take the final state
        msg = await client.receive_json()
        latest = msg["event"]
        dan = next(p for p in latest["scales"][0]["people"] if p["name"] == "Dan")
        if dan["measured_at"]:
            break
    assert dan["data"]["body_fat"] == 34.7
    assert dan["data"]["trunk_muscle"] > 0  # full data even though sensor is disabled

    await step_on(hass, ble, weigh_in(130.0))
    while True:
        latest = (await client.receive_json())["event"]
        if latest["scales"][0]["pending"]:
            break
    assert latest["scales"][0]["pending"]["weight"] == 130.0
    assert latest["scales"][0]["pending"]["reason"] == "no_match"


async def test_card_is_served(hass, hass_client, ble):
    assert await async_setup_component(hass, "http", {})
    await setup_scale(hass, [("Dan", DAN)])
    client = await hass_client()
    resp = await client.get("/hume_pod_static/hume-pod-card.js")
    assert resp.status == 200
    assert 'customElements.define("hume-pod-card"' in await resp.text()
