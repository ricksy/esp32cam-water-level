// Water level camera: serves flash-lit JPEG snapshots of the float ball.
//
// GET  /capture.jpg[?res=UXGA&q=15&led=100&settle=500&wb=1&aec=-1]
//        Query parameters override the stored settings for this shot only.
//   res:    QVGA | VGA | SVGA | XGA | SXGA | UXGA
//   q:      JPEG quality 4..63, lower is better
//   led:    flash LED duty 0..100 %
//   settle: ms between LED on and capture, 0..5000
//   wb:     0 auto, 1 sunny, 2 cloudy, 3 office, 4 home
//   aec:    -1 auto exposure, or fixed 0..1200
// GET  /config            -> stored settings as JSON
// POST /config?q=12&...   -> change and persist settings (same keys)
// POST /config?reset=1    -> restore defaults
// GET  /health            -> JSON status
//
// res, q and wb shift the measured ball diameter slightly: don't change them
// after calibrating.

#include <Arduino.h>
#include <ArduinoOTA.h>
#include <ESPmDNS.h>
#include <Preferences.h>
#include <WebServer.h>
#include <WiFi.h>
#include <esp_camera.h>
#include <esp_task_wdt.h>

#include "camera_pins.h"
#include "secrets.h"

static const char *FIRMWARE_VERSION = "0.2.0";
static const char *HOSTNAME = "water-tank";

static const int LED_CHANNEL = 2;  // channel 0 / timer 0 drive the camera XCLK
static const int LED_FREQ_HZ = 5000;
static const int LED_RES_BITS = 8;

static const int STALE_FRAMES = 2;
static const uint32_t SEND_DEADLINE_MS = 20000;
static const uint32_t SEND_STALL_MS = 5000;
static const int WDT_TIMEOUT_S = 60;  // longer than settle + send deadline
static const uint32_t WIFI_GIVE_UP_MS = 10UL * 60 * 1000;

struct CaptureSettings {
  framesize_t size = FRAMESIZE_UXGA;
  int quality = 15;  // bench: 60 KB vs 89 KB at q=10, diameter +0.2 px
  int led = 100;     // ball edges go dark at 40 cm below ~60 %
  int settle = 500;
  int wb = 1;        // sunny: closest preset to the white LED, stable hue
  int aec = -1;
};

static const struct { const char *name; framesize_t size; } FRAMESIZES[] = {
  {"QVGA", FRAMESIZE_QVGA}, {"VGA", FRAMESIZE_VGA},   {"SVGA", FRAMESIZE_SVGA},
  {"XGA", FRAMESIZE_XGA},   {"SXGA", FRAMESIZE_SXGA}, {"UXGA", FRAMESIZE_UXGA},
};

WebServer server(80);
Preferences prefs;
static CaptureSettings stored;

static uint32_t lastCaptureMs = 0;
static uint32_t lastCaptureBytes = 0;
static uint32_t captureCount = 0;
static uint32_t captureFailures = 0;
static uint32_t wifiReconnects = 0;
static uint32_t wifiLostAt = 0;  // 0 while connected
static uint32_t wifiNextAttemptAt = 0;
static uint32_t wifiBackoffMs = 5000;

static void setLed(int percent) {
  percent = constrain(percent, 0, 100);
  ledcWrite(LED_CHANNEL, (percent * ((1 << LED_RES_BITS) - 1)) / 100);
}

static const char *framesizeName(framesize_t size) {
  for (auto &f : FRAMESIZES)
    if (f.size == size) return f.name;
  return "?";
}

static const char *resetReasonName(esp_reset_reason_t r) {
  switch (r) {
    case ESP_RST_POWERON: return "power_on";
    case ESP_RST_SW: return "software";
    case ESP_RST_PANIC: return "panic";
    case ESP_RST_INT_WDT: return "interrupt_watchdog";
    case ESP_RST_TASK_WDT: return "task_watchdog";
    case ESP_RST_WDT: return "watchdog";
    case ESP_RST_BROWNOUT: return "brownout";
    case ESP_RST_DEEPSLEEP: return "deep_sleep";
    default: return "other";
  }
}

