// Water level camera: serves flash-lit JPEG snapshots of the float ball.
//
// GET /capture.jpg[?res=UXGA&q=10&led=30&settle=500]
//   res:    QVGA | VGA | SVGA | XGA | SXGA | UXGA   (default UXGA)
//   q:      JPEG quality 4..63, lower is better     (default 10)
//   led:    flash LED duty 0..100 %                 (default 100)
//   settle: ms between LED on and capture           (default 500)
//   wb:     0 auto, 1 sunny, 2 cloudy, 3 office, 4 home (default 1)
//   aec:    -1 auto exposure, or fixed 0..1200      (default -1)
// GET /health  -> JSON status

#include <Arduino.h>
#include <ArduinoOTA.h>
#include <ESPmDNS.h>
#include <WebServer.h>
#include <WiFi.h>
#include <esp_camera.h>

#include "camera_pins.h"
#include "secrets.h"

static const char *HOSTNAME = "water-tank";

static const int LED_CHANNEL = 2;  // channel 0 / timer 0 drive the camera XCLK
static const int LED_FREQ_HZ = 5000;
static const int LED_RES_BITS = 8;

static const int DEFAULT_LED_DUTY = 100;  // ball edges go dark at 40 cm below ~60 %
static const int DEFAULT_SETTLE_MS = 500;
static const int DEFAULT_QUALITY = 10;
static const framesize_t DEFAULT_FRAMESIZE = FRAMESIZE_UXGA;
static const int STALE_FRAMES = 2;
static const int DEFAULT_WB_MODE = 1;  // sunny: closest preset to the white LED

WebServer server(80);

static uint32_t lastCaptureMs = 0;
static uint32_t lastCaptureBytes = 0;
static uint32_t captureCount = 0;
static uint32_t captureFailures = 0;

static void setLed(int percent) {
  percent = constrain(percent, 0, 100);
  ledcWrite(LED_CHANNEL, (percent * ((1 << LED_RES_BITS) - 1)) / 100);
}

