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
