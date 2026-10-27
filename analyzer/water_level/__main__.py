"""Command line: analyse snapshots, check a calibration.

    python -m water_level analyze IMAGE_OR_URL... [--calibration cal.json] [--annotate DIR]
    python -m water_level fit cal.json
    python -m water_level serve --options /data/options.json
"""

from __future__ import annotations

import argparse
import json
import logging
import sys
import urllib.request
from pathlib import Path

import cv2
import numpy as np

from .calibrate import Calibration
from .detect import annotate, detect_ball


def _load_image(source: str) -> np.ndarray:
    if source.startswith(("http://", "https://")):
        data = urllib.request.urlopen(source, timeout=30).read()
        image = cv2.imdecode(np.frombuffer(data, np.uint8), cv2.IMREAD_COLOR)
    else:
        image = cv2.imread(source)
    if image is None:
        raise SystemExit(f"cannot read image: {source}")
    return image


def cmd_analyze(args: argparse.Namespace) -> int:
    cal = Calibration.load(args.calibration) if args.calibration else None
    if args.annotate:
        Path(args.annotate).mkdir(parents=True, exist_ok=True)
    failures = 0
    for i, source in enumerate(args.images):
        image = _load_image(source)
        det = detect_ball(image)
        line = f"{source}: "
        if det.ok:
            line += f"{det.diameter_px:.1f} px (fit {det.fit_diameter_px:.1f}, circ {det.circularity:.3f})"
            if cal:
                line += f" -> {cal.litres(det.diameter_px):.1f} L, {cal.percent(det.diameter_px):.0f} %"
        else:
            failures += 1
            line += f"REJECTED {det.reason}"
            if det.diameter_px:
                line += f" ({det.diameter_px:.1f} px)"
        print(line)
        if args.annotate:
            name = Path(source).name if not source.startswith("http") else f"capture_{i}.jpg"
            cv2.imwrite(str(Path(args.annotate) / name), annotate(image, det))
    return 1 if failures == len(args.images) else 0


def cmd_fit(args: argparse.Namespace) -> int:
    cal = Calibration.load(args.calibration)
    print(f"model {cal.model}: V = {cal.b:.2f} - {cal.a:.1f} / d   (full = {cal.full_litres:g} L)")
    for p, r in zip(cal.points, cal.residuals):
        print(f"  {p.diameter_px:7.1f} px  {p.litres:6.2f} L  residual {r:+.2f} L")
    return 0


def cmd_serve(args: argparse.Namespace) -> int:
    from .service import ServiceConfig, serve

    logging.basicConfig(level=logging.DEBUG if args.verbose else logging.INFO,
                        format="%(asctime)s %(levelname)s %(message)s")
    serve(ServiceConfig.from_options(json.loads(Path(args.options).read_text())))
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="water_level")
    sub = parser.add_subparsers(dest="command", required=True)

    p = sub.add_parser("analyze", help="detect the ball in images or URLs")
    p.add_argument("images", nargs="+")
    p.add_argument("--calibration", help="calibration JSON")
    p.add_argument("--annotate", metavar="DIR", help="write annotated images here")
    p.set_defaults(func=cmd_analyze)

    p = sub.add_parser("fit", help="show the fit and residuals of a calibration")
    p.add_argument("calibration")
    p.set_defaults(func=cmd_fit)

    p = sub.add_parser("serve", help="poll the camera and publish to MQTT")
    p.add_argument("--options", default="/data/options.json",
                   help="add-on options JSON (same keys work standalone)")
    p.add_argument("-v", "--verbose", action="store_true")
    p.set_defaults(func=cmd_serve)

    args = parser.parse_args(argv)
    return args.func(args)


if __name__ == "__main__":
    sys.exit(main())