// Applies request arguments on top of `s`. Returns an error message or nullptr.
static const char *parseSettings(CaptureSettings &s) {
  if (server.hasArg("res")) {
    bool found = false;
    for (auto &f : FRAMESIZES) {
      if (server.arg("res").equalsIgnoreCase(f.name)) {
        s.size = f.size;
        found = true;
      }
    }
    if (!found) return "unknown res";
  }
  if (server.hasArg("q")) s.quality = constrain(server.arg("q").toInt(), 4, 63);
  if (server.hasArg("led")) s.led = constrain(server.arg("led").toInt(), 0, 100);
  if (server.hasArg("settle")) s.settle = constrain(server.arg("settle").toInt(), 0, 5000);
  if (server.hasArg("wb")) s.wb = constrain(server.arg("wb").toInt(), 0, 4);
  if (server.hasArg("aec")) s.aec = constrain(server.arg("aec").toInt(), -1, 1200);
  return nullptr;
}

static String settingsJson(const CaptureSettings &s) {
  String json = "{";
  json += "\"res\":\"" + String(framesizeName(s.size)) + "\"";
  json += ",\"q\":" + String(s.quality);
  json += ",\"led\":" + String(s.led);
  json += ",\"settle\":" + String(s.settle);
  json += ",\"wb\":" + String(s.wb);
  json += ",\"aec\":" + String(s.aec);
  json += "}";
  return json;
}

static void loadSettings() {
  CaptureSettings d;
  stored.size = (framesize_t)prefs.getInt("res", d.size);
  stored.quality = prefs.getInt("q", d.quality);
  stored.led = prefs.getInt("led", d.led);
  stored.settle = prefs.getInt("settle", d.settle);
  stored.wb = prefs.getInt("wb", d.wb);
  stored.aec = prefs.getInt("aec", d.aec);
}

static void saveSettings() {
  prefs.putInt("res", stored.size);
  prefs.putInt("q", stored.quality);
  prefs.putInt("led", stored.led);
  prefs.putInt("settle", stored.settle);
  prefs.putInt("wb", stored.wb);
  prefs.putInt("aec", stored.aec);
}

static bool initCamera() {
  camera_config_t config = {};
  config.ledc_channel = LEDC_CHANNEL_0;
  config.ledc_timer = LEDC_TIMER_0;
  config.pin_d0 = Y2_GPIO_NUM;
  config.pin_d1 = Y3_GPIO_NUM;
  config.pin_d2 = Y4_GPIO_NUM;
  config.pin_d3 = Y5_GPIO_NUM;
  config.pin_d4 = Y6_GPIO_NUM;
  config.pin_d5 = Y7_GPIO_NUM;
  config.pin_d6 = Y8_GPIO_NUM;
  config.pin_d7 = Y9_GPIO_NUM;
  config.pin_xclk = XCLK_GPIO_NUM;
  config.pin_pclk = PCLK_GPIO_NUM;
  config.pin_vsync = VSYNC_GPIO_NUM;
  config.pin_href = HREF_GPIO_NUM;
  config.pin_sccb_sda = SIOD_GPIO_NUM;
  config.pin_sccb_scl = SIOC_GPIO_NUM;
  config.pin_pwdn = PWDN_GPIO_NUM;
  config.pin_reset = RESET_GPIO_NUM;
  config.xclk_freq_hz = 20000000;
  config.pixel_format = PIXFORMAT_JPEG;
  // Allocate for the largest size; smaller ones are set per capture.
  config.frame_size = FRAMESIZE_UXGA;
  config.jpeg_quality = stored.quality;
  config.fb_count = 1;
  config.fb_location = CAMERA_FB_IN_PSRAM;
  config.grab_mode = CAMERA_GRAB_WHEN_EMPTY;

  if (!psramFound()) {
    Serial.println("No PSRAM, falling back to SVGA in DRAM");
    config.frame_size = FRAMESIZE_SVGA;
    config.fb_location = CAMERA_FB_IN_DRAM;
  }

  esp_err_t err = esp_camera_init(&config);
  if (err != ESP_OK) {
    Serial.printf("Camera init failed: 0x%x\n", err);
    return false;
  }
  return true;
}

