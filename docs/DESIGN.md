# Design

## Goal

Report how much water is in a 40 L plastic drum to Home Assistant, once a
minute, with no electronics touching the water.

## System overview

```
 ┌──────────── lid ────────────┐
 │  ESP32-CAM  (lens + LED ↓)  │        Wi-Fi         ┌──────────────── Home Assistant OS ────────────────┐
 └─────────────┬───────────────┘   GET /capture.jpg   │                                                   │
               │ guide tube       ◄───────────────────┤  water_level_analyzer add-on (Python + OpenCV)   │
               │ (perforated)     ────── JPEG ───────►│    detect ball → diameter px → litres            │
               │                                      │                │ MQTT (discovery)                 │
            ( ● ) ← orange ball                       │                ▼                                  │
  ~~~~~~~~~~~~~~~~~~~~ water ~~~~~~                   │  Mosquitto add-on ──► sensor.water_tank_volume …  │
 └──────────────────────────────┘                     └───────────────────────────────────────────────────┘
```

* **ESP32-CAM (AI-Thinker, OV2640, ESP32-D0WD-V3, 4 MB flash)**: a "dumb" camera.
  It serves one JPEG per request, firing the white flash LED (GPIO4) only for
  the exposure.
* **Analyzer (HA add-on)**: pulls a snapshot every 60 s, finds the ball, converts
  it to a level and volume, and publishes via MQTT with HA discovery.
* **Mosquitto (existing add-on)**: transport to HA.

### Why process on the server

* OpenCV in Python is far easier to tune than colour thresholds in C on the ESP32.
* Raw and annotated images can be kept for debugging and calibration.
* Firmware stays tiny and rarely needs reflashing.
* Cost: the ESP32 depends on the HA host being up. That's fine, because HA is
  needed to display the value anyway.

## Measurement principle

A ping-pong ball has a fixed diameter **D = 40 mm**. It floats with only about
7 mm submerged: it weighs 2.7 g, so it displaces 2.7 cm³. Its widest circle sits
a constant ~13 mm above the water surface. Seen from above, the ball's apparent
diameter `d` (pixels) follows the pinhole model:

```
d = f · D / Z         Z = distance from lens to ball
```

The water height is `h = H_cam − Z − const`. For straight or near-straight walls,
the volume is `V = A · h`. Substituting gives:

```
V = b − a / d
```

**Volume is linear in 1/d.** We never need the focal length, the camera height
or the tank area separately. Two calibration points (known litres, measured
`d`) fix `a` and `b`. More points give a least-squares fit and expose any taper.
If the fit residuals show taper, the analyzer switches to piecewise-linear
interpolation over a calibration table instead of the 2-parameter model.

### Why a guide tube

The OV2640 stock lens has a horizontal FOV of roughly 50–60°. That means the
visible patch of tank is about as wide as the distance to it. With the ball
10 cm away, the camera sees only ~10 × 8 cm of a 35 × 45 cm tank, so a
free-floating ball is out of frame most of the time once the tank is half full.

A vertical **perforated pipe, ~46–50 mm inner diameter**, from floor to lid,
directly under the lens:

* keeps the ball on the optical axis, so there's no off-axis distortion and it's
  always in frame
* calms surface ripples and prevents the ball sticking in a corner
* gives a fixed, uniform background (paint the inside matte black to cut flash glare)

Alternative if a tube is undesirable: a 120°/160° replacement lens. This needs
per-position distortion correction, and the ball can still hide under the lid
edge. It's rejected for v1.

### Expected resolution

Assumptions: UXGA (1600 × 1200), ~54° horizontal FOV → f ≈ 1570 px, interior
footprint ≈ 1400 cm² (≈ 1.4 L per cm). These numbers must be verified in
Phase 1.

| Lens → ball (Z) | Ball diameter | 1 px change ≈ | Volume per px |
|-----------------|---------------|---------------|---------------|
| 43 cm (empty)   | ~146 px       | 0.29 cm       | ~0.4 L        |
| 25 cm (half)    | ~251 px       | 0.10 cm       | ~0.14 L       |
| 10 cm (full)    | ~628 px       | 0.016 cm      | ~0.02 L       |

Sub-pixel diameter (from contour area) plus a median over several readings
gives better than ±0.5 L across the range. Accuracy is worst when the tank is
nearly empty.

### Usable range / headroom

