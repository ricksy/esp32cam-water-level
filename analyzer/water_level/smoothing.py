"""Rolling median over recent diameters, to ride out ripples and odd frames."""

from __future__ import annotations

import statistics
from collections import deque


class RollingMedian:
    def __init__(self, window: int = 5):
        if window < 1:
            raise ValueError("window must be >= 1")
        self._values: deque[float] = deque(maxlen=window)

    def add(self, value: float) -> float:
        self._values.append(value)
        return self.value

    @property
    def value(self) -> float:
        return statistics.median(self._values)

    @property
    def spread(self) -> float:
        """max - min of the window; large while the surface is moving."""
        return max(self._values) - min(self._values)

    def __len__(self) -> int:
        return len(self._values)
