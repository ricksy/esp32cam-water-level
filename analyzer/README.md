# analyzer

Python library and CLI that finds the orange ball in an ESP32-CAM snapshot and
converts its apparent diameter to litres. See [../docs/DESIGN.md](../docs/DESIGN.md).

```bash
cd analyzer
uv run pytest                                              # tests (use ../samples)
uv run python -m water_level analyze ../samples/*.jpg      # diameters / rejections
uv run python -m water_level analyze http://water-tank.local/capture.jpg \
    --calibration calibration.example.json --annotate /tmp/annotated
uv run python -m water_level fit calibration.example.json  # model + residuals
```

| Module | Purpose |
|---|---|
| `detect.py` | HSV mask, convex-hull diameter, RANSAC circle-fit cross-check, rejection reasons |
| `calibrate.py` | `V = b − a/d` fit, piecewise table fallback for the shoulder/neck |
| `smoothing.py` | Rolling median + spread (unsettled surface) |

Rejection reasons: `no_ball`, `too_small`, `touches_border`, `not_round`, `occluded`.

`calibration.example.json` is generated from the bench focal length and is
**not** a real calibration. Replace it with measured points in Phase 5.
