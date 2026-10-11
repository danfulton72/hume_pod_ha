# Hume Body Pod for Home Assistant

A local, cloud-free Home Assistant integration for the **Hume Health Body Pod** smart scale. It talks to the scale over Bluetooth (any HA Bluetooth adapter or ESPHome Bluetooth proxy), so no Hume account or phone is needed for weigh-ins.

Protocol and body-composition maths are based on [Blue2Scale](https://github.com/JozefJarosciak/Blue2Scale.com) by Jozef Jarosciak, ported from JavaScript to Python.

## How it works

1. The Body Pod sleeps until you tap or step on it, then advertises over BLE for ~30 seconds.
2. Home Assistant sees the advertisement, connects, and writes your profile (sex, age, height, activity) to characteristic `FFF1`.
3. The scale streams weight packets (`0xCF`) and, once you've stood still barefoot for ~10–15 s, two segmental impedance packets (`0xBE`) at ~50 kHz and ~250 kHz.
4. The integration computes 39 body-composition metrics from weight + impedance and updates the sensors.

Weigh-ins with socks on (or stepping off early) still record **weight** and **BMI**; the body-composition sensors keep their previous values.

## Installation

**HACS (custom repository):** HACS → ⋮ → Custom repositories → add this repo as *Integration* → install **Hume Body Pod** → restart.

**Manual:** copy `custom_components/hume_pod` into your HA `config/custom_components/` folder and restart.

Requires Home Assistant 2025.1+ with the Bluetooth integration working, and the scale within range of an adapter or [ESPHome Bluetooth proxy](https://esphome.io/components/bluetooth_proxy.html) that supports active connections.

## Setup

Tap the scale to wake it. HA should show a *Discovered: Body Pod* card; otherwise go to **Settings → Devices & services → Add integration → Hume Body Pod**.

You'll be asked for a name and your body profile. Age is worked out from your date of birth at each weigh-in. Edit the profile later via **Configure** on the integration.

## Entities

Each profile becomes a device named `Body Pod (<name>)`.

Enabled by default: weight, BMI, body fat %, fat mass, visceral fat, lean mass, skeletal muscle mass, body water %, bone mineral, BMR, metabolic age, last measured, status.

Disabled by default (enable in the entity list): subcutaneous fat, android/gynoid fat and ratio, body cell mass, total/extra/intracellular water, mineral, skeletal and organ mass, segmental muscle and fat for each arm, leg and trunk, a live weight sensor, and the 10 raw impedance readings (diagnostic).

Metric sensors restore their last value after a restart and use `state_class: measurement`, so they get long-term statistics. Weights follow your HA unit system (kg or lb).

### Event

Every weigh-in fires `hume_pod_measurement` with all values, the raw impedances, and `composition: true/false`. Useful for notifications or forwarding to other services:

```yaml
automation:
  - alias: Weigh-in notification
    triggers:
      - trigger: event
        event_type: hume_pod_measurement
    actions:
      - action: notify.mobile_app_phone
        data:
          message: >
            {{ trigger.event.data.weight }} kg
            {% if trigger.event.data.composition %}· {{ trigger.event.data.body_fat }}% fat{% endif %}
```

## Limitations

- **One person per scale for now.** Only one profile can be bound to a given scale (the config entry is keyed on the scale's Bluetooth address). Multi-user support would need to pick the profile per weigh-in (e.g. closest previous weight); the raw impedance in the event makes it possible to recompute for another person in an automation in the meantime.
- **Estimates, not clinical values.** The scale reports only weight and impedance; every other figure comes from published BIA regression equations that Blue2Scale's author calibrated against the Hume app. Expect numbers close to, but not identical with, the Hume app.
- **Not yet tested on real hardware by this integration.** Protocol handling is covered by tests using the packet formats documented by Blue2Scale. If your scale advertises under a name other than `Body Pod*` or `Hume*`, it won't be auto-discovered; please open an issue with the name from **Settings → Bluetooth → Advertisement monitor**.
- After each weigh-in the integration ignores the scale for 45 seconds so it doesn't reconnect while the scale is still awake.

## Troubleshooting

Enable debug logging:

```yaml
logger:
  logs:
    custom_components.hume_pod: debug
```

## Licence

The protocol details and BIA equations are derived from Blue2Scale, which is published under the **Blue2Scale Source-Available License 1.0**. That licence allows forking and modification for **non-production (personal, non-commercial) use** only, and requires keeping its notice. This project is intended for personal home use on that basis. Ask the Blue2Scale author before publishing it more widely or using it commercially.
