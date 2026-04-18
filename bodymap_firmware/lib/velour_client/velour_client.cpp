#include "velour_client.h"


VelourClient::VelourClient(const char* baseUrl, const char* slug, const char* apiToken)
    : _baseUrl(baseUrl),
      _slug(slug ? slug : ""),
      _apiToken(apiToken ? apiToken : ""),
      _firmwareVersion(""),
      _count(0),
      _fsMounted(false) {}


VelourClient::VelourClient(const char* baseUrl)
    : _baseUrl(baseUrl),
      _slug(""),
      _apiToken(""),
      _firmwareVersion(""),
      _count(0),
      _fsMounted(false) {}


bool VelourClient::_ensureFs() {
    if (_fsMounted) return true;
    // LittleFS.begin() returns true on success. On ESP32 we pass true so
    // the FS is auto-formatted on first boot; on ESP8266 begin() takes no
    // args and auto-formats as needed.
#if defined(ESP32)
    _fsMounted = LittleFS.begin(true);
#elif defined(ESP8266)
    _fsMounted = LittleFS.begin();
#endif
    return _fsMounted;
}


bool VelourClient::loadStoredCredentials() {
    if (!_ensureFs()) return false;
    if (!LittleFS.exists(VELOUR_CREDS_PATH)) return false;
    File f = LittleFS.open(VELOUR_CREDS_PATH, "r");
    if (!f) return false;
    // Two lines: slug, then token. Trim CRLF.
    String slug = f.readStringUntil('\n');
    String token = f.readStringUntil('\n');
    f.close();
    slug.trim();
    token.trim();
    if (!slug.length() || !token.length()) return false;
    _slug = slug;
    _apiToken = token;
    return true;
}


bool VelourClient::saveCredentials() {
    if (!_ensureFs()) return false;
    if (!_slug.length() || !_apiToken.length()) return false;
    File f = LittleFS.open(VELOUR_CREDS_PATH, "w");
    if (!f) return false;
    f.println(_slug);
    f.println(_apiToken);
    f.close();
    return true;
}


bool VelourClient::clearStoredCredentials() {
    if (!_ensureFs()) return false;
    if (!LittleFS.exists(VELOUR_CREDS_PATH)) return true;
    return LittleFS.remove(VELOUR_CREDS_PATH);
}


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


String VelourClient::_effectiveBase() const {
    if (_resolvedUrl.length()) return _resolvedUrl;
    return String(_baseUrl);
}


