from unittest.mock import patch

import pytest

pytest_plugins = ["pytest_homeassistant_custom_component"]


@pytest.fixture
def ble():
    state = {}

    def register(hass, cb, matcher, mode):
        state["cb"] = cb
        return lambda: None

    with (
        patch("custom_components.hume_pod.bluetooth.async_scanner_count", return_value=1),
        patch(
            "custom_components.hume_pod.scale.bluetooth.async_register_callback",
            side_effect=register,
        ),
        patch(
            "custom_components.hume_pod.scale.bluetooth.async_ble_device_from_address",
            return_value=None,
        ),
    ):
        yield state
