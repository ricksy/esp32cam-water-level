import json
from pathlib import Path

import cv2
import numpy as np
import pytest

from water_level.service import Service, ServiceConfig, discovery_messages

SAMPLES = Path(__file__).resolve().parents[2] / "samples"


class FakePublisher:
    def __init__(self):
        self.messages: dict[str, tuple[str | bytes, bool]] = {}

    def publish(self, topic, payload, retain=False):
        self.messages[topic] = (payload, retain)

    def state(self) -> dict:
        return json.loads(self.messages["water_tank/state"][0])


def camera(*names):
    """Fake fetch that returns the given samples in turn (None = unreachable)."""
    frames = iter(names)

    def fetch(url):
        name = next(frames)
        if name is None:
            raise ConnectionError("camera fetch failed: timed out")
        return cv2.imread(str(SAMPLES / name))
    return fetch


OPTIONS = {
    "camera_url": "http://cam/capture.jpg",
    "calibration": [{"litres": 0, "diameter_px": 143.9}, {"litres": 30, "diameter_px": 325.0}],
}


def make(*frames, options=OPTIONS, **cfg_overrides):
    cfg = ServiceConfig.from_options(options)
    for k, v in cfg_overrides.items():
        setattr(cfg, k, v)
    pub = FakePublisher()
    return Service(cfg, pub, fetch=camera(*frames)), pub


def test_good_frame_publishes_level():
    svc, pub = make("dark_34cm_a.jpg")
    state = svc.step()
    assert state["ok"] and state["reason"] is None
    assert state["diameter_px"] == pytest.approx(180.1, abs=0.2)
    assert 0 < state["litres"] < 30
    assert state["percent"] == pytest.approx(100 * state["litres"] / 30, abs=0.1)
    assert pub.state() == state
    image, retain = pub.messages["water_tank/image"]
    assert retain and cv2.imdecode(np.frombuffer(image, np.uint8), cv2.IMREAD_COLOR).shape[1] == 800


def test_rejected_frame_keeps_last_good_level():
    svc, pub = make("dark_34cm_a.jpg", "no_ball_desk.jpg")
    good = svc.step()
    bad = svc.step()
    assert not bad["ok"] and bad["reason"] == "no_ball"
    assert bad["litres"] == good["litres"]
    assert bad["raw_diameter_px"] is None


def test_unreachable_camera_is_a_problem_not_a_crash():
    svc, pub = make(None)
    state = svc.step()
    assert not state["ok"] and state["reason"] == "camera_unreachable"
    assert state["litres"] is None
    assert "water_tank/image" not in pub.messages


def test_median_smooths_an_outlier_frame():
    svc, _ = make("dark_34cm_a.jpg", "dark_34cm_b.jpg", "dark_near.jpg")
    svc.step()
    svc.step()
    state = svc.step()  # one near frame among two 34 cm frames
    assert state["diameter_px"] == pytest.approx(180.0, abs=0.2)
    assert state["spread_px"] > 200


def test_without_calibration_only_diameter_is_published():
    svc, _ = make("dark_34cm_a.jpg", options={"camera_url": "http://cam"})
    state = svc.step()
    assert state["ok"] and not state["calibrated"]
    assert state["litres"] is None and state["percent"] is None
    assert state["diameter_px"] == pytest.approx(180.1, abs=0.2)


def test_failed_frames_are_saved_and_pruned(tmp_path, monkeypatch):
    monkeypatch.setattr("water_level.service.MAX_FAILED_IMAGES", 2)
    svc, _ = make(*["no_ball_desk.jpg"] * 4, image_dir=tmp_path)
    for _ in range(4):
        svc.step()
    assert (tmp_path / "latest.jpg").exists() and (tmp_path / "latest_annotated.jpg").exists()
    assert len(list((tmp_path / "failed").glob("*no_ball.jpg"))) <= 2


def test_announce_publishes_retained_discovery_and_online():
    svc, pub = make()
    svc.announce()
    assert pub.messages["water_tank/availability"] == ("online", True)
    volume = json.loads(pub.messages["homeassistant/sensor/water_tank/litres/config"][0])
    assert volume["device_class"] == "volume_storage" and volume["unit_of_measurement"] == "L"


def test_discovery_ids_are_unique_and_share_one_device():
    msgs = discovery_messages(ServiceConfig(camera_url="x"))
    ids = [p["unique_id"] for _, p in msgs]
    assert len(ids) == len(set(ids)) == 6
    assert {json.dumps(p["device"]) for _, p in msgs} == {json.dumps(msgs[0][1]["device"])}


def test_options_parsing():
    cfg = ServiceConfig.from_options({
        "camera_url": "http://cam", "interval_seconds": 30, "roi": "10, 20, 300, 400",
        "val_min": 30, "full_litres": 0, "mqtt_host": "", "topic_prefix": "tank2",
    })
    assert cfg.interval_seconds == 30
    assert cfg.detection.roi == (10, 20, 300, 400)
    assert cfg.detection.val_min == 30 and cfg.detection.hue_min == 3
    assert cfg.full_litres is None  # 0 = use the highest calibration point
    assert cfg.mqtt_host is None and cfg.topic_prefix == "tank2"


def test_bad_roi_is_rejected():
    with pytest.raises(ValueError):
        ServiceConfig.from_options({"camera_url": "x", "roi": "1,2,3"})
