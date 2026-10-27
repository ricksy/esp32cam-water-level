#!/usr/bin/env python3
"""Capture a labelled series of snapshots for Phase 1 bench tests.

Example: ball 20 cm below the lens, three LED levels:
    python3 tools/bench_capture.py 20 --led 10 30 60
Images land in captures/bench/<distance>cm_<res>_led<duty>_<n>.jpg
"""
import argparse
import pathlib
import urllib.request

parser = argparse.ArgumentParser()
parser.add_argument("distance_cm", type=float, help="lens to ball centre, cm")
parser.add_argument("--host", default="water-tank.local")
parser.add_argument("--res", default="UXGA")
parser.add_argument("--led", type=int, nargs="+", default=[30])
parser.add_argument("--settle", type=int, default=500)
parser.add_argument("--count", type=int, default=3)
args = parser.parse_args()

out = pathlib.Path(__file__).resolve().parent.parent / "captures" / "bench"
out.mkdir(parents=True, exist_ok=True)

# The first frame after idle can still have a colour cast; throw it away.
urllib.request.urlopen(f"http://{args.host}/capture.jpg?res=VGA", timeout=20).read()

for led in args.led:
    for n in range(args.count):
        url = f"http://{args.host}/capture.jpg?res={args.res}&led={led}&settle={args.settle}"
        data = urllib.request.urlopen(url, timeout=20).read()
        path = out / f"{args.distance_cm:g}cm_{args.res}_led{led}_{n}.jpg"
        path.write_bytes(data)
        print(f"{path.relative_to(out.parent.parent)}  {len(data)} B")