static bool parseFramesize(const String &name, framesize_t &out) {
  struct { const char *name; framesize_t size; } sizes[] = {
    {"QVGA", FRAMESIZE_QVGA}, {"VGA", FRAMESIZE_VGA},   {"SVGA", FRAMESIZE_SVGA},
    {"XGA", FRAMESIZE_XGA},   {"SXGA", FRAMESIZE_SXGA}, {"UXGA", FRAMESIZE_UXGA},
  };
  for (auto &s : sizes) {
    if (name.equalsIgnoreCase(s.name)) {
      out = s.size;
      return true;
    }
  }
  return false;
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
  config.frame_size = DEFAULT_FRAMESIZE;
  config.jpeg_quality = DEFAULT_QUALITY;
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
  sensor_t *sensor = esp_camera_sensor_get();

  framesize_t size = DEFAULT_FRAMESIZE;
  if (server.hasArg("res") && !parseFramesize(server.arg("res"), size)) {
    server.send(400, "text/plain", "unknown res");
    return;
  }
  int quality = server.hasArg("q") ? constrain(server.arg("q").toInt(), 4, 63) : DEFAULT_QUALITY;
  int led = server.hasArg("led") ? server.arg("led").toInt() : DEFAULT_LED_DUTY;
  int settle = server.hasArg("settle") ? constrain(server.arg("settle").toInt(), 0, 5000) : DEFAULT_SETTLE_MS;

  if (sensor->status.framesize != size) sensor->set_framesize(sensor, size);
  if (sensor->status.quality != quality) sensor->set_quality(sensor, quality);

  // Auto white balance drifts between shots, which moves the ball's hue.
  // wb=0 auto, 1 sunny, 2 cloudy, 3 office, 4 home (presets disable drift).
  int wb = server.hasArg("wb") ? constrain(server.arg("wb").toInt(), 0, 4) : DEFAULT_WB_MODE;
  sensor->set_whitebal(sensor, 1);
  sensor->set_awb_gain(sensor, 1);
  sensor->set_wb_mode(sensor, wb);
  // aec=-1 auto exposure, otherwise a fixed exposure 0..1200.
  int aec = server.hasArg("aec") ? constrain(server.arg("aec").toInt(), -1, 1200) : -1;
  sensor->set_exposure_ctrl(sensor, aec < 0);
  if (aec >= 0) sensor->set_aec_value(sensor, aec);

  uint32_t start = millis();
  setLed(led);
  delay(settle);
  // Frames already in flight were exposed before the LED came on.
  for (int i = 0; i < STALE_FRAMES; i++) {
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
  // JPEG; push it in chunks and keep retrying until a 10 s deadline instead.
  WiFiClient client = server.client();
  size_t sent = 0;
  uint32_t deadline = millis() + 10000;
  while (sent < fb->len && client.connected() && millis() < deadline) {
    size_t n = client.write(fb->buf + sent, min<size_t>(4096, fb->len - sent));
    if (n == 0) {
      delay(10);
      continue;
    }
    sent += n;
  }
  if (sent < fb->len) {
    captureFailures++;
    Serial.printf("Capture send truncated: %u/%u bytes\n", sent, fb->len);
  }
  esp_camera_fb_return(fb);
}

static void handleHealth() {
  String json = "{";
  json += "\"uptime_s\":" + String(millis() / 1000);
  json += ",\"rssi\":" + String(WiFi.RSSI());
  json += ",\"ip\":\"" + WiFi.localIP().toString() + "\"";
  json += ",\"free_heap\":" + String(ESP.getFreeHeap());
  json += ",\"psram\":" + String(ESP.getPsramSize());
  json += ",\"free_psram\":" + String(ESP.getFreePsram());
  json += ",\"reset_reason\":" + String(esp_reset_reason());
  json += ",\"captures\":" + String(captureCount);
  json += ",\"capture_failures\":" + String(captureFailures);
  json += ",\"last_capture_ms\":" + String(lastCaptureMs);
  json += ",\"last_capture_bytes\":" + String(lastCaptureBytes);
  json += "}";
  server.send(200, "application/json", json);
}

static void connectWifi() {
  WiFi.mode(WIFI_STA);
  WiFi.setHostname(HOSTNAME);
  WiFi.setSleep(false);
  WiFi.begin(WIFI_SSID, WIFI_PASSWORD);
  Serial.printf("Connecting to %s", WIFI_SSID);
  uint32_t start = millis();
  while (WiFi.status() != WL_CONNECTED) {
    if (millis() - start > 30000) {
      Serial.println("\nWi-Fi timeout, restarting");
      ESP.restart();
    }
    delay(500);
    Serial.print(".");
  }
  Serial.printf("\nConnected, IP %s, RSSI %d\n", WiFi.localIP().toString().c_str(), WiFi.RSSI());
}

void setup() {
  Serial.begin(115200);
  Serial.printf("\nwater-tank camera, reset reason %d\n", esp_reset_reason());

  ledcSetup(LED_CHANNEL, LED_FREQ_HZ, LED_RES_BITS);
  ledcAttachPin(FLASH_LED_GPIO, LED_CHANNEL);
  setLed(0);

  if (!initCamera()) {
    delay(5000);
    ESP.restart();
  }

  connectWifi();

  if (MDNS.begin(HOSTNAME)) MDNS.addService("http", "tcp", 80);

  ArduinoOTA.setHostname(HOSTNAME);
  ArduinoOTA.setPassword(OTA_PASSWORD);
  ArduinoOTA.onStart([]() { setLed(0); });
  ArduinoOTA.begin();

  server.on("/capture.jpg", HTTP_GET, handleCapture);
  server.on("/health", HTTP_GET, handleHealth);
  server.begin();
  Serial.printf("Ready: http://%s.local/capture.jpg\n", HOSTNAME);
}

void loop() {
  if (WiFi.status() != WL_CONNECTED) {
    Serial.println("Wi-Fi lost, reconnecting");
    WiFi.reconnect();
    uint32_t start = millis();
    while (WiFi.status() != WL_CONNECTED && millis() - start < 30000) delay(500);
    if (WiFi.status() != WL_CONNECTED) ESP.restart();
  }
  ArduinoOTA.handle();
  server.handleClient();
  delay(2);
}
