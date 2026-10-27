#!/usr/bin/env python3
"""Soak test: capture once a minute, log transfer, detection and board health.

Run from analyzer/ so the water_level package is importable:
    uv run python ../tools/soak.py --hours 24
Writes captures/soak.csv; a summary line goes to stdout every hour.
"""
import argparse
import csv
import json
import time
import urllib.request
from datetime import datetime
from pathlib import Path

import cv2
import numpy as np

from water_level import detect_ball

parser = argparse.ArgumentParser()
parser.add_argument("--host", default="192.168.178.98")
parser.add_argument("--hours", type=float, default=24)
parser.add_argument("--interval", type=int, default=60)
args = parser.parse_args()

out = Path(__file__).resolve().parent.parent / "captures" / "soak.csv"
out.parent.mkdir(exist_ok=True)
fields = ["time", "http", "bytes", "seconds", "error", "ok", "reason", "diameter_px",
          "uptime_s", "reset_reason", "rssi", "wifi_reconnects", "captures", "capture_failures"]
new_file = not out.exists()
log = out.open("a", newline="")
writer = csv.DictWriter(log, fieldnames=fields)
if new_file:
    writer.writeheader()

end = time.time() + args.hours * 3600
count = failures = reboots = 0
last_uptime = None
while time.time() < end:
    started = time.time()
    row = {"time": datetime.now().isoformat(timespec="seconds")}
    try:
        with urllib.request.urlopen(f"http://{args.host}/capture.jpg", timeout=30) as resp:
            data = resp.read()
            row["http"] = resp.status
        row["bytes"] = len(data)
        image = cv2.imdecode(np.frombuffer(data, np.uint8), cv2.IMREAD_COLOR)
        if image is None:
            raise ValueError("undecodable JPEG")
        det = detect_ball(image)
        row.update(ok=det.ok, reason=det.reason,
                   diameter_px=round(det.diameter_px, 2) if det.diameter_px else None)
    except Exception as e:
        row["error"] = f"{type(e).__name__}: {e}"
    row["seconds"] = round(time.time() - started, 2)
    try:
        with urllib.request.urlopen(f"http://{args.host}/health", timeout=10) as resp:
            health = json.load(resp)
        row.update({k: health.get(k) for k in
                    ("uptime_s", "reset_reason", "rssi", "wifi_reconnects", "captures", "capture_failures")})
        if last_uptime is not None and health["uptime_s"] < last_uptime:
            reboots += 1
        last_uptime = health["uptime_s"]
    except Exception as e:
        row["error"] = (row.get("error") or "") + f" health {type(e).__name__}"

    count += 1
    failures += 0 if row.get("ok") else 1
    writer.writerow(row)
    log.flush()
    if count % 60 == 0:
        print(f"{row['time']} {count} captures, {failures} failed, {reboots} reboots, "
              f"rssi {row.get('rssi')}", flush=True)
    time.sleep(max(1, args.interval - (time.time() - started)))

print(f"done: {count} captures, {failures} failed/rejected, {reboots} board reboots -> {out}")
