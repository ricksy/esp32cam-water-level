"""Convert apparent ball diameter (px) to litres.

Pinhole camera + straight walls give V = b - a/d: volume is linear in 1/d, so
two measured (litres, diameter) points are enough. Where the drum's walls are
not straight (the shoulder and neck near the top), the residuals of that fit
grow; with enough points we then interpolate piecewise in 1/d instead.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path

import numpy as np


@dataclass(frozen=True)
class CalPoint:
    litres: float
    diameter_px: float


class Calibration:
    # Switch from the 2-parameter model to the table when it misses by more.
    MAX_INVERSE_RESIDUAL_L = 0.5
    MIN_TABLE_POINTS = 4

    def __init__(self, points: list[CalPoint], model: str = "auto",
                 full_litres: float | None = None):
        if len(points) < 2:
            raise ValueError("need at least 2 calibration points")
        if len({p.diameter_px for p in points}) != len(points):
            raise ValueError("calibration diameters must be distinct")
        self.points = sorted(points, key=lambda p: p.diameter_px)
        self.full_litres = full_litres if full_litres is not None else max(p.litres for p in points)

        x = np.array([1.0 / p.diameter_px for p in self.points])
        y = np.array([p.litres for p in self.points])
        slope, intercept = np.polyfit(x, y, 1)
        self.a, self.b = -slope, intercept
        self.residuals = y - (intercept + slope * x)

        if model == "auto":
            fits = np.max(np.abs(self.residuals)) <= self.MAX_INVERSE_RESIDUAL_L
            model = "inverse" if fits or len(points) < self.MIN_TABLE_POINTS else "table"
        if model not in ("inverse", "table"):
            raise ValueError(f"unknown model {model!r}")
        self.model = model
        # np.interp needs increasing x; 1/d falls as d grows, so reverse.
        self._table_x = x[::-1]
        self._table_y = y[::-1]

    def litres(self, diameter_px: float) -> float:
        x = 1.0 / diameter_px
        if self.model == "inverse":
            return float(self.b - self.a * x)
        tx, ty = self._table_x, self._table_y
        if x < tx[0]:  # fuller than the last point: extend the end segment
            return float(ty[0] + (x - tx[0]) * (ty[1] - ty[0]) / (tx[1] - tx[0]))
        if x > tx[-1]:  # emptier than the first point
            return float(ty[-1] + (x - tx[-1]) * (ty[-1] - ty[-2]) / (tx[-1] - tx[-2]))
        return float(np.interp(x, tx, ty))

    def percent(self, diameter_px: float) -> float:
        return 100.0 * self.litres(diameter_px) / self.full_litres

    @classmethod
    def from_dict(cls, data: dict) -> Calibration:
        points = [CalPoint(float(p["litres"]), float(p["diameter_px"])) for p in data["points"]]
        return cls(points, model=data.get("model", "auto"), full_litres=data.get("full_litres"))

    @classmethod
    def load(cls, path: str | Path) -> Calibration:
        return cls.from_dict(json.loads(Path(path).read_text()))
