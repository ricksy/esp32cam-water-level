import json

import pytest

from water_level import CalPoint, Calibration

A, B = 6000.0, 45.0  # V = B - A/d: 0 L at 133 px, ~28 L at 360 px


def inverse_points(diameters):
    return [CalPoint(B - A / d, d) for d in diameters]


def test_two_points_define_the_model():
    cal = Calibration(inverse_points([140, 400]))
    assert cal.model == "inverse"
    assert cal.a == pytest.approx(A)
    assert cal.b == pytest.approx(B)
    assert cal.litres(250) == pytest.approx(B - A / 250)


def test_many_points_on_the_curve_stay_inverse():
    cal = Calibration(inverse_points([140, 170, 210, 260, 330, 420]))
    assert cal.model == "inverse"
    assert max(abs(r) for r in cal.residuals) < 1e-9


def test_taper_switches_to_table_and_hits_points():
    points = inverse_points([140, 170, 210, 260, 330])
    # Shoulder near the top: last litres come with much less level change.
    points.append(CalPoint(points[-1].litres + 4.0, 345))
    cal = Calibration(points)
    assert cal.model == "table"
    for p in points:
        assert cal.litres(p.diameter_px) == pytest.approx(p.litres)


def test_table_extrapolates_continuously():
    points = inverse_points([140, 170, 210, 260])
    points[1] = CalPoint(points[1].litres + 2, 170)  # force a bad inverse fit
    cal = Calibration(points, model="table")
    eps = 1e-6
    for d in (140, 260):
        assert cal.litres(d + eps) == pytest.approx(cal.litres(d - eps), abs=1e-3)
    assert cal.litres(300) > cal.litres(260)
    assert cal.litres(120) < cal.litres(140)


def test_percent_uses_full_litres():
    cal = Calibration(inverse_points([140, 400]), full_litres=40)
    assert cal.percent(400) == pytest.approx(100 * (B - A / 400) / 40)


def test_full_defaults_to_highest_point():
    points = inverse_points([140, 400])
    assert Calibration(points).full_litres == max(p.litres for p in points)


@pytest.mark.parametrize("points, model", [
    ([CalPoint(0, 140)], "auto"),
    ([CalPoint(0, 140), CalPoint(5, 140)], "auto"),
    (inverse_points([140, 400]), "cubic"),
])
def test_invalid_calibrations(points, model):
    with pytest.raises(ValueError):
        Calibration(points, model=model)


def test_load_json(tmp_path):
    path = tmp_path / "cal.json"
    path.write_text(json.dumps({
        "full_litres": 38,
        "points": [{"litres": p.litres, "diameter_px": p.diameter_px}
                   for p in inverse_points([140, 400])],
    }))
    cal = Calibration.load(path)
    assert cal.full_litres == 38
    assert cal.litres(250) == pytest.approx(B - A / 250)
