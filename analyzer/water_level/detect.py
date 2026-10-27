"""Find the orange float ball in a snapshot and measure its apparent diameter."""

from __future__ import annotations

import math
from dataclasses import dataclass, field

import cv2
import numpy as np


@dataclass
class DetectionParams:
    # HSV (OpenCV ranges: H 0..179, S/V 0..255). V is low on purpose: with the
    # ball 34+ cm away its edges are much darker than its centre.
    hue_min: int = 3
    hue_max: int = 28
    sat_min: int = 80
    val_min: int = 40
    # Region of interest (x, y, w, h) in full-image pixels; None = whole image.
    roi: tuple[int, int, int, int] | None = None
    min_diameter_px: float = 40.0
    min_circularity: float = 0.85
    # Area-based and circle-fit diameters must agree within this fraction.
    max_fit_disagreement: float = 0.03
    # Fraction of the outline that must lie on the fitted circle.
    min_arc_fraction: float = 0.5
    border_margin_px: int = 3


@dataclass
class Detection:
    ok: bool
    reason: str | None = None
    diameter_px: float | None = None
    center: tuple[float, float] | None = None
    circularity: float | None = None
    fit_diameter_px: float | None = None
    arc_fraction: float | None = None
    contour: np.ndarray | None = field(default=None, repr=False)


def _mask(hsv: np.ndarray, p: DetectionParams) -> np.ndarray:
    mask = cv2.inRange(hsv, (p.hue_min, p.sat_min, p.val_min), (p.hue_max, 255, 255))
    # Kernel sizes scale with the image so VGA and UXGA behave alike.
    k = max(3, hsv.shape[1] // 320) | 1
    mask = cv2.morphologyEx(mask, cv2.MORPH_OPEN, np.ones((k, k), np.uint8))
    return cv2.morphologyEx(mask, cv2.MORPH_CLOSE, np.ones((2 * k + 1, 2 * k + 1), np.uint8))


def fit_circle(points: np.ndarray, tol: float, iterations: int = 300,
               seed: int = 0) -> tuple[float, float, float, float] | None:
    """RANSAC circle fit; returns (cx, cy, r, inlier fraction) or None.

    Only points on the visible arc vote, so a partly hidden ball or mask spill
    on one side does not bias the radius the way an area measurement would.
    """
    if len(points) < 3:
        return None
    rng = np.random.default_rng(seed)
    pts = points.astype(float)
    best, best_count = None, 0
    for _ in range(iterations):
        a, b, c = pts[rng.choice(len(pts), 3, replace=False)]
        lhs = 2 * np.array([b - a, c - a])
        if abs(np.linalg.det(lhs)) < 1e-6:
            continue
        rhs = np.array([b @ b - a @ a, c @ c - a @ a])
        cx, cy = np.linalg.solve(lhs, rhs)
        r = math.hypot(*(a - (cx, cy)))
        count = int(np.sum(np.abs(np.hypot(*(pts - (cx, cy)).T) - r) < tol))
        if count > best_count:
            best, best_count = (cx, cy, r), count
    if best is None:
        return None

    # Least-squares refinement on the inliers.
    cx, cy, r = best
    inliers = pts[np.abs(np.hypot(*(pts - (cx, cy)).T) - r) < tol]
    lhs = np.c_[2 * inliers, np.ones(len(inliers))]
    sol = np.linalg.lstsq(lhs, (inliers ** 2).sum(axis=1), rcond=None)[0]
    cx, cy = sol[:2]
    r = math.sqrt(sol[2] + cx * cx + cy * cy)
    return cx, cy, r, len(inliers) / len(pts)


def detect_ball(image: np.ndarray, params: DetectionParams | None = None) -> Detection:
    """Locate the ball in a BGR image. Rejected frames carry a `reason`."""
    p = params or DetectionParams()
    ox, oy = 0, 0
    if p.roi:
        ox, oy, w, h = p.roi
        image = image[oy:oy + h, ox:ox + w]

    hsv = cv2.cvtColor(image, cv2.COLOR_BGR2HSV)
    contours, _ = cv2.findContours(_mask(hsv, p), cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_NONE)
    if not contours:
        return Detection(ok=False, reason="no_ball")

    contour = max(contours, key=cv2.contourArea)
    # The convex hull bridges the printed logo and the specular highlight.
    hull = cv2.convexHull(contour)
    area = cv2.contourArea(hull)
    perimeter = cv2.arcLength(hull, True)
    diameter = 2 * math.sqrt(area / math.pi)
    circularity = 4 * math.pi * area / perimeter ** 2 if perimeter else 0.0
    (cx, cy), _ = cv2.minEnclosingCircle(contour)
    result = Detection(ok=False, diameter_px=diameter, center=(cx + ox, cy + oy),
                       circularity=circularity, contour=contour + (ox, oy))

    if diameter < p.min_diameter_px:
        result.reason = "too_small"
        return result

    pts = contour[:, 0, :]
    m = p.border_margin_px
    height, width = image.shape[:2]
    on_border = ((pts[:, 0] < m) | (pts[:, 1] < m)
                 | (pts[:, 0] >= width - m) | (pts[:, 1] >= height - m))
    if on_border.any():
        result.reason = "touches_border"
        return result

    if circularity < p.min_circularity:
        result.reason = "not_round"
        return result

    fit = fit_circle(pts, tol=max(2.0, diameter * 0.01))
    if fit is None:
        result.reason = "not_round"
        return result
    _, _, r, arc_fraction = fit
    result.fit_diameter_px = 2 * r
    result.arc_fraction = arc_fraction
    if (arc_fraction < p.min_arc_fraction
            or abs(2 * r - diameter) / diameter > p.max_fit_disagreement):
        result.reason = "occluded"
        return result

    result.ok = True
    return result


def annotate(image: np.ndarray, det: Detection) -> np.ndarray:
    """Copy of `image` with the detection drawn on it, for debugging."""
    out = image.copy()
    scale = max(1, image.shape[1] // 640)
    colour = (0, 200, 0) if det.ok else (0, 0, 255)
    if det.contour is not None:
        cv2.drawContours(out, [cv2.convexHull(det.contour)], -1, colour, 2 * scale)
    if det.ok:
        label = f"{det.diameter_px:.1f} px"
    else:
        label = det.reason or "?"
        if det.diameter_px:
            label += f" ({det.diameter_px:.1f} px)"
    cv2.putText(out, label, (10 * scale, 30 * scale), cv2.FONT_HERSHEY_SIMPLEX,
                scale, colour, 2 * scale)
    return out