The ball must stay ≥ ~10 cm below the lens. Closer than that, it fills the frame
and is badly out of focus. This defines **"full"** as roughly 8–10 cm below the
lid, so the usable capacity is less than the nominal 40 L. The analyzer reports
`over_max` when the ball touches the frame edges.

## Image pipeline (analyzer)

1. `GET http://<esp32>/capture.jpg` (timeout 10 s, 2 retries).
2. Decode → crop to a configurable ROI (the tube opening).
3. Convert to HSV and threshold orange (default H 5–25, S > 120, V > 80, configurable).
4. Morphological open, then close, then **fill holes**. The flash makes a white
   specular highlight on the ball, which would otherwise punch a hole in the mask.
5. Take the largest contour. Reject it if area < min, if circularity
   `4πA/P²` < 0.75, or if it touches the image border.
6. Diameter = `2·sqrt(area/π)` (sub-pixel), cross-checked against `minEnclosingCircle`.
7. Push to a rolling window (default 5), take the median, and convert with the
   calibration to litres, cm and %.
8. Publish. Every N minutes (and on failure), save the raw and annotated JPEGs to
   `/share/water_level/`.

## Home Assistant entities (MQTT discovery)

| Entity | Unit | Notes |
|---|---|---|
| `sensor.water_tank_volume` | L | `device_class: volume_storage`, `state_class: measurement` |
| `sensor.water_tank_level` | % | of calibrated full |
| `sensor.water_tank_height` | cm | water height above floor |
| `sensor.water_tank_ball_diameter` | px | diagnostic; used for calibration |
| `binary_sensor.water_tank_detection_ok` | – | `problem` class, on when detection fails |
| `camera.water_tank_snapshot` | – | MQTT camera with the annotated last image |

Availability topic: the add-on sets an LWT, and the analyzer also marks entities
unavailable if the ESP32 is unreachable for > 5 min.

## Firmware (ESP32-CAM)

PlatformIO + Arduino framework (`esp32-camera` driver).

| Endpoint | Purpose |
|---|---|
| `GET /capture.jpg` | LED on (PWM) → wait for AE → discard 1 stale frame → capture → LED off → return JPEG |
| `GET /health` | JSON: uptime, RSSI, free heap, PSRAM, last capture ms, reset reason |
| `POST /config` | optional: resolution, JPEG quality, LED duty, settle ms (persisted to NVS) |
| OTA (ArduinoOTA) | updates without opening the lid |

* **Flash LED**: GPIO4, LEDC PWM. Start at ~30 % duty and tune. It's on for
  only ~200 ms per minute, so heat and current stay low.
* Camera settings are fixed after warm-up (AWB/AE locked, or set manually), so
  colour thresholds stay stable.
* A watchdog reboots the board if the camera init or Wi-Fi fails, and it
  reconnects to Wi-Fi with backoff.
* Wi-Fi credentials live in `firmware/include/secrets.h` (git-ignored, template committed).
* Static DHCP lease or mDNS (`water-tank.local`) so the analyzer can find it.

## Calibration

1. Empty the tank and record `d` (diagnostic sensor) → point (0 L, d₀).
2. Add water with a measuring jug in 5 L steps. After each step wait 1 min and
   record `(litres, d)`.
3. Enter the points in the add-on options:
   ```yaml
   calibration:
     - { litres: 0,  diameter_px: 146.2 }
     - { litres: 5,  diameter_px: 158.9 }
     ...
   ```
4. The add-on logs the fit type and residuals. "Full" = the highest calibrated
   point, or `max_litres`.

## Risks and mitigations

| Risk | Mitigation |
|---|---|
| Condensation fogs the lens in a closed humid drum | Mount behind a small clear window (acrylic) a few mm above the lid, anti-fog coating, keep LED duty low; detection-fail sensor alerts |
| Flash glare on the water/ball | Matte black tube interior, low LED duty, hole filling in the mask |
| ESP32-CAM brownouts (known issue) | Good 5 V/2 A supply, 470 µF cap at the 5 V pin, brownout reset logged in `/health` |
| Ball sticks to the tube wall | Smooth PVC, ID ≥ 46 mm, perforations large enough for water to equalise quickly |
| Colour drift (AWB) | Lock AWB/exposure in firmware; thresholds configurable |
| Food-safe water contact | Ball and tube are the only parts in water; use food-grade PP/PVC pipe and a new ball |
| Lens focus | OV2640 lens can be turned to adjust focus; set it for ~25 cm (mid-range) |
