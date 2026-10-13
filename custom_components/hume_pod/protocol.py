"""BLE protocol for the Hume Body Pod (Lefu-based "Body Pod" scale).

Pure Python, no Home Assistant imports, so it can be unit tested on its own.

Protocol notes derived from Blue2Scale's BLE_SCALE_PROTOCOL.md by Jozef Jarosciak
(https://github.com/JozefJarosciak/Blue2Scale.com).
"""

from __future__ import annotations

from dataclasses import dataclass, field

SERVICE_UUID = "0000fff0-0000-1000-8000-00805f9b34fb"
CHAR_WRITE_UUID = "0000fff1-0000-1000-8000-00805f9b34fb"  # user profile command
CHAR_RW_UUID = "0000fff2-0000-1000-8000-00805f9b34fb"  # secondary notify (optional)
CHAR_NOTIFY_UUID = "0000fff4-0000-1000-8000-00805f9b34fb"  # primary notify

HEADER_WEIGHT = 0xCF
HEADER_IMPEDANCE = 0xBE
HEADER_EXTENDED = 0xDF

MIN_WEIGHT_KG = 5.0

SEGMENTS = ("right_arm", "left_arm", "trunk", "right_leg", "left_leg")

ACTIVITY_SEDENTARY = 0
ACTIVITY_MODERATE = 1
ACTIVITY_ACTIVE = 2


NAME_PREFIXES = ("body pod", "hume")


def _address_bytes(address: str) -> bytes | None:
    try:
        raw = bytes.fromhex(address.replace(":", "").replace("-", ""))
    except ValueError:
        return None
    return raw if len(raw) == 6 else None


def looks_like_body_pod(
    name: str | None,
    address: str,
    service_uuids: list[str] | tuple[str, ...],
    manufacturer_data: dict[int, bytes],
) -> bool:
    """Identify a Body Pod from its advertisement.

    Some units (e.g. Body Pod 2) don't advertise a name at all. Those are
    recognised by the FFF0 service plus Lefu-style manufacturer data, whose
    payload starts with the scale's own Bluetooth address.
    """
    if (name or "").strip().lower().startswith(NAME_PREFIXES):
        return True
    if SERVICE_UUID not in [u.lower() for u in service_uuids]:
        return False
    mac = _address_bytes(address)
    if mac is None:  # e.g. macOS hides real addresses; fall back to name only
        return False
    return any(payload[:6] in (mac, mac[::-1]) for payload in manufacturer_data.values())


def is_placeholder_name(name: str | None, address: str) -> bool:
    """HA uses the address as the name when a device advertises none."""
    if not name:
        return True
    norm = name.replace("-", ":").upper()
    return norm == address.upper() or _address_bytes(name) is not None


def _le16(data: bytes, offset: int) -> int:
    return data[offset] | (data[offset + 1] << 8)


def build_user_command(male: bool, age: int, height_cm: float, activity: int) -> bytes:
    """Build the 8-byte profile command written to FFF1 to start a measurement.

    Layout: FE, user_id, sex, activity, height_cm, age, unit(kg), xor(bytes 1..6)
    """
    user_id = 0x01
    sex = 0x01 if male else 0x00
    act = min(max(int(activity), 0), 2)
    height = min(max(round(height_cm), 0), 255)
    age_b = min(max(int(age), 0), 255)
    unit = 0x01
    checksum = (user_id ^ sex ^ act ^ height ^ age_b ^ unit) & 0xFF
    return bytes([0xFE, user_id, sex, act, height, age_b, unit, checksum])


@dataclass(frozen=True)
class WeightPacket:
    weight_kg: float
    stable: bool


@dataclass(frozen=True)
class ImpedancePacket:
    """Index 0 = low frequency (~50 kHz), 1 = high frequency (~250 kHz)."""

    index: int
    ohms: tuple[float, float, float, float, float]


@dataclass(frozen=True)
class ExtendedPacket:
    index: tuple[int, int]
    raw: bytes


Packet = WeightPacket | ImpedancePacket | ExtendedPacket


def decode_packet(data: bytes | bytearray) -> Packet | None:
    """Decode one notification. Returns None for unknown/short packets.

    Note: the trailing byte is documented as an XOR checksum, but captured
    sample packets don't satisfy plain XOR, so it is deliberately not validated.
    """
    data = bytes(data)
    if not data:
        return None
    header = data[0]

    if header == HEADER_WEIGHT and len(data) >= 5:
        return WeightPacket(weight_kg=_le16(data, 3) / 100, stable=bool(data[2] & 0x80))

    if header == HEADER_IMPEDANCE and len(data) >= 12:
        values = tuple(_le16(data, 2 + i * 2) / 10 for i in range(5))
        return ImpedancePacket(index=data[1], ohms=values)  # type: ignore[arg-type]

    if header == HEADER_EXTENDED and len(data) >= 4:
        return ExtendedPacket(index=(data[2], data[3]), raw=data)

    return None


@dataclass
class MeasurementSession:
    """Accumulates packets from one weigh-in."""

    last_weight_kg: float | None = None
    stable_weight_kg: float | None = None
    impedance: dict[int, tuple[float, ...]] = field(default_factory=dict)
    extended: dict[tuple[int, int], bytes] = field(default_factory=dict)
    _last_raw: bytes | None = None

    def feed(self, data: bytes | bytearray) -> Packet | None:
        """Feed a raw notification; returns the decoded packet (None if dup/unknown)."""
        data = bytes(data)
        if data == self._last_raw:
            return None  # scale repeats packets; drop exact duplicates
        self._last_raw = data
        pkt = decode_packet(data)
        if isinstance(pkt, WeightPacket):
            if pkt.weight_kg > MIN_WEIGHT_KG:
                self.last_weight_kg = pkt.weight_kg
                if pkt.stable:
                    self.stable_weight_kg = pkt.weight_kg
        elif isinstance(pkt, ImpedancePacket):
            self.impedance[pkt.index] = pkt.ohms
        elif isinstance(pkt, ExtendedPacket):
            self.extended[pkt.index] = pkt.raw
        return pkt

    @property
    def weight_kg(self) -> float | None:
        return self.stable_weight_kg or self.last_weight_kg

    @property
    def has_impedance(self) -> bool:
        return 0 in self.impedance and 1 in self.impedance
