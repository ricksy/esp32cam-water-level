"""Water level from an orange float ball seen by an ESP32-CAM."""

from .calibrate import CalPoint, Calibration
from .detect import Detection, DetectionParams, annotate, detect_ball
from .smoothing import RollingMedian

__all__ = ["CalPoint", "Calibration", "Detection", "DetectionParams", "RollingMedian",
           "annotate", "detect_ball"]
