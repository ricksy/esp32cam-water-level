from pathlib import Path

import cv2
import numpy as np
import pytest

from water_level import DetectionParams, annotate, detect_ball

SAMPLES = Path(__file__).resolve().parents[2] / "samples"


def load(name: str) -> np.ndarray:
    image = cv2.imread(str(SAMPLES / name))
    assert image is not None, name
    return image


def synthetic_ball(radius: int, size=(1200, 1600), center=(800, 600)) -> np.ndarray:
    image = np.full((*size, 3), 20, np.uint8)  # dark tank
    cv2.circle(image, center, radius, (40, 140, 245), -1)  # orange in BGR
    return image


@pytest.mark.parametrize("name, expected", [
    ("dark_34cm_a.jpg", 180.0),
    ("dark_34cm_b.jpg", 180.0),
    ("dark_far_led100.jpg", 176.6),
    ("dark_near.jpg", 421.2),
])
def test_bench_samples_are_measured(name, expected):
    det = detect_ball(load(name))
    assert det.ok, det.reason
    assert det.diameter_px == pytest.approx(expected, abs=1.5)
    assert det.circularity > 0.98


def test_repeat_shots_agree():
    a = detect_ball(load("dark_34cm_a.jpg")).diameter_px
    b = detect_ball(load("dark_34cm_b.jpg")).diameter_px
    assert abs(a - b) < 0.5


@pytest.mark.parametrize("name, reason", [
    ("dark_near_edge_cut.jpg", "touches_border"),
    ("desk_cloth_wb1.jpg", "occluded"),
    ("no_ball_desk.jpg", "no_ball"),
    ("no_led_vga.jpg", "no_ball"),
])
def test_bad_frames_are_rejected(name, reason):
    det = detect_ball(load(name))
    assert not det.ok
    assert det.reason == reason


def test_dim_led_underestimates_diameter():
    # Known limitation, and the reason the firmware defaults to 100 % LED:
    # at 30 % the dark ball edges fall below the V threshold.
    dim = detect_ball(load("dark_far_led30_dim.jpg")).diameter_px
    bright = detect_ball(load("dark_far_led100.jpg")).diameter_px
    assert dim < bright * 0.97


def test_resolution_scales_diameter():
    image = load("dark_34cm_a.jpg")
    small = cv2.resize(image, None, fx=0.4, fy=0.4, interpolation=cv2.INTER_AREA)
    assert detect_ball(small).diameter_px == pytest.approx(0.4 * detect_ball(image).diameter_px, rel=0.02)


def test_roi_offsets_center():
    image = load("dark_34cm_a.jpg")
    full = detect_ball(image)
    cx, cy = full.center
    roi = (int(cx) - 200, int(cy) - 200, 400, 400)
    cropped = detect_ball(image, DetectionParams(roi=roi))
    assert cropped.ok
    assert cropped.diameter_px == pytest.approx(full.diameter_px, abs=0.1)
    assert cropped.center == pytest.approx(full.center, abs=0.5)


def test_roi_cutting_the_ball_is_rejected():
    image = load("dark_34cm_a.jpg")
    cx, cy = detect_ball(image).center
    det = detect_ball(image, DetectionParams(roi=(int(cx), int(cy) - 200, 400, 400)))
    assert det.reason == "touches_border"


@pytest.mark.parametrize("radius", [60, 150, 400])
def test_synthetic_ball_diameter(radius):
    det = detect_ball(synthetic_ball(radius))
    assert det.ok, det.reason
    assert det.diameter_px == pytest.approx(2 * radius, rel=0.01)


def test_printed_logo_is_bridged():
    image = synthetic_ball(150)
    cv2.putText(image, "LOGO", (700, 610), cv2.FONT_HERSHEY_SIMPLEX, 2, (10, 10, 10), 8)
    det = detect_ball(image)
    assert det.ok, det.reason
    assert det.diameter_px == pytest.approx(300, rel=0.01)


def test_partly_covered_ball_is_occluded():
    image = synthetic_ball(150)
    cv2.rectangle(image, (850, 0), (1600, 1200), (20, 20, 20), -1)  # hides a third
    assert detect_ball(image).reason in ("occluded", "not_round")


def test_tiny_blob_is_too_small():
    assert detect_ball(synthetic_ball(10)).reason == "too_small"


def test_annotate_keeps_input_untouched():
    image = synthetic_ball(150)
    before = image.copy()
    out = annotate(image, detect_ball(image))
    assert np.array_equal(image, before)
    assert out.shape == image.shape and not np.array_equal(out, image)
