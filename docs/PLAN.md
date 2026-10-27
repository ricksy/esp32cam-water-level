# Plan

Phases are ordered so each one produces something testable before the next one
starts.

## Phase 0: Project setup ✅
- [x] Requirements and design ([DESIGN.md](DESIGN.md), [HARDWARE.md](HARDWARE.md))
- [x] Repo, MIT license, README
- [x] Board identified: AI-Thinker ESP32-CAM, ESP32-D0WD-V3, 4 MB flash, CH340 on `/dev/ttyUSB0`

## Phase 1: Camera bring-up and feasibility
- [x] PlatformIO project in `firmware/`, minimal sketch: Wi-Fi + `/capture.jpg` + flash LED, `/health`, OTA, mDNS `water-tank.local`
- [x] Confirm PSRAM (4 MB) and UXGA capture (~105 KB, ~0.8 s incl. 500 ms LED settle)
- [x] Full-size transfers got cut off on weak Wi-Fi: firmware now writes in chunks until a deadline
- [x] Colour stability: auto WB → 13 px spread; fixed preset `wb=1` (sunny) → 1.2 px. Default set to sunny
- [x] Dark background (black T-shirt): 412.4 / 412.3 px, circularity 0.989, no spill, no ghost
- [x] LED duty: no effect at ~15 cm, but at ~40 cm the edges go dark below ~60 % (30 %: 124 px, 100 %: 173–178 px). Default now 100 %, mask V > 40
- [x] Red power LED on the MB board leaks a faint glow; tape over it in the final install
- [x] Measured 34 cm → 180.0 px → f ≈ 1617 px (52.6° HFOV, 63.5° diagonal); resolution table updated
- [x] One bad frame in the 34 cm series was the room light switched on briefly. Room light swamps the LED, so the tank lid must stay closed. As a precaution, the firmware discards 3 extra frames after a resolution switch, and the bench script warms up at the target size
- [ ] Optional: one more measured point near 12 cm to confirm the model at the full-tank end
- [ ] Recheck LED duty inside the tube (glare), once Phase 4 hardware exists
- **Exit:** the ball is clearly segmentable at 10 cm and 43 cm, in the dark, with the LED.

## Phase 2: Firmware v1
- [ ] `secrets.h` template, mDNS `water-tank.local`
- [ ] `/health` JSON, `/config` persisted to NVS
- [ ] Fixed AWB/AE after warm-up, discard stale frame before capture
- [ ] ArduinoOTA, watchdog, Wi-Fi reconnect with backoff
- [ ] 24 h soak test: 1 capture/min with no hang or brownout
- [ ] Wi-Fi is marginal on the desk (RSSI −67…−72, ~5 s per 100 KB UXGA, software resets after Wi-Fi loss): check RSSI at the tank, consider a crop window (only the tube matters) or lower resolution / JPEG quality

## Phase 3: Analyzer core (offline) ✅
- [x] `analyzer/` Python package: `detect.py` (HSV → mask → convex hull diameter + RANSAC circle cross-check), `calibrate.py` (fit `V = b − a/d`, auto piecewise fallback)
- [x] CLI: `python -m water_level analyze IMAGE|URL [--calibration] [--annotate DIR]`, `fit cal.json`
- [x] 9 sample images from Phase 1 in `samples/`, 36 pytest tests (real + synthetic images)
- [x] Rolling median with spread, rejection rules (`no_ball`, `too_small`, `touches_border`, `not_round`, `occluded`)
- [ ] Known limit: a dim ball (LED < 60 % at far range) is accepted but measured too small; relies on LED 100 %
- [ ] Possibly add `too_dark` / room-light detection (background brightness) once tank images exist

## Phase 4: Mechanical install
- [ ] Lid layout: guide tube/camera opposite the dryer inlet, grommet for drip tubes + pump cable
- [ ] Route the dryer inlet so it doesn't splash into the guide tube
- [ ] Cut and perforate the guide tube, blacken the inside, fix it under the lens
- [ ] Mount the ESP32-CAM on the lid behind a clear window, route USB power
- [ ] Set focus at ~25 cm, check framing (tube centred in ROI)

## Phase 5: Calibration and accuracy
- [ ] Define "empty" = Gardena pump intake level (what the pump can no longer draw)
- [ ] Empty → full in 5 L steps with a measuring jug, record diameters
- [ ] Fit, check residuals (taper?), choose the model
- [ ] Verify with 3 independent random fills: target error ≤ ±0.5 L
- [ ] Determine the real usable max (headroom limit)

## Phase 6: Home Assistant add-on (code done, install pending)
- [x] `repository.yaml` at repo root, add-on in `water_level_analyzer/` (`config.yaml`, `build.yaml`, `Dockerfile`, `DOCS.md`, translations)
- [x] Service `python -m water_level serve`: poll, detect, median, calibrate, publish; keeps last good level on rejected frames
- [x] Options: camera URL, interval, median window, ROI, HSV thresholds, calibration points, MQTT (auto from Mosquitto service)
- [x] MQTT discovery (6 entities, one device), availability + LWT + offline on SIGTERM
- [x] Debug images to `/share/water_level/` (latest, annotated, last 50 failed)
- [x] 10 service tests; end-to-end run against a local broker and the live camera
- [x] Dockerfile installs the package from the `v<version>` release tarball (tested locally with `#subdirectory=analyzer`)
- [ ] Push + tag `v0.1.0`, then install via "Add-on store → ⋮ → Repositories → https://github.com/ricksy/esp32cam-water-level"
- [ ] First Docker build on the HA machine (couldn't build locally, no Docker here)
- [ ] Give the camera a fixed DHCP lease, set `camera_url` to its IP

## Phase 7: Hardening and automations
- [ ] Alert automations: overflow (≥ 90 % / ≥ 97 %), low water (< 20 %), detection failing > 10 min, device offline
- [ ] Gardena pump dry-run cut-off via smart plug (< 5 %)
- [ ] Inflow/watering event detection (step changes) with litres per event
- [ ] Lovelace example card (gauge + snapshot)
- [ ] Long-term check after 2 weeks: fogging, algae, drift; re-tune
- [ ] v1.0.0 release tag

## Open questions
- Exact usable height: where must "full" be, given the lid and the 10 cm headroom?
- Is a guide tube acceptable inside the drum (it costs ~1–2 L of capacity)?
- Gardena pump model? (e.g. holiday irrigation set 1265; its intake height sets "empty")
- Is the pump plugged in through a smart plug HA can switch (needed for the dry-run cut-off)?
- Is the dryer controllable/visible in HA (smart plug with power metering, so a dryer run can be detected)?
- Where does the dryer hose end: through the lid, or a hole in the neck?
