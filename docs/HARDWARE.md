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
