# Water Level Analyzer

Fetches a snapshot from the ESP32-CAM every minute, finds the orange
ping-pong ball, converts its apparent size to litres and publishes it to
Home Assistant over MQTT (auto-discovered).

## Requirements

- The Mosquitto broker add-on (MQTT credentials are picked up automatically).
- The ESP32-CAM running this project's firmware, reachable from Home Assistant.

## Setup

1. Set **Camera URL** to `http://<camera IP>/capture.jpg`. Give the camera a
   fixed DHCP lease in your router; add-ons often can't resolve `.local` names.
2. Start the add-on. The device **Water Tank** appears under MQTT with:

   | Entity | |
   |---|---|
   | Volume (L) | needs calibration |
   | Level (%) | needs calibration |
   | Ball diameter (px) | diagnostic, use it to calibrate |
   | Surface spread (px) | diagnostic, large while water pours in |
   | Detection problem | on when a frame is rejected; the reason is an attribute |
   | Snapshot | annotated last frame |

3. **Calibrate.** For at least two known volumes (e.g. empty, then after
   pouring in measured litres), wait two minutes and note **Ball diameter**.
   Enter the pairs under **Calibration points** and restart. The log shows the
   fit and its residuals. "Empty" is where the irrigation pump stops drawing water.

## Problem reasons

| Reason | Meaning |
|---|---|
| `camera_unreachable` | Snapshot could not be fetched (power, Wi-Fi, wrong URL) |
| `no_ball` | Nothing orange: lens fogged, LED failed, ball out of view |
| `touches_border` | Ball cut off by the frame edge or ROI |
| `not_round` / `occluded` | Ball partly hidden, or mask spill (lint, glare) |
| `too_small` | Only a tiny orange speck found |

During a problem the last good level is kept. Snapshots are in
`/share/water_level/` (`latest.jpg`, `latest_annotated.jpg`, `failed/`).