static void handleCapture() {
  CaptureSettings s = stored;
  if (const char *error = parseSettings(s)) {
    server.send(400, "text/plain", error);
    return;
  }

  sensor_t *sensor = esp_camera_sensor_get();
  bool resized = sensor->status.framesize != s.size;
  if (resized) sensor->set_framesize(sensor, s.size);
  if (sensor->status.quality != s.quality) sensor->set_quality(sensor, s.quality);
  // Auto white balance drifts between shots, which moves the ball's hue.
  sensor->set_whitebal(sensor, 1);
  sensor->set_awb_gain(sensor, 1);
  sensor->set_wb_mode(sensor, s.wb);
  sensor->set_exposure_ctrl(sensor, s.aec < 0);
  if (s.aec >= 0) sensor->set_aec_value(sensor, s.aec);

  uint32_t start = millis();
  setLed(s.led);
  delay(s.settle);
  // Frames already in flight were exposed before the LED came on.
  // A resolution switch spoils a few more frames (exposure and colour jump).
  for (int i = 0; i < STALE_FRAMES + (resized ? 3 : 0); i++) {
    camera_fb_t *stale = esp_camera_fb_get();
    if (stale) esp_camera_fb_return(stale);
  }
  camera_fb_t *fb = esp_camera_fb_get();
  setLed(0);

  if (!fb) {
    captureFailures++;
    server.send(500, "text/plain", "capture failed");
    return;
  }

  lastCaptureMs = millis() - start;
  lastCaptureBytes = fb->len;
  captureCount++;

  server.sendHeader("Content-Disposition", "inline; filename=capture.jpg");
  server.sendHeader("Cache-Control", "no-store");
  server.sendHeader("X-Capture-Ms", String(lastCaptureMs));
  server.setContentLength(fb->len);
  server.send(200, "image/jpeg", "");

  // WebServer::sendContent gives up silently on a slow link, truncating the
  // JPEG. Push it in chunks; give up only on an overall deadline or when the
  // connection makes no progress at all for a while.
  WiFiClient client = server.client();
  size_t sent = 0;
  uint32_t deadline = millis() + SEND_DEADLINE_MS;
  uint32_t lastProgress = millis();
  while (sent < fb->len && client.connected() && millis() < deadline
         && millis() - lastProgress < SEND_STALL_MS) {
    size_t n = client.write(fb->buf + sent, min<size_t>(4096, fb->len - sent));
    if (n == 0) {
      delay(10);
      continue;
    }
    sent += n;
    lastProgress = millis();
  }
  if (sent < fb->len) {
    captureFailures++;
    Serial.printf("Capture send truncated: %u/%u bytes\n", sent, fb->len);
  }
  esp_camera_fb_return(fb);
}

static void handleConfig() {
  if (server.method() == HTTP_POST) {
    if (server.hasArg("reset")) {
      stored = CaptureSettings();
    } else {
      CaptureSettings s = stored;
      if (const char *error = parseSettings(s)) {
        server.send(400, "text/plain", error);
        return;
      }
      stored = s;
    }
    saveSettings();
  }
  server.send(200, "application/json", settingsJson(stored));
}

static void handleHealth() {
  String json = "{";
  json += "\"version\":\"" + String(FIRMWARE_VERSION) + "\"";
  json += ",\"uptime_s\":" + String(millis() / 1000);
  json += ",\"rssi\":" + String(WiFi.RSSI());
  json += ",\"ip\":\"" + WiFi.localIP().toString() + "\"";
  json += ",\"wifi_reconnects\":" + String(wifiReconnects);
  json += ",\"free_heap\":" + String(ESP.getFreeHeap());
  json += ",\"psram\":" + String(ESP.getPsramSize());
  json += ",\"free_psram\":" + String(ESP.getFreePsram());
  json += ",\"reset_reason\":\"" + String(resetReasonName(esp_reset_reason())) + "\"";
  json += ",\"captures\":" + String(captureCount);
  json += ",\"capture_failures\":" + String(captureFailures);
  json += ",\"last_capture_ms\":" + String(lastCaptureMs);
  json += ",\"last_capture_bytes\":" + String(lastCaptureBytes);
  json += ",\"settings\":" + settingsJson(stored);
  json += "}";
  server.send(200, "application/json", json);
}

