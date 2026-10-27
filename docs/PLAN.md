# Plan

Phases are ordered so each one produces something testable before the next one
starts.

## Phase 0: Project setup ✅
- [x] Requirements and design ([DESIGN.md](DESIGN.md), [HARDWARE.md](HARDWARE.md))
- [x] Repo, MIT license, README
- [x] Board identified: AI-Thinker ESP32-CAM, ESP32-D0WD-V3, 4 MB flash, CH340 on `/dev/ttyUSB0`

## Phase 1: Camera bring-up and feasibility
- [ ] PlatformIO project in `firmware/`, minimal sketch: Wi-Fi + `/capture.jpg` + flash LED
- [ ] Confirm PSRAM and that UXGA capture works reliably
- [ ] Take test shots of the ball at known distances (10, 20, 30, 43 cm) on the bench
- [ ] Measure the real FOV/focal length and update the resolution table in DESIGN.md
- [ ] Find the LED duty that lights the tube without blowing out the image
- **Exit:** the ball is clearly segmentable at 10 cm and 43 cm, in the dark, with the LED.

## Phase 2: Firmware v1
- [ ] `secrets.h` template, mDNS `water-tank.local`
- [ ] `/health` JSON, `/config` persisted to NVS
- [ ] Fixed AWB/AE after warm-up, discard stale frame before capture
- [ ] ArduinoOTA, watchdog, Wi-Fi reconnect with backoff
- [ ] 24 h soak test: 1 capture/min with no hang or brownout

## Phase 3: Analyzer core (offline)
- [ ] `analyzer/` Python package: `detect.py` (HSV → mask → contour → diameter), `calibrate.py` (fit `V = b − a/d` and piecewise fallback)
- [ ] CLI: `python -m water_level analyze image.jpg` → diameter + annotated image
- [ ] Sample images from Phase 1 committed under `samples/`, with pytest tests on them
- [ ] Rolling median, rejection rules (area, circularity, border touch)

## Phase 4: Mechanical install
- [ ] Cut and perforate the guide tube, blacken the inside, fix it under the lens
- [ ] Mount the ESP32-CAM on the lid behind a clear window, route USB power
- [ ] Set focus at ~25 cm, check framing (tube centred in ROI)

## Phase 5: Calibration and accuracy
- [ ] Empty → full in 5 L steps with a measuring jug, record diameters
- [ ] Fit, check residuals (taper?), choose the model
- [ ] Verify with 3 independent random fills: target error ≤ ±0.5 L
- [ ] Determine the real usable max (headroom limit)

## Phase 6: Home Assistant add-on
- [ ] `repository.yaml` at repo root, add-on in `water_level_analyzer/` (`config.yaml`, `Dockerfile`, `run.sh`)
- [ ] Options: ESP32 URL, interval, ROI, HSV thresholds, calibration points, MQTT (auto from Mosquitto service)
- [ ] MQTT discovery for the entities listed in DESIGN.md, plus availability
- [ ] Debug images to `/share/water_level/`
- [ ] Install via "Add-on store → Repositories → this GitHub URL"

## Phase 7: Hardening and automations
- [ ] Alert automations: low water (< 20 %), detection failing > 10 min, device offline
- [ ] Lovelace example card (gauge + snapshot)
- [ ] Long-term check after 2 weeks: fogging, algae, drift; re-tune
- [ ] v1.0.0 release tag

## Open questions
- Exact usable height: where must "full" be, given the lid and the 10 cm headroom?
- Is a guide tube acceptable inside the drum (it costs ~1–2 L of capacity)?
- How does the water get in and out (tap at the bottom, or scooped from the top)? A scoop could knock the tube.
