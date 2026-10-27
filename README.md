# esp32cam-water-level

Measure the water in a tank with an **ESP32-CAM** and a floating **orange
ping-pong ball**, and show it in **Home Assistant**.

The camera sits in the lid and looks down at the ball. The closer the water
gets to the top, the bigger the ball looks. A Home Assistant add-on turns the
ball's apparent size into litres and publishes it over MQTT.

> **Status:** camera firmware and ball detection work on the bench; tank install and the Home Assistant add-on are next. See [docs/PLAN.md](docs/PLAN.md).

## How it works

1. The ESP32-CAM serves a snapshot at `/capture.jpg`, lit by its on-board flash LED.
2. The analyzer add-on fetches a snapshot every minute and finds the orange ball
   (OpenCV, HSV threshold).
3. The ball's diameter in pixels gives its distance: `V = b − a / d`, calibrated
   with a measuring jug.
4. The results go to Home Assistant via MQTT discovery: volume (L), level (%),
   height (cm) and a snapshot camera.

A perforated guide tube keeps the ball centred under the lens. Details are in
[docs/DESIGN.md](docs/DESIGN.md).

## Hardware

* AI-Thinker ESP32-CAM (OV2640) with ESP32-CAM-MB programmer, 5 V USB power
* 40 mm orange ping-pong ball
* ~50 mm perforated PVC tube
* 40 L opaque plastic drum (plasteo, 35 × 35 × 45 cm, Ø 22 cm neck)

See [docs/HARDWARE.md](docs/HARDWARE.md).

## Repository layout

```
firmware/               PlatformIO / Arduino firmware for the ESP32-CAM
analyzer/               Python detection + calibration library and CLI
water_level_analyzer/   Home Assistant add-on (planned, Phase 6)
samples/                Reference images used by the tests
tools/                  Bench capture helper
docs/                   Design, hardware and plan
```

## Home Assistant entities

`sensor.water_tank_volume`, `sensor.water_tank_level`, `sensor.water_tank_height`,
`sensor.water_tank_ball_diameter` (diagnostic), `binary_sensor.water_tank_detection_ok`,
`camera.water_tank_snapshot`.

## License

[MIT](LICENSE)
