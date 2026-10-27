"""Long-running service: poll the camera, publish the level to Home Assistant via MQTT.

Runs as the Home Assistant add-on (options from /data/options.json, MQTT
credentials from the Supervisor) or standalone with a JSON config file.
"""

from __future__ import annotations

import json
import logging
import os
import signal
import sys
import time
import urllib.request
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Callable, Protocol

import cv2
import numpy as np

from .calibrate import CalPoint, Calibration
from .detect import Detection, DetectionParams, annotate, detect_ball
from .smoothing import RollingMedian

log = logging.getLogger("water_level")

SNAPSHOT_WIDTH = 800  # published camera image; full UXGA is needlessly heavy for MQTT
MAX_FAILED_IMAGES = 50


@dataclass
class ServiceConfig:
    camera_url: str
    interval_seconds: int = 60
    median_window: int = 5
    calibration: list[CalPoint] = field(default_factory=list)
    full_litres: float | None = None
    detection: DetectionParams = field(default_factory=DetectionParams)
    image_dir: Path | None = None
    save_failed_images: bool = True
    topic_prefix: str = "water_tank"
    discovery_prefix: str = "homeassistant"
    device_name: str = "Water Tank"
    mqtt_host: str | None = None
    mqtt_port: int = 1883
    mqtt_username: str | None = None
    mqtt_password: str | None = None

    @classmethod
    def from_options(cls, opts: dict) -> ServiceConfig:
        """Build from add-on options; unset optional keys keep the defaults."""
        det = DetectionParams()
        for key in ("hue_min", "hue_max", "sat_min", "val_min"):
            if opts.get(key) is not None:
                setattr(det, key, int(opts[key]))
        if opts.get("roi"):
            det.roi = tuple(int(v) for v in str(opts["roi"]).split(","))
            if len(det.roi) != 4:
                raise ValueError("roi must be 'x,y,w,h'")

        cfg = cls(camera_url=opts["camera_url"], detection=det)
        for key in ("interval_seconds", "median_window", "mqtt_port"):
            if opts.get(key) is not None:
                setattr(cfg, key, int(opts[key]))
        for key in ("topic_prefix", "discovery_prefix", "device_name",
                    "mqtt_host", "mqtt_username", "mqtt_password"):
            if opts.get(key):
                setattr(cfg, key, str(opts[key]))
        if opts.get("save_failed_images") is not None:
            cfg.save_failed_images = bool(opts["save_failed_images"])
        if opts.get("image_dir"):
            cfg.image_dir = Path(opts["image_dir"])
        if opts.get("full_litres"):  # 0 means "highest calibration point"
            cfg.full_litres = float(opts["full_litres"])
        cfg.calibration = [CalPoint(float(p["litres"]), float(p["diameter_px"]))
                           for p in opts.get("calibration") or []]
        return cfg


class Publisher(Protocol):
    def publish(self, topic: str, payload: str | bytes, retain: bool = False) -> None: ...


def fetch_jpeg(url: str, timeout: float = 25, attempts: int = 3) -> np.ndarray:
    error: Exception | None = None
    for attempt in range(attempts):
        try:
            data = urllib.request.urlopen(url, timeout=timeout).read()
            image = cv2.imdecode(np.frombuffer(data, np.uint8), cv2.IMREAD_COLOR)
            if image is None:
                raise ValueError(f"not a JPEG ({len(data)} bytes)")
            return image
        except Exception as e:  # truncated transfers on weak Wi-Fi land here too
            error = e
            if attempt + 1 < attempts:
                time.sleep(2)
    raise ConnectionError(f"camera fetch failed: {error}")


