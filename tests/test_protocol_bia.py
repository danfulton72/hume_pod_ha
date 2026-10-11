"""Tests against the worked example in Blue2Scale's BLE_SCALE_PROTOCOL.md."""

import importlib.util
import pathlib
import sys

BASE = pathlib.Path(__file__).parents[1] / "custom_components" / "hume_pod"


def _load(name):
    spec = importlib.util.spec_from_file_location(name, BASE / f"{name}.py")
    mod = importlib.util.module_from_spec(spec)
    sys.modules[name] = mod
    spec.loader.exec_module(mod)
    return mod


protocol = _load("protocol")
bia = _load("bia")


def le(vals):
    return b"".join(v.to_bytes(2, "little") for v in vals)


def test_user_command():
    assert protocol.build_user_command(True, 52, 173, 1).hex() == "fe010101ad340199"


def test_weight_packet():
    p = protocol.decode_packet(bytes.fromhex("cf0080512400000000 01a4".replace(" ", "")))
    assert p == protocol.WeightPacket(92.97, True)
    live = protocol.decode_packet(bytes.fromhex("cf0000512400000000 01a4".replace(" ", "")))
    assert live.stable is False


def test_session_flow_and_dedupe():
    s = protocol.MeasurementSession()
    s.feed(bytes.fromhex("cf000000000000000000cf"))  # idle
    s.feed(bytes.fromhex("cf0000a2030000000000aa"))  # 9.30 live
    s.feed(bytes.fromhex("cf00805a2400000000 0000".replace(" ", "")))  # 93.06 stable
    lo = bytes([0xBE, 0]) + le([3319, 3229, 270, 2307, 2321]) + b"\x00"
    assert s.feed(lo) is not None
    assert s.feed(lo) is None  # duplicate dropped
    assert not s.has_impedance
    s.feed(bytes([0xBE, 1]) + le([2951, 2890, 209, 1997, 2037]) + b"\x00")
    assert s.has_impedance and s.weight_kg == 93.06
    assert s.impedance[0] == (331.9, 322.9, 27.0, 230.7, 232.1)


def test_worked_example():
    r = bia.compute_body_composition(
        (331.9, 322.9, 27.0, 230.7, 232.1), (295.1, 289.0, 20.9, 199.7, 203.7), 93.05, 173, 52, True
    )
    assert r["bmi"] == 31.1
    assert r["body_fat"] == 34.7
    assert r["fat_mass"] == 32.3
    assert r["total_body_water"] == 44.4
    assert r["body_water"] == 47.7
    assert r["bmr"] == 1658
    assert r["visceral_fat"] == 14
    assert r["metabolic_age"] == 62
    assert abs(sum(r[f"{n}_muscle"] for n in bia.SEG_NAMES) - r["skeletal_muscle_mass"]) < 0.3
    assert len(r) == 39


def test_bad_contact_rejected():
    assert not bia.impedance_is_valid((0, 0, 0, 0, 0))
    assert bia.impedance_is_valid((331.9, 322.9, 27.0, 230.7, 232.1))
