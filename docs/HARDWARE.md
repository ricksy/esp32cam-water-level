# Hardware

## Bill of materials

| Item | Notes |
|---|---|
| AI-Thinker ESP32-CAM + ESP32-CAM-MB (CH340) | Already owned. OV2640, flash LED on GPIO4, 4 MB flash, PSRAM |
| 5 V / 2 A USB power supply + cable | Weak supplies cause brownouts on the ESP32-CAM |
| 470 µF electrolytic capacitor | Across 5 V / GND, optional but recommended |
| Orange ping-pong ball, 40 mm | New, clean. Matte (not glossy) reduces glare |
| Guide tube, PVC/PP, ID 46–50 mm, ~45 cm | Food-grade (e.g. DN50 HT pipe), drilled with Ø8–10 mm holes along its length, and slots at the bottom so the ball still rests on the floor when empty |
| Matte black paint (food-safe), or a black liner | Inside of the tube |
| Small clear acrylic window (~40 × 40 mm) | Seals the camera away from humidity |
| Enclosure / 3D-printed mount for the lid | Holds the board with the lens centred over the tube |

## Board

AI-Thinker ESP32-CAM (ESP32-D0WD-V3, 4 MB flash) with an OV2640 sensor
(`TY-OV2640-V2.0` flex, stock lens) on an ESP32-CAM-MB programmer (CH340,
micro-USB, IO0 + RST buttons).

![ESP32-CAM on ESP32-CAM-MB](images/esp32-cam-board.jpg)

* The **white flash LED** (bottom right in the photo, GPIO4) is ~2.5 cm away from
  the lens. Under a shared window, the flash reflects off the acrylic straight
  into the lens. To avoid that, put a **foam/rubber divider** between LED and
  lens, pressed against the window, or give each its own hole/window.
* Peel off the red protective tab on the lens.
* The lens is the standard ~66° (diagonal) type. Its focus can be adjusted by
  turning it (break the glue dot carefully).
* The MB board's micro-USB doubles as the 5 V power input in the final install.

## Tank

plasteo 40 L wide-neck drum (Weithalsfass), blue, opaque, with a screw lid.

![plasteo 40 L drum](images/plasteo-40l-drum.jpg)

* Footprint **35 × 35 cm** with chamfered corners; total height **45 cm**
  *including* the neck and lid. (The "45 × 35 × 45" in the listing is wrong;
  the drum is 35 × 35.)
* Square body ≈ 33 cm tall (35 × 35 × 33 ≈ 40 L), then a shoulder, then a
  round **neck, opening Ø 22 cm**, about 10 cm tall.
* The camera sits in the screw lid, so the lens is ~10 cm above the top of the
  body. Water in the shoulder/neck has a much smaller area per cm. That's the
  reason calibration falls back to a piecewise table near the top.
* A free-floating ball could hide under the shoulder, out of the camera's
  view. One more reason for the guide tube.
* **Volume is set by calibration, not by the dimensions.**
* Opaque blue walls: the inside is dark, so every photo uses the flash. The blue
  background also helps the orange segmentation.

## What else is in the tank

| Item | Where | Effect on the measurement |
|---|---|---|
| **Inlet hose, 25 mm** (yellow/blue striped), condensate from the tumble dryer | Through the neck/lid, outlet near the top | Falling water causes ripples and splashes, so the ball bobs during a dryer run. Condensate is warm and humid, which makes lens fogging more likely. Lint can float on the surface |
| **Gardena irrigation pump** (submersible) | On the tank floor | Takes up floor space, so the guide tube must stand beside it. The pump stops drawing water below its intake, so that level is the practical "empty". Watering runs cause sudden level drops |
| **2 × ~5 mm drip tubes + pump power cable** | From the pump up through the neck | More things competing for room in the 22 cm opening |

### Lid layout (Ø 22 cm opening)

```
            ┌───── lid, Ø 22 cm ─────┐
           /                          \
          │   (●)            ◯         │   ◯  25 mm dryer inlet, kept away from the tube
          │  guide tube     inlet      │      so it doesn't splash into it
          │  + camera                  │   (●) camera window over the Ø50 guide tube
          │            ·  ·  ▪         │   · · ▪  2 drip tubes + pump cable (grommet)
           \                          /
            └──────────────────────────┘
```

* Inlet and guide tube on opposite sides. If possible, extend the inlet below
  the water line (or angle it at the wall) so it doesn't splash.
* The guide tube stands on the floor next to the pump. It must not rest on the
  pump or its cable.
* The tube's perforations help here too: they damp the ripples from inflow
  and pumping, so the ball inside stays calm.

## Mounting

```
        USB 5V ──► [ESP32-CAM in enclosure]
                   ───────[ acrylic window ]─────── lid (hole Ø ~30 mm)
                          │                 │
                          │  guide tube     │  ← hangs from the lid or stands on the floor
                          │  (black inside) │
                          │      ( ● )      │  ← ball
                          │ o    ~~~~~    o │  ← perforations
                          │ o               │
                          └──┘           └──┘ ← bottom slots
```

* The lens must look straight down the tube axis.
* If the tube stands on the floor, the lid can be removed without disturbing it.
  If it hangs from the lid, everything comes out together for cleaning. Pick
  whichever suits how you take water out.
* Keep the board outside the humid air space. Only the window faces the water.

## Wiring

No external wiring beyond power. The flash LED (GPIO4) is on the board. The
ESP32-CAM-MB is used only for flashing; in the tank it can stay attached as a
USB power adapter.

## Flashing

```bash
cd firmware
pio run -t upload --upload-port /dev/ttyUSB0
pio device monitor -b 115200
```
After the first flash, updates go over the air (`pio run -t upload --upload-port water-tank.local`).