def discovery_messages(cfg: ServiceConfig) -> list[tuple[str, dict]]:
    """MQTT discovery configs for every entity, as (topic, payload) pairs."""
    p = cfg.topic_prefix
    state = f"{p}/state"
    device = {"identifiers": [p], "name": cfg.device_name,
              "manufacturer": "esp32cam-water-level", "model": "ESP32-CAM float ball"}
    common = {"availability_topic": f"{p}/availability", "device": device}

    def sensor(key, name, **extra):
        return (f"{cfg.discovery_prefix}/sensor/{p}/{key}/config",
                {"name": name, "unique_id": f"{p}_{key}", "state_topic": state,
                 "value_template": f"{{{{ value_json.{key} }}}}", **common, **extra})

    return [
        sensor("litres", "Volume", unit_of_measurement="L", device_class="volume_storage",
               state_class="measurement", suggested_display_precision=1),
        sensor("percent", "Level", unit_of_measurement="%", state_class="measurement",
               icon="mdi:water-percent", suggested_display_precision=0),
        sensor("diameter_px", "Ball diameter", unit_of_measurement="px",
               state_class="measurement", entity_category="diagnostic",
               suggested_display_precision=1),
        sensor("spread_px", "Surface spread", unit_of_measurement="px",
               entity_category="diagnostic", icon="mdi:waves",
               suggested_display_precision=1),
        (f"{cfg.discovery_prefix}/binary_sensor/{p}/problem/config",
         {"name": "Detection problem", "unique_id": f"{p}_problem", "device_class": "problem",
          "state_topic": state, "value_template": "{{ 'OFF' if value_json.ok else 'ON' }}",
          "json_attributes_topic": state, "entity_category": "diagnostic", **common}),
        (f"{cfg.discovery_prefix}/camera/{p}/snapshot/config",
         {"name": "Snapshot", "unique_id": f"{p}_snapshot", "topic": f"{p}/image", **common}),
    ]


