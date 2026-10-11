"""Body composition (BIA) maths for the Hume Body Pod.

The scale only reports weight + segmental impedance at two frequencies; every
body-composition figure is estimated here. Equations are a Python port of
Blue2Scale's ble-bia.js (https://github.com/JozefJarosciak/Blue2Scale.com),
which its author calibrated against the manufacturer's app. Treat the outputs
as consumer-scale estimates, not clinical values.
"""

from __future__ import annotations

from collections.abc import Sequence
import math

SEG_NAMES = ("right_arm", "left_arm", "trunk", "right_leg", "left_leg")
SEG_WEIGHT = {
    True: (0.062, 0.062, 0.528, 0.174, 0.174),
    False: (0.054, 0.054, 0.510, 0.191, 0.191),
}
FAT_DIST = {
    True: (0.058, 0.058, 0.515, 0.137, 0.137),
    False: (0.055, 0.055, 0.400, 0.190, 0.190),
}
MUSCLE_FRAC = (0.80, 0.80, 0.833, 0.81, 0.81)


def _r1(v: float) -> float:
    return round(v + 0.0, 1)


def _r2(v: float) -> float:
    return round(v + 0.0, 2)


def _js_round(v: float) -> int:
    """Math.round semantics (half rounds up) to match the reference implementation."""
    return math.floor(v + 0.5)


def impedance_is_valid(imp: Sequence[float]) -> bool:
    """Reject readings taken with socks on / poor contact (zeros or absurd values)."""
    return len(imp) >= 5 and all(0 < z < 3000 for z in imp[:5])


def compute_bmi(weight_kg: float, height_cm: float) -> float:
    hm = height_cm / 100
    return _r1(weight_kg / (hm * hm))


def compute_body_composition(
    imp_low: Sequence[float],
    imp_high: Sequence[float],
    weight_kg: float,
    height_cm: float,
    age: int,
    male: bool,
) -> dict[str, float | int]:
    w = weight_kg
    h = height_cm

    z_right = imp_low[0] + imp_low[2] + imp_low[3]
    z_left = imp_low[1] + imp_low[2] + imp_low[4]
    z_total = (z_right + z_left) / 2
    imp_index = (h * h) / z_total

    tbw = 0.464 * imp_index + 0.19 * w + 3.03 if male else 0.39 * imp_index + 0.107 * w + 8.3
    ecw_ratio = 0.37 if male else 0.385
    tbw_r = _r1(tbw)
    ecw = _r1(tbw_r * ecw_ratio)
    icw = _r1(tbw_r - ecw)
    water_pct = _r1(tbw / w * 100)

    ffm = tbw / 0.731
    fat_mass = _r1(max(0.0, w - ffm))
    body_fat_pct = _r1(fat_mass / w * 100)

    bone_mineral = _r1(0.054 * ffm)
    mineral_mass = _r1(0.014 * ffm)
    lean_mass = _r1(w - fat_mass - bone_mineral - mineral_mass)
    lean_mass_pct = _r1(lean_mass / w * 100)
    skeletal_mass = _r1(0.167 * ffm)
    organ_mass = _r1(0.134 * ffm)

    subcut_fat = _r1(fat_mass * 0.87)
    subcut_fat_pct = _r1(subcut_fat / w * 100)

    bmi = compute_bmi(w, h)
    visceral = max(1, min(59, _js_round(bmi * 0.54 - 2.5 if male else bmi * 0.42 - 3.0)))
    bmr = _js_round(370 + 21.2 * ffm)
    metabolic_age = max(
        18,
        min(99, _js_round(age + (body_fat_pct - (25 if male else 32)) * 1.03)),
    )
    body_cell_mass = _r1(icw / 0.7)
    smm = _r1(lean_mass - skeletal_mass - organ_mass)

    seg_w = SEG_WEIGHT[male]
    fat_d = FAT_DIST[male]
    seg_muscle_raw: dict[str, float] = {}
    seg_fat_kg: dict[str, float] = {}
    seg_fat_pct: dict[str, float] = {}
    for i, name in enumerate(SEG_NAMES):
        sw = w * seg_w[i]
        sf = min(fat_mass * fat_d[i], sw * 0.6)
        seg_muscle_raw[name] = (sw - sf) * MUSCLE_FRAC[i]
        seg_fat_kg[name] = _r1(sf)
        seg_fat_pct[name] = _r1(sf / max(sw, 0.1) * 100)

    raw_sum = sum(seg_muscle_raw.values())
    scale = smm / raw_sum if raw_sum > 0 else 1
    seg_muscle = {n: _r1(v * scale) for n, v in seg_muscle_raw.items()}

    android = _r1(seg_fat_kg["trunk"] * 0.78)
    gynoid = _r1((seg_fat_kg["right_leg"] + seg_fat_kg["left_leg"]) * 1.41)
    ag_ratio = _r1(android / max(gynoid, 0.1) * 100)

    result: dict[str, float | int] = {
        "weight": _r2(w),
        "bmi": bmi,
        "body_fat": body_fat_pct,
        "fat_mass": fat_mass,
        "subcutaneous_fat_mass": subcut_fat,
        "subcutaneous_fat": subcut_fat_pct,
        "visceral_fat": visceral,
        "android_fat": android,
        "gynoid_fat": gynoid,
        "android_gynoid_ratio": ag_ratio,
        "lean_mass": lean_mass,
        "lean_mass_percentage": lean_mass_pct,
        "skeletal_muscle_mass": smm,
        "body_cell_mass": body_cell_mass,
        "body_water": water_pct,
        "total_body_water": _r1(tbw),
        "extracellular_water": ecw,
        "intracellular_water": icw,
        "bone_mineral": bone_mineral,
        "mineral_mass": mineral_mass,
        "skeletal_mass": skeletal_mass,
        "organ_mass": organ_mass,
        "bmr": bmr,
        "metabolic_age": metabolic_age,
    }
    for n in SEG_NAMES:
        result[f"{n}_muscle"] = seg_muscle[n]
        result[f"{n}_fat"] = seg_fat_pct[n]
        result[f"{n}_fat_mass"] = seg_fat_kg[n]
    return result