static void connectWifi() {
  WiFi.mode(WIFI_STA);
  WiFi.setHostname(HOSTNAME);
  WiFi.setSleep(false);
  WiFi.setAutoReconnect(true);
  WiFi.begin(WIFI_SSID, WIFI_PASSWORD);
  Serial.printf("Connecting to %s", WIFI_SSID);
  uint32_t start = millis();
  while (WiFi.status() != WL_CONNECTED) {
    if (millis() - start > 30000) {
      Serial.println("\nWi-Fi timeout, restarting");
      ESP.restart();
    }
    delay(500);
    esp_task_wdt_reset();
    Serial.print(".");
  }
  Serial.printf("\nConnected, IP %s, RSSI %d\n", WiFi.localIP().toString().c_str(), WiFi.RSSI());
}

// Non-blocking: OTA and the watchdog keep running while Wi-Fi is down. Retries
// back off from 5 s to 60 s; a reboot is the last resort after 10 minutes.
static void maintainWifi() {
  uint32_t now = millis();
  if (WiFi.status() == WL_CONNECTED) {
    if (wifiLostAt) {
      Serial.printf("Wi-Fi back after %lu s, RSSI %d\n", (now - wifiLostAt) / 1000, WiFi.RSSI());
      wifiReconnects++;
      wifiLostAt = 0;
      wifiBackoffMs = 5000;
    }
    return;
  }
  if (!wifiLostAt) {
    Serial.println("Wi-Fi lost");
    wifiLostAt = now;
    wifiNextAttemptAt = now + wifiBackoffMs;
  }
  if (now - wifiLostAt > WIFI_GIVE_UP_MS) {
    Serial.println("Wi-Fi down for 10 min, restarting");
    ESP.restart();
  }
  if ((int32_t)(now - wifiNextAttemptAt) >= 0) {
    Serial.println("Wi-Fi reconnect attempt");
    WiFi.disconnect();
    WiFi.begin(WIFI_SSID, WIFI_PASSWORD);
    wifiBackoffMs = min<uint32_t>(wifiBackoffMs * 2, 60000);
    wifiNextAttemptAt = now + wifiBackoffMs;
  }
}

void setup() {
  Serial.begin(115200);
  Serial.printf("\nwater-tank camera %s, reset reason %s\n", FIRMWARE_VERSION,
                resetReasonName(esp_reset_reason()));

  // Reboot if the loop ever hangs (camera driver, network stack).
  esp_task_wdt_init(WDT_TIMEOUT_S, true);
  esp_task_wdt_add(NULL);

  ledcSetup(LED_CHANNEL, LED_FREQ_HZ, LED_RES_BITS);
  ledcAttachPin(FLASH_LED_GPIO, LED_CHANNEL);
  setLed(0);

  prefs.begin("camera", false);
  loadSettings();

  if (!initCamera()) {
    delay(5000);
    ESP.restart();
  }

  connectWifi();

  if (MDNS.begin(HOSTNAME)) MDNS.addService("http", "tcp", 80);

  ArduinoOTA.setHostname(HOSTNAME);
  ArduinoOTA.setPassword(OTA_PASSWORD);
  ArduinoOTA.onStart([]() {
    setLed(0);
    esp_task_wdt_delete(NULL);  // flashing can outlast the watchdog
  });
  ArduinoOTA.begin();

  server.on("/capture.jpg", HTTP_GET, handleCapture);
  server.on("/config", HTTP_ANY, handleConfig);
  server.on("/health", HTTP_GET, handleHealth);
  server.begin();
  Serial.printf("Ready: http://%s.local/capture.jpg\n", HOSTNAME);
}

void loop() {
  esp_task_wdt_reset();
  maintainWifi();
  ArduinoOTA.handle();
  server.handleClient();
  delay(2);
}
