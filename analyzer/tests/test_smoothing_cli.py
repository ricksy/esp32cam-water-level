from pathlib import Path

import pytest

from water_level import RollingMedian
from water_level.__main__ import main

SAMPLES = Path(__file__).resolve().parents[2] / "samples"
EXAMPLE_CAL = Path(__file__).resolve().parents[1] / "calibration.example.json"


def test_rolling_median_ignores_one_outlier():
    m = RollingMedian(window=5)
    for v in (180.0, 180.2, 260.0, 179.9, 180.1):
        m.add(v)
    assert m.value == pytest.approx(180.1)
    assert m.spread == pytest.approx(80.1)


def test_rolling_median_window_slides():
    m = RollingMedian(window=3)
    for v in (1, 2, 3, 10, 11):
        m.add(v)
    assert len(m) == 3
    assert m.value == 10


def test_rolling_median_rejects_empty_window():
    with pytest.raises(ValueError):
        RollingMedian(window=0)


def test_cli_analyze_with_calibration(tmp_path, capsys):
    rc = main(["analyze", str(SAMPLES / "dark_34cm_a.jpg"), str(SAMPLES / "no_ball_desk.jpg"),
               "--calibration", str(EXAMPLE_CAL), "--annotate", str(tmp_path)])
    out = capsys.readouterr().out
    assert rc == 0
    assert "180.1 px" in out and " L, " in out
    assert "REJECTED no_ball" in out
    assert (tmp_path / "dark_34cm_a.jpg").exists()


def test_cli_fails_when_every_frame_is_rejected(capsys):
    assert main(["analyze", str(SAMPLES / "no_ball_desk.jpg")]) == 1


def test_cli_fit(capsys):
    assert main(["fit", str(EXAMPLE_CAL)]) == 0
    assert "model inverse" in capsys.readouterr().out