String VelourClient::_buildUrl() const {
    // URL shape is fixed by velour's api_urls.py:
    //   <base>/api/nodes/<slug>/report/
    String url = _effectiveBase();
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
    if (!hasIdentity()) {
        // No slug/token yet — runtime-provisioned node hasn't registered
        // or loaded credentials. Drop the batch so we don't stockpile
        // unsendable readings indefinitely.
        _count = 0;
        return -1;
    }
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
    if (!hasIdentity()) {
        return VELOUR_OTA_CHECK_FAILED;
    }
    if (WiFi.status() != WL_CONNECTED) {
        return VELOUR_OTA_NO_NETWORK;
    }

    // Build the check URL: <base>/api/nodes/<slug>/firmware/check?current=<v>
    String checkUrl = _effectiveBase();
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


VelourClient::RegisterResult VelourClient::registerSelf(
    const char* provisioningSecret,
    const char* hardwareProfile,
    const char* fleet
) {
    if (WiFi.status() != WL_CONNECTED) {
        return REG_NO_NETWORK;
    }

    // Build the MAC string. WiFi.macAddress() returns "AA:BB:CC:DD:EE:FF"
    // already uppercase with colons — matches what the server expects.
    String mac = WiFi.macAddress();

    // Hand-rolled JSON so we stay dependency-free, same as _buildPayload().
    String body;
    body.reserve(256);
    body = "{\"provisioning_secret\":";
    appendEscaped(body, provisioningSecret);
    body += ",\"mac\":";
    appendEscaped(body, mac.c_str());
    body += ",\"hardware_profile\":";
    appendEscaped(body, hardwareProfile);
    if (fleet && fleet[0]) {
        body += ",\"fleet\":";
        appendEscaped(body, fleet);
    }
    if (_firmwareVersion && _firmwareVersion[0]) {
        body += ",\"firmware_version\":";
        appendEscaped(body, _firmwareVersion);
    }
    body += '}';

    String url = _effectiveBase();
    while (url.endsWith("/")) url.remove(url.length() - 1);
    url += "/api/nodes/register";

    HTTPClient http;
#if defined(ESP32)
    if (!http.begin(url)) return REG_HTTP_FAILED;
#elif defined(ESP8266)
    WiFiClient client;
    if (!http.begin(client, url)) return REG_HTTP_FAILED;
#endif
    http.addHeader("Content-Type", "application/json");
    http.setUserAgent("velour-node/1");
    http.setTimeout(10000);

    int status = http.POST(body);
    String resp = http.getString();
    http.end();

    if (status == 503) return REG_DISABLED;
    if (status >= 400 && status < 500) return REG_REJECTED;
    if (status != 200 && status != 201) return REG_HTTP_FAILED;

    String slug = jsonStringAfter(resp, "slug");
    String token = jsonStringAfter(resp, "api_token");
    if (!slug.length() || !token.length()) {
        return REG_BAD_RESPONSE;
    }

    _slug = slug;
    _apiToken = token;
    saveCredentials();  // best-effort; if flash is wedged the caller can retry
    return REG_OK;
}


bool VelourClient::fetchSensorConfig(String& out) {
    out = String();

    auto loadCached = [&]() -> bool {
        if (!_ensureFs()) return false;
        File f = LittleFS.open(VELOUR_SENSOR_CONFIG_PATH, "r");
        if (!f) return false;
        out = f.readString();
        f.close();
        return out.length() > 0;
    };

    if (!hasIdentity() || WiFi.status() != WL_CONNECTED) {
        return loadCached();
    }

    String url = _effectiveBase();
    while (url.endsWith("/")) url.remove(url.length() - 1);
    url += "/bodymap/api/config/";
    url += _slug;
    url += "/";

    HTTPClient http;
#if defined(ESP32)
    if (!http.begin(url)) return loadCached();
#elif defined(ESP8266)
    WiFiClient client;
    if (!http.begin(client, url)) return loadCached();
#endif

    String auth = "Bearer ";
    auth += _apiToken;
    http.addHeader("Authorization", auth);
    http.setUserAgent("velour-node/1");
    http.setTimeout(10000);

    int status = http.GET();
    String body = (status == 200) ? http.getString() : String();
    http.end();

    if (status != 200 || body.length() == 0) {
        return loadCached();
    }

    out = body;

    // Best-effort cache write. Skip if the on-flash copy already matches
    // byte-for-byte — otherwise every boot would rewrite the same bytes
    // and chew through flash erase cycles for no reason.
    if (_ensureFs()) {
        bool same = false;
        File r = LittleFS.open(VELOUR_SENSOR_CONFIG_PATH, "r");
        if (r) {
            if ((size_t)r.size() == (size_t)body.length()) {
                same = (r.readString() == body);
            }
            r.close();
        }
        if (!same) {
            File w = LittleFS.open(VELOUR_SENSOR_CONFIG_PATH, "w");
            if (w) {
                w.print(body);
                w.close();
            }
        }
    }
    return true;
}


// Default candidate ports — same list as smart_runserver on the server.
#ifndef VELOUR_DISCOVER_PORTS
#define VELOUR_DISCOVER_PORTS {7777, 7778, 7779, 8000, 8080, 8888}
#endif

bool VelourClient::discover() {
    if (WiFi.status() != WL_CONNECTED) return false;

    // Extract the host (IP or hostname) from _baseUrl.
    // Expected shapes: "http://192.168.1.50:7777" or "http://host:port"
    String base = String(_baseUrl);
    // Strip scheme
    int schemeEnd = base.indexOf("://");
    String hostPort = (schemeEnd >= 0) ? base.substring(schemeEnd + 3) : base;
    // Strip trailing path
    int slash = hostPort.indexOf('/');
    if (slash >= 0) hostPort = hostPort.substring(0, slash);
    // Strip existing port
    String host = hostPort;
    int colon = hostPort.lastIndexOf(':');
    if (colon > 0) host = hostPort.substring(0, colon);

    int ports[] = VELOUR_DISCOVER_PORTS;
    int nPorts = sizeof(ports) / sizeof(ports[0]);

    for (int i = 0; i < nPorts; i++) {
        String url = "http://" + host + ":" + String(ports[i]) + "/api/nodes/discover";

        HTTPClient http;
        WiFiClient client;

#if defined(ESP32)
        if (!http.begin(url)) continue;
#elif defined(ESP8266)
        if (!http.begin(client, url)) continue;
#endif
        http.setTimeout(2000);  // short timeout — we're scanning
        int status = http.GET();
        String body = (status == 200) ? http.getString() : String();
        http.end();

        if (status == 200 && body.indexOf("\"velour\":true") >= 0) {
            _resolvedUrl = "http://" + host + ":" + String(ports[i]);
            Serial.print("[velour] Discovered on port ");
            Serial.println(ports[i]);
            return true;
        }
    }

    Serial.println("[velour] Discovery failed — using default URL");
    return false;
}
