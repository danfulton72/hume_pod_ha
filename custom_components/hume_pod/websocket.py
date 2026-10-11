"""Websocket feed for the Body Pod dashboard card.

`hume_pod/subscribe` sends a snapshot of every scale and person straight away
and again whenever anything changes. The card uses it instead of reading
sensor states so it can show every metric (including sensors that are
disabled by default) and pick the right body silhouette for each person.
"""

from __future__ import annotations

from typing import Any

from homeassistant.components import websocket_api
from homeassistant.config_entries import ConfigEntryState
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers import device_registry as dr, entity_registry as er
from homeassistant.helpers.dispatcher import async_dispatcher_connect
import voluptuous as vol

from .const import CONF_HEIGHT, CONF_SEX, DOMAIN, SIGNAL_UPDATED


@callback
def async_setup_websocket(hass: HomeAssistant) -> None:
    websocket_api.async_register_command(hass, ws_subscribe)


def _iso(value: Any) -> str | None:
    return value.isoformat() if value else None


@callback
def build_snapshot(hass: HomeAssistant) -> dict[str, Any]:
    dev_reg = dr.async_get(hass)
    ent_reg = er.async_get(hass)
    scales: list[dict[str, Any]] = []

    for entry in hass.config_entries.async_entries(DOMAIN):
        if entry.state is not ConfigEntryState.LOADED:
            continue
        scale = entry.runtime_data
        entry_id = entry.entry_id

        # unique_id -> entity_id for this scale's enabled entities
        by_unique: dict[str, str] = {
            e.unique_id: e.entity_id
            for e in er.async_entries_for_config_entry(ent_reg, entry_id)
            if e.disabled_by is None
        }

        def entities_with_prefix(
            prefix: str, by_unique: dict[str, str] = by_unique
        ) -> dict[str, str]:
            return {
                uid[len(prefix) :]: eid for uid, eid in by_unique.items() if uid.startswith(prefix)
            }

        scale_device = dev_reg.async_get_device({(DOMAIN, entry_id)})
        people = []
        for sid, sub in scale.person_subentries.items():
            state = scale.people.get(sid)
            device = dev_reg.async_get_device({(DOMAIN, f"{entry_id}_{sid}")})
            people.append(
                {
                    "person_id": sid,
                    "name": sub.title,
                    "sex": sub.data.get(CONF_SEX),
                    "height": sub.data.get(CONF_HEIGHT),
                    "device_id": device.id if device else None,
                    "entities": entities_with_prefix(f"{entry_id}_{sid}_"),
                    "data": state.data if state else {},
                    "measured_at": _iso(state.measured_at) if state else None,
                    "composition_at": _iso(state.composition_at) if state else None,
                }
            )

        pending = scale.pending
        scales.append(
            {
                "entry_id": entry_id,
                "name": entry.title,
                "device_id": scale_device.id if scale_device else None,
                "status": scale.status,
                "live_weight": scale.live_weight,
                "last_weigh_in": _iso(scale.last_weigh_in),
                "pending": {
                    "weight": pending.weight,
                    "measured_at": _iso(pending.measured_at),
                    "reason": pending.reason,
                    "has_body_composition": pending.low is not None,
                }
                if pending
                else None,
                "people": people,
            }
        )
    return {"scales": scales}


@websocket_api.websocket_command({vol.Required("type"): f"{DOMAIN}/subscribe"})
@callback
def ws_subscribe(
    hass: HomeAssistant, connection: websocket_api.ActiveConnection, msg: dict[str, Any]
) -> None:
    @callback
    def send() -> None:
        connection.send_message(websocket_api.event_message(msg["id"], build_snapshot(hass)))

    connection.subscriptions[msg["id"]] = async_dispatcher_connect(hass, SIGNAL_UPDATED, send)
    connection.send_result(msg["id"])
    send()
