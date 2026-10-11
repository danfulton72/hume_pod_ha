# Hume Body Pod for Home Assistant

[![Validate](https://github.com/danfulton72/hume_pod_ha/actions/workflows/validate.yml/badge.svg)](https://github.com/danfulton72/hume_pod_ha/actions/workflows/validate.yml)
[![Tests](https://github.com/danfulton72/hume_pod_ha/actions/workflows/tests.yml/badge.svg)](https://github.com/danfulton72/hume_pod_ha/actions/workflows/tests.yml)

A local, cloud-free Home Assistant integration for the **Hume Health Body Pod** smart scale. It talks to the scale over Bluetooth (any HA Bluetooth adapter or ESPHome Bluetooth proxy), so weigh-ins need no Hume account or phone. Several people can share one scale: each weigh-in is matched to the right person automatically by weight and body fat.

Protocol and body-composition maths are based on [Blue2Scale](https://github.com/JozefJarosciak/Blue2Scale.com) by Jozef Jarosciak, ported from JavaScript to Python.

## How it works

1. The Body Pod sleeps until you tap or step on it, then advertises over BLE for ~30 seconds.
2. Home Assistant sees the advertisement, connects, and starts a measurement.
3. The scale streams weight packets and, once you've stood still barefoot for ~10–15 s, segmental impedance at ~50 kHz and ~250 kHz.
4. The integration works out who it was (see below), computes 39 body-composition metrics with that person's profile, and updates their sensors.

Weigh-ins with socks on (or stepping off early) still record **weight** and **BMI**; body-composition sensors keep their previous values.

## Installation

**HACS:** HACS → ⋮ → Custom repositories → add `https://github.com/danfulton72/hume_pod_ha` as type *Integration* → install **Hume Body Pod** → restart Home Assistant.

**Manual:** copy `custom_components/hume_pod` into your `config/custom_components/` folder and restart.

Requires Home Assistant 2025.6 or newer with Bluetooth working, and the scale in range of an adapter or [ESPHome Bluetooth proxy](https://esphome.io/components/bluetooth_proxy.html) that supports active connections. The integration's own icon shows in HA 2026.3 and later.

## Setup

Tap the scale to wake it. HA should show a *Discovered: Body Pod* card; otherwise go to **Settings → Devices & services → Add integration → Hume Body Pod**. Setup asks for the first person's details.

To add more people, open the integration and choose **Add person**. To change someone's height, date of birth and so on, use the ⋮ menu next to their name → **Reconfigure**. Age is recalculated from date of birth at every weigh-in.

Giving each person an **approximate weight** when you add them lets the very first weigh-ins be matched straight away.

## Who stepped on? Automatic matching

For every weigh-in the integration compares the reading with each person's previous weigh-in:

- **Weight**: a person is only considered if the reading is within the *weight tolerance* (default 3 kg) of their last weight.
- **Body fat**: when the reading includes impedance, body fat is calculated with *each candidate's own profile* and compared with their last body fat, scaled by the *body fat tolerance* (default 4 percentage points). This separates people of similar weight.
- The closest person wins. If two people are too close to call, or nobody is within tolerance (a guest, or a big change after a holiday), the reading is kept as an **unassigned weigh-in** instead of polluting anyone's history.
- If someone has no history yet and nobody else matches, their first weigh-in goes to them.

Adjust both tolerances under the integration's **Configure** button.

### Unassigned weigh-ins

The scale device has an **Unassigned weigh-in** sensor showing the weight, with attributes explaining why it wasn't matched. Resolve it with:

- `hume_pod.assign_weigh_in`: pick the person's device; the weigh-in is recorded for them, with body composition calculated from their profile.
- `hume_pod.discard_weigh_in`: pick the scale device to throw it away.

An actionable phone notification is a convenient way to do this:

```yaml
automation:
  - alias: Body Pod - who was that?
    triggers:
      - trigger: state
        entity_id: sensor.body_pod_unassigned_weigh_in
        not_to: [unknown, unavailable]
    actions:
      - action: notify.mobile_app_phone
        data:
          message: "Unassigned weigh-in: {{ trigger.to_state.state }} kg"
          data:
            actions:
              - action: HUME_ASSIGN_DAN
                title: Dan
              - action: HUME_ASSIGN_SAM
                title: Sam
              - action: HUME_DISCARD
                title: Discard

  - alias: Body Pod - handle answer
    triggers:
      - trigger: event
        event_type: mobile_app_notification_action
        event_data: { action: HUME_ASSIGN_DAN }
        id: dan
      - trigger: event
        event_type: mobile_app_notification_action
        event_data: { action: HUME_ASSIGN_SAM }
        id: sam
      - trigger: event
        event_type: mobile_app_notification_action
        event_data: { action: HUME_DISCARD }
        id: discard
    actions:
      - choose:
          - conditions: "{{ trigger.id == 'discard' }}"
            sequence:
              - action: hume_pod.discard_weigh_in
                data:
                  scale: "{{ device_id('sensor.body_pod_status') }}"
        default:
          - action: hume_pod.assign_weigh_in
            data:
              person: "{{ device_id('sensor.' ~ trigger.id ~ '_weight') }}"
```

## Entities

**Scale device (`Body Pod`)**: status, unassigned weigh-in, last weigh-in, and live weight (disabled by default).

**One device per person**, linked to the scale:

- Enabled by default: weight, BMI, body fat %, fat mass, visceral fat, lean mass, skeletal muscle mass, body water %, bone mineral, BMR, metabolic age and last measured.
- Disabled by default: subcutaneous fat, android/gynoid fat and ratio, body cell mass, total/extra/intracellular water, mineral, skeletal and organ mass, segmental muscle and fat for each arm, leg and trunk, and the 10 raw impedance readings (diagnostic).

Each person's latest results are stored and survive restarts. Metric sensors use `state_class: measurement` for long-term statistics, and weights follow your HA unit system.

### Event

Every weigh-in fires `hume_pod_measurement`, including the matched `person` (or `null` if unassigned), `match_reason` (`matched`, `only_new_person`, `no_match`, `ambiguous`, `manual`), `match_distances`, all metric values and raw impedances.

## Limitations

- **Estimates, not clinical values.** The scale reports only weight and impedance; everything else comes from published BIA regression equations that Blue2Scale's author calibrated against the Hume app.
- **Not yet verified on real hardware.** Protocol handling is tested with the packet formats documented by Blue2Scale. If your scale advertises under a name other than `Body Pod*` or `Hume*` it won't be auto-discovered; please open an issue with the name shown in **Settings → Bluetooth → Advertisement monitor**.
- The scale itself is always sent the first person's profile to start a measurement. This only affects the scale's own display; HA calculates results with the matched person's profile.
- After a weigh-in the integration ignores the scale for 45 seconds so it doesn't reconnect while the scale is still awake.

## Troubleshooting

Download diagnostics from the integration's ⋮ menu (names, birthdates and the Bluetooth address are redacted), or enable debug logging:

```yaml
logger:
  logs:
    custom_components.hume_pod: debug
```

## Development

```bash
python -m venv .venv && . .venv/bin/activate
pip install -r requirements_test.txt ruff
ruff check . && ruff format --check .
pytest
```

CI runs hassfest, HACS validation, ruff and the test suite on every push.

## Licence

The protocol details and BIA equations are derived from Blue2Scale, which is published under the **Blue2Scale Source-Available License 1.0** (see [BLUE2SCALE_LICENSE](BLUE2SCALE_LICENSE) and [NOTICE](NOTICE)). That licence allows forks and modifications for **non-production (personal, non-commercial) use** only. This project is for personal home use on that basis; ask the Blue2Scale author before using it commercially or submitting it to the default HACS store.