class Service:
    def __init__(self, cfg: ServiceConfig, publisher: Publisher,
                 fetch: Callable[[str], np.ndarray] = fetch_jpeg):
        self.cfg = cfg
        self.publisher = publisher
        self.fetch = fetch
        self.median = RollingMedian(cfg.median_window)
        self.calibration = None
        if len(cfg.calibration) >= 2:
            self.calibration = Calibration(cfg.calibration, full_litres=cfg.full_litres)
            log.info("calibration: model %s, V = %.2f - %.1f/d, residuals %s",
                     self.calibration.model, self.calibration.b, self.calibration.a,
                     ", ".join(f"{r:+.2f}" for r in self.calibration.residuals))
        else:
            log.warning("no calibration (need >= 2 points): publishing ball diameter only")
        # Last good values survive rejected frames, so a fogged lens or an
        # open lid does not make the level jump around.
        self.last_good: dict = {"litres": None, "percent": None, "diameter_px": None}

    def announce(self) -> None:
        for topic, payload in discovery_messages(self.cfg):
            self.publisher.publish(topic, json.dumps(payload), retain=True)
        self.publisher.publish(f"{self.cfg.topic_prefix}/availability", "online", retain=True)

    def step(self) -> dict:
        now = datetime.now(timezone.utc).isoformat(timespec="seconds")
        try:
            image = self.fetch(self.cfg.camera_url)
        except Exception as e:
            log.warning("%s", e)
            return self._publish_state(now, ok=False, reason="camera_unreachable")

        det = detect_ball(image, self.cfg.detection)
        annotated = annotate(image, det)
        self._publish_image(annotated)
        self._save_images(image, annotated, det, now)

        if not det.ok:
            log.info("frame rejected: %s", det.reason)
            return self._publish_state(now, ok=False, reason=det.reason)

        diameter = self.median.add(det.diameter_px)
        self.last_good["diameter_px"] = round(diameter, 1)
        if self.calibration:
            self.last_good["litres"] = round(self.calibration.litres(diameter), 2)
            self.last_good["percent"] = round(self.calibration.percent(diameter), 1)
        return self._publish_state(now, ok=True, reason=None, raw=det)

    def _publish_state(self, now: str, ok: bool, reason: str | None,
                       raw: Detection | None = None) -> dict:
        state = {
            **self.last_good,
            "spread_px": round(self.median.spread, 1) if len(self.median) else None,
            "raw_diameter_px": round(raw.diameter_px, 1) if raw else None,
            "ok": ok,
            "reason": reason,
            "calibrated": self.calibration is not None,
            "updated": now,
        }
        self.publisher.publish(f"{self.cfg.topic_prefix}/state", json.dumps(state), retain=True)
        return state

    def _publish_image(self, annotated: np.ndarray) -> None:
        h, w = annotated.shape[:2]
        if w > SNAPSHOT_WIDTH:
            annotated = cv2.resize(annotated, (SNAPSHOT_WIDTH, h * SNAPSHOT_WIDTH // w),
                                   interpolation=cv2.INTER_AREA)
        ok, jpeg = cv2.imencode(".jpg", annotated, [cv2.IMWRITE_JPEG_QUALITY, 80])
        if ok:
            self.publisher.publish(f"{self.cfg.topic_prefix}/image", jpeg.tobytes(), retain=True)

    def _save_images(self, image, annotated, det: Detection, now: str) -> None:
        if not self.cfg.image_dir:
            return
        d = self.cfg.image_dir
        d.mkdir(parents=True, exist_ok=True)
        cv2.imwrite(str(d / "latest.jpg"), image)
        cv2.imwrite(str(d / "latest_annotated.jpg"), annotated)
        if det.ok or not self.cfg.save_failed_images:
            return
        failed = d / "failed"
        failed.mkdir(exist_ok=True)
        cv2.imwrite(str(failed / f"{now.replace(':', '')}_{det.reason}.jpg"), image)
        for old in sorted(failed.glob("*.jpg"))[:-MAX_FAILED_IMAGES]:
            old.unlink()


def supervisor_mqtt() -> dict | None:
    """MQTT credentials of the Mosquitto add-on, when running under Supervisor."""
    token = os.environ.get("SUPERVISOR_TOKEN")
    if not token:
        return None
    req = urllib.request.Request("http://supervisor/services/mqtt",
                                 headers={"Authorization": f"Bearer {token}"})
    with urllib.request.urlopen(req, timeout=10) as resp:
        return json.load(resp)["data"]


class MqttPublisher:
    def __init__(self, cfg: ServiceConfig, on_connect: Callable[[], None]):
        import paho.mqtt.client as mqtt

        self.client = mqtt.Client(mqtt.CallbackAPIVersion.VERSION2,
                                  client_id=f"{cfg.topic_prefix}-analyzer")
        if cfg.mqtt_username:
            self.client.username_pw_set(cfg.mqtt_username, cfg.mqtt_password)
        self.client.will_set(f"{cfg.topic_prefix}/availability", "offline", retain=True)
        self.client.reconnect_delay_set(1, 60)

        def connected(client, userdata, flags, reason_code, properties):
            if reason_code.is_failure:
                log.error("MQTT connect failed: %s", reason_code)
                return
            log.info("MQTT connected to %s:%s", cfg.mqtt_host, cfg.mqtt_port)
            on_connect()  # (re)announce discovery after every reconnect

        self.client.on_connect = connected
        self._host, self._port = cfg.mqtt_host, cfg.mqtt_port

    def start(self) -> None:
        self.client.connect_async(self._host, self._port)
        self.client.loop_start()

    def publish(self, topic: str, payload: str | bytes, retain: bool = False) -> None:
        self.client.publish(topic, payload, qos=1, retain=retain)

    def close(self, topic_prefix: str) -> None:
        self.client.publish(f"{topic_prefix}/availability", "offline", qos=1, retain=True).wait_for_publish(5)
        self.client.loop_stop()
        self.client.disconnect()


def serve(cfg: ServiceConfig) -> None:
    if not cfg.mqtt_host:
        creds = supervisor_mqtt()
        if not creds:
            raise SystemExit("no MQTT broker: set mqtt_host, or run as an add-on with Mosquitto")
        cfg.mqtt_host, cfg.mqtt_port = creds["host"], int(creds["port"])
        cfg.mqtt_username, cfg.mqtt_password = creds.get("username"), creds.get("password")

    service: Service | None = None
    publisher = MqttPublisher(cfg, on_connect=lambda: service.announce())
    service = Service(cfg, publisher)
    publisher.start()  # only now, so on_connect always finds the service
    log.info("polling %s every %ss", cfg.camera_url, cfg.interval_seconds)
    # Supervisor stops add-ons with SIGTERM; exit through `finally` so
    # availability goes "offline" at once instead of after the keepalive.
    signal.signal(signal.SIGTERM, lambda *_: sys.exit(0))
    try:
        while True:
            started = time.monotonic()
            state = service.step()
            log.debug("state %s", state)
            time.sleep(max(1.0, cfg.interval_seconds - (time.monotonic() - started)))
    except KeyboardInterrupt:
        pass
    finally:
        publisher.close(cfg.topic_prefix)
