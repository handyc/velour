#include "velour_client.h"


VelourClient::VelourClient(const char* baseUrl, const char* slug, const char* apiToken)
    : _baseUrl(baseUrl),
      _slug(slug),
      _apiToken(apiToken),
      _firmwareVersion(""),
      _count(0) {}


bool VelourClient::addReading(const char* channel, float value) {
    if (_count >= VELOUR_MAX_READINGS) return false;
    _readings[_count].channel = channel;
    _readings[_count].value = value;
    _count++;
    return true;
}


void VelourClient::setFirmwareVersion(const char* version) {
    _firmwareVersion = version ? version : "";
}


String VelourClient::_buildUrl() const {
    // URL shape is fixed by velour's api_urls.py:
    //   <base>/api/nodes/<slug>/report/
    String url = _baseUrl;
    while (url.endsWith("/")) url.remove(url.length() - 1);
    url += "/api/nodes/";
    url += _slug;
    url += "/report/";
    return url;
}


// Hand-rolled JSON serializer to keep this file dependency-free (no
// ArduinoJson, etc.). The payload shape is small and fixed, so escaping
// logic is minimal — we only guard against embedded quotes in channel
// names, which shouldn't occur in practice but we handle defensively.
static void appendEscaped(String& out, const char* s) {
    out += '"';
    if (s) {
        for (const char* p = s; *p; p++) {
            char c = *p;
            if (c == '"' || c == '\\') { out += '\\'; out += c; }
            else if (c == '\n') { out += "\\n"; }
            else if (c == '\r') { out += "\\r"; }
            else if (c == '\t') { out += "\\t"; }
            else if ((unsigned char)c < 0x20) { /* skip */ }
            else { out += c; }
        }
    }
    out += '"';
}


String VelourClient::_buildPayload() const {
    String s;
    s.reserve(128 + _count * 48);
    s = "{\"readings\":[";
    for (int i = 0; i < _count; i++) {
        if (i > 0) s += ',';
        s += "{\"channel\":";
        appendEscaped(s, _readings[i].channel);
        s += ",\"value\":";
        s += String(_readings[i].value, 4);
        s += '}';
    }
    s += ']';

    if (_firmwareVersion && _firmwareVersion[0]) {
        s += ",\"firmware_version\":";
        appendEscaped(s, _firmwareVersion);
    }
    // Standard host-health metadata included on every report. These end up
    // in SensorReading.raw_json on the server alongside each stored row.
    s += ",\"free_heap\":";
    s += String(ESP.getFreeHeap());
    s += ",\"uptime_ms\":";
    s += String(millis());
    if (WiFi.status() == WL_CONNECTED) {
        s += ",\"rssi\":";
        s += String(WiFi.RSSI());
    }
    s += '}';
    return s;
}


int VelourClient::report() {
    if (WiFi.status() != WL_CONNECTED) {
        // No network — drop the batch so we don't leak memory forever.
        _count = 0;
        return -1;
    }

    HTTPClient http;
    String url = _buildUrl();

#if defined(ESP32)
    if (!http.begin(url)) {
        _count = 0;
        return -1;
    }
#elif defined(ESP8266)
    WiFiClient client;
    if (!http.begin(client, url)) {
        _count = 0;
        return -1;
    }
#endif

    String auth = "Bearer ";
    auth += _apiToken;
    http.addHeader("Authorization", auth);
    http.addHeader("Content-Type", "application/json");
    http.setUserAgent("velour-node/1");
    http.setTimeout(10000);  // 10s — enough for most servers, fail fast otherwise

    String payload = _buildPayload();
    int status = http.POST(payload);
    http.end();

    // Clear the batch whether or not send succeeded. Alternative would be
    // keep-on-failure for retry, but that can grow unbounded when the
    // network is down for a long time and blow the heap on a microcontroller.
    _count = 0;
    return status;
}


// Tiny "find the value after this key" helper for the OTA check response.
// The JSON is small and well-known (server-emitted, not attacker-controlled),
// so we don't need a real parser. We locate `"key"` then skip a colon and
// optional whitespace, so both compact JSON (`"key":true`) and pretty-
// printed JSON (`"key": true`) are accepted.
static int jsonFindValueStart(const String& body, const char* key) {
    String needle = "\"";
    needle += key;
    needle += "\"";
    int i = body.indexOf(needle);
    if (i < 0) return -1;
    int p = i + needle.length();
    // Skip whitespace, colon, whitespace.
    while (p < (int)body.length() && (body[p] == ' ' || body[p] == '\t')) p++;
    if (p >= (int)body.length() || body[p] != ':') return -1;
    p++;
    while (p < (int)body.length() && (body[p] == ' ' || body[p] == '\t')) p++;
    return p;
}

