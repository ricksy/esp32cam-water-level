# Sample snapshots

Real captures from the Phase 1 bench (ESP32-CAM, UXGA unless noted, white
balance *sunny*). The analyzer tests in `analyzer/tests/` depend on them.

| File | Scene | Expected |
|---|---|---|
| `dark_34cm_a.jpg`, `dark_34cm_b.jpg` | Black background, ball top **34 cm** from lens (measured), LED 100 % | 180.0 px |
| `dark_far_led100.jpg` | Black background, ball ~36 cm (not measured), LED 100 % | 176.6 px |
| `dark_far_led30_dim.jpg` | Same position, LED 30 % | accepted but ~6 % too small (dark edges); why the LED defaults to 100 % |
| `dark_near.jpg` | Black background, ball close (~14 cm, not measured) | 421.2 px |
| `dark_near_edge_cut.jpg` | Ball runs off the bottom of the frame | rejected: `touches_border` |
| `desk_cloth_wb1.jpg` | White cloth partly covering the ball | rejected: `occluded` |
| `no_ball_desk.jpg` | First frame after boot, no ball, green cast | rejected: `no_ball` |
| `no_led_vga.jpg` | VGA, LED off, dark | rejected: `no_ball` |