static String jsonStringAfter(const String& body, const char* key) {
    int p = jsonFindValueStart(body, key);
    if (p < 0 || p >= (int)body.length() || body[p] != '"') return String();
    int start = p + 1;
    int end = body.indexOf('"', start);
    if (end < 0) return String();
    return body.substring(start, end);
}

static bool jsonHasTrue(const String& body, const char* key) {
    int p = jsonFindValueStart(body, key);
    if (p < 0) return false;
    return body.substring(p, p + 4) == "true";
}


VelourClient::OtaResult VelourClient::checkForUpdate() {
    if (WiFi.status() != WL_CONNECTED) {
        return VELOUR_OTA_NO_NETWORK;
    }

    // Build the check URL: <base>/api/nodes/<slug>/firmware/check?current=<v>
    String checkUrl = _baseUrl;
    while (checkUrl.endsWith("/")) checkUrl.remove(checkUrl.length() - 1);
    checkUrl += "/api/nodes/";
    checkUrl += _slug;
    checkUrl += "/firmware/check";
    if (_firmwareVersion && _firmwareVersion[0]) {
        checkUrl += "?current=";
        checkUrl += _firmwareVersion;
    }

    HTTPClient http;
    WiFiClient client;

#if defined(ESP32)
    if (!http.begin(checkUrl)) {
        return VELOUR_OTA_CHECK_FAILED;
    }
#elif defined(ESP8266)
    if (!http.begin(client, checkUrl)) {
        return VELOUR_OTA_CHECK_FAILED;
    }
#endif

    String auth = "Bearer ";
    auth += _apiToken;
    http.addHeader("Authorization", auth);
    http.setUserAgent("velour-node/1");
    http.setTimeout(10000);

    int status = http.GET();
    String body = (status == 200) ? http.getString() : String();
    http.end();

    if (status != 200) {
        return VELOUR_OTA_CHECK_FAILED;
    }

    if (jsonHasTrue(body, "no_firmware")) {
        return VELOUR_OTA_NO_FIRMWARE;
    }
    if (jsonHasTrue(body, "up_to_date")) {
        return VELOUR_OTA_UP_TO_DATE;
    }
    if (!jsonHasTrue(body, "update")) {
        // Unexpected shape — treat as check failed so the operator sees a
        // retry next interval rather than silently doing nothing.
        return VELOUR_OTA_CHECK_FAILED;
    }

    String binUrl = jsonStringAfter(body, "url");
    if (binUrl.length() == 0) {
        return VELOUR_OTA_CHECK_FAILED;
    }

    // The OTA library downloads to a temporary flash slot, verifies the
    // ESP magic byte, then atomically swaps and reboots. We need to pass
    // the Authorization header because the bin endpoint is also bearer-
    // gated. Both ESP8266HTTPUpdate and HTTPUpdate support this via
    // setAuthorization() (ESP32) / addHeader-equivalent on ESP8266.

#if defined(ESP32)
    httpUpdate.setLedPin(LED_BUILTIN, LOW);
    httpUpdate.rebootOnUpdate(true);
    t_httpUpdate_return ret = httpUpdate.update(client, binUrl, _firmwareVersion);
    if (ret == HTTP_UPDATE_OK) {
        // unreachable — ESP has rebooted by now
        return VELOUR_OTA_UP_TO_DATE;
    }
    return VELOUR_OTA_UPDATE_FAILED;
#elif defined(ESP8266)
    ESPhttpUpdate.setLedPin(LED_BUILTIN, LOW);
    ESPhttpUpdate.rebootOnUpdate(true);
    // Pass the Authorization header along for the bin download. The
    // ESP8266httpUpdate API takes a WiFiClient, a URL, and an optional
    // "current version" string used for its own If-Match header. We use
    // our own version check instead, so we just pass an empty string.
    ESPhttpUpdate.setAuthorization(String("Bearer ") + _apiToken);
    t_httpUpdate_return ret = ESPhttpUpdate.update(client, binUrl, "");
    if (ret == HTTP_UPDATE_OK) {
        // unreachable — ESP has rebooted by now
        return VELOUR_OTA_UP_TO_DATE;
    }
    return VELOUR_OTA_UPDATE_FAILED;
#endif
}
