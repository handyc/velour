#include "sensors.h"

#include <Wire.h>


// ---------------------------------------------------------------------------
// Minimal JSON utilities.
//
// Parses one specific shape — either a JSON array of objects, or a
// top-level object with a "channels" array. Every field we care about
// is a primitive, so we scan for balanced `{...}` blocks and pluck
// named values out of each.
// ---------------------------------------------------------------------------

static int jsonSkipWs(const String& s, int i) {
    const int n = s.length();
    while (i < n) {
        char c = s[i];
        if (c == ' ' || c == '\t' || c == '\n' || c == '\r') { i++; continue; }
        break;
    }
    return i;
}


static int jsonEndOfString(const String& s, int start) {
    const int n = s.length();
    int i = start + 1;
    while (i < n) {
        char c = s[i];
        if (c == '\\' && i + 1 < n) { i += 2; continue; }
        if (c == '"') return i;
        i++;
    }
    return -1;
}


static int jsonEndOfValue(const String& s, int start) {
    const int n = s.length();
    int i = jsonSkipWs(s, start);
    if (i >= n) return -1;
    char c = s[i];

    if (c == '"') {
        int end = jsonEndOfString(s, i);
        return end < 0 ? -1 : end + 1;
    }
    if (c == '{' || c == '[') {
        const char close = (c == '{') ? '}' : ']';
        int depth = 1;
        i++;
        while (i < n && depth > 0) {
            char d = s[i];
            if (d == '"') {
                int end = jsonEndOfString(s, i);
                if (end < 0) return -1;
                i = end + 1;
                continue;
            }
            if (d == '{' || d == '[') depth++;
            else if (d == '}' || d == ']') {
                depth--;
                if (depth == 0 && d == close) return i + 1;
            }
            i++;
        }
        return -1;
    }

    // Primitive — number / true / false / null. Consume until delim.
    while (i < n) {
        char d = s[i];
        if (d == ',' || d == '}' || d == ']' ||
            d == ' ' || d == '\n' || d == '\r' || d == '\t') break;
        i++;
    }
    return i;
}


// Locate the value for `key` within `obj` (the body between `{` and
// `}`, NOT including the braces). Returns [start, end) byte range of
// the raw value in `obj`, or (-1, -1) if the key is absent.
static void jsonFindField(const String& obj, const char* key,
                          int& outStart, int& outEnd) {
    outStart = -1;
    outEnd = -1;
    String needle = "\"";
    needle += key;
    needle += "\"";
    int from = 0;
    while (from < (int)obj.length()) {
        int i = obj.indexOf(needle, from);
        if (i < 0) return;
        // Guard against matching mid-word (e.g. "foo_channel" when
        // searching for "channel"). The needle must be preceded either
        // by `{`, `,`, or whitespace.
        if (i > 0) {
            char prev = obj[i - 1];
            if (prev != '{' && prev != ',' && prev != ' ' && prev != '\n' &&
                prev != '\t' && prev != '\r') {
                from = i + 1;
                continue;
            }
        }
        int p = i + needle.length();
        p = jsonSkipWs(obj, p);
        if (p >= (int)obj.length() || obj[p] != ':') { from = i + 1; continue; }
        p++;
        p = jsonSkipWs(obj, p);
        int end = jsonEndOfValue(obj, p);
        if (end < 0) return;
        outStart = p;
        outEnd = end;
        return;
    }
}


static String jsonGetString(const String& obj, const char* key,
                            const char* fallback = "") {
    int a, b;
    jsonFindField(obj, key, a, b);
    if (a < 0 || obj[a] != '"') return String(fallback);
    return obj.substring(a + 1, b - 1);
}


static float jsonGetFloat(const String& obj, const char* key, float fallback) {
    int a, b;
    jsonFindField(obj, key, a, b);
    if (a < 0) return fallback;
    String piece = obj.substring(a, b);
    piece.trim();
    if (!piece.length()) return fallback;
    if (piece[0] == '"') piece = piece.substring(1, piece.length() - 1);
    if (piece == "true")  return 1.0f;
    if (piece == "false") return 0.0f;
    if (piece == "null")  return fallback;
    return piece.toFloat();
}


static int jsonGetInt(const String& obj, const char* key, int fallback) {
    return (int)jsonGetFloat(obj, key, (float)fallback);
}


static bool jsonGetBool(const String& obj, const char* key, bool fallback) {
    int a, b;
    jsonFindField(obj, key, a, b);
    if (a < 0) return fallback;
    String piece = obj.substring(a, b);
    piece.trim();
    if (piece == "true" || piece == "1")  return true;
    if (piece == "false" || piece == "0") return false;
    return fallback;
}


// Given a JSON payload that is either a top-level array or an object
// wrapping a "channels" array, return the text between the outer `[`
// and `]`. Empty string if no array is found.
static String jsonExtractChannelsArray(const String& payload) {
    int n = payload.length();
    int i = jsonSkipWs(payload, 0);
    if (i >= n) return String();

    if (payload[i] == '[') {
        int end = jsonEndOfValue(payload, i);
        if (end < 0) return String();
        return payload.substring(i + 1, end - 1);
    }
    if (payload[i] == '{') {
        int objEnd = jsonEndOfValue(payload, i);
        if (objEnd < 0) return String();
        String body = payload.substring(i + 1, objEnd - 1);
        int a, b;
        jsonFindField(body, "channels", a, b);
        if (a < 0 || body[a] != '[') return String();
        return body.substring(a + 1, b - 1);
    }
    return String();
}


// ---------------------------------------------------------------------------
// Sensor implementations.
// ---------------------------------------------------------------------------

DigitalSensor::DigitalSensor(const char* channel, int pin,
                             const char* pull, bool activeLow)
    : _pin(pin), _pull(pull ? pull : ""), _activeLow(activeLow) {
    _channel = channel;
}

bool DigitalSensor::begin() {
    if (_pull == "up")        pinMode(_pin, INPUT_PULLUP);
    else if (_pull == "down") pinMode(_pin, INPUT_PULLDOWN);
    else                      pinMode(_pin, INPUT);
    return true;
}

float DigitalSensor::sample() {
    int v = digitalRead(_pin);
    if (_activeLow) v = (v == HIGH) ? 0 : 1;
    return (float)v;
}


AnalogSensor::AnalogSensor(const char* channel, int pin,
                           float scale, float offset, int avg)
    : _pin(pin),
      _scale(scale == 0.0f ? 1.0f : scale),
      _offset(offset),
      _avg(avg < 1 ? 1 : avg) {
    _channel = channel;
}

bool AnalogSensor::begin() {
    pinMode(_pin, INPUT);
    return true;
}

float AnalogSensor::sample() {
    long sum = 0;
    for (int i = 0; i < _avg; i++) sum += analogRead(_pin);
    float raw = (float)sum / (float)_avg;
    return raw * _scale + _offset;
}


AttinyI2CSensor::AttinyI2CSensor(const char* channel, uint8_t addr,
                                 uint8_t bytes, float scale, float offset)
    : _addr(addr),
      _bytes(bytes < 1 ? 1 : (bytes > 4 ? 4 : bytes)),
      _scale(scale == 0.0f ? 1.0f : scale),
      _offset(offset) {
    _channel = channel;
}

bool AttinyI2CSensor::begin() {
    // Wire.begin() is called once in SensorRegistry::loadFromJson() on
    // the first i2c entry, so individual sensors don't double-init the
    // shared bus.
    return true;
}

float AttinyI2CSensor::sample() {
    // Big-endian: the USI slave writes hi byte first, then lo. Any
    // additional bytes tack on as further LSBs for 24- or 32-bit
    // signals (e.g. soldered sensors that want more resolution).
    Wire.requestFrom((int)_addr, (int)_bytes);
    uint32_t value = 0;
    uint8_t received = 0;
    while (Wire.available() && received < _bytes) {
        value = (value << 8) | (uint8_t)Wire.read();
        received++;
    }
    if (received == 0) return 0.0f;
    return (float)value * _scale + _offset;
}


AttinyPwmSensor::AttinyPwmSensor(const char* channel, int pin,
                                 uint32_t timeoutUs)
    : _pin(pin), _timeoutUs(timeoutUs ? timeoutUs : 50000UL) {
    _channel = channel;
}

bool AttinyPwmSensor::begin() {
    pinMode(_pin, INPUT);
    return true;
}

float AttinyPwmSensor::sample() {
    // Duty = high / (high + low). If the HIGH half times out we skip the
    // second pulseIn so one stuck line costs _timeoutUs, not 2× — with
    // many PWM sensors on a disconnected bus the difference is the
    // heartbeat missing its report window.
    uint32_t high = pulseIn(_pin, HIGH, _timeoutUs);
    if (high == 0) return 0.0f;
    uint32_t low = pulseIn(_pin, LOW, _timeoutUs);
    uint32_t period = high + low;
    if (period == 0) return 0.0f;
    return (float)high / (float)period;
}


AttinySoftUartSensor::AttinySoftUartSensor(const char* channel, int pin,
                                           uint32_t baud, int uartNum)
    : _pin(pin),
      _baud(baud == 0 ? 1200UL : baud),
      _uartNum(uartNum),
      _serial(nullptr),
      _lastValue(0.0f) {
    _channel = channel;
}

AttinySoftUartSensor::~AttinySoftUartSensor() {
    if (_serial) _serial->end();
}

bool AttinySoftUartSensor::begin() {
#if defined(ESP32)
    if (_uartNum == 2)      _serial = &Serial2;
    else                    _serial = &Serial1;  // default: UART1
    _serial->begin(_baud, SERIAL_8N1, _pin, -1);  // RX only
    return true;
#else
    _serial = nullptr;
    return false;
#endif
}

float AttinySoftUartSensor::sample() {
    if (!_serial) return _lastValue;

    // Frame format written by the '13a's softuart_tx template:
    //   0xA5, hi, lo   — a 16-bit unsigned value.
    // Only process frames whose three bytes are already buffered; a stray
    // 0xA5 mid-noise must not stall the hot path waiting for companions
    // that may never arrive (a disconnected '13a is a silent heartbeat).
    while (_serial->available() >= 3) {
        uint8_t b = (uint8_t)_serial->read();
        if (b != 0xA5) continue;
        if (_serial->available() < 2) break;
        uint8_t hi = (uint8_t)_serial->read();
        uint8_t lo = (uint8_t)_serial->read();
        uint16_t v = ((uint16_t)hi << 8) | lo;
        _lastValue = (float)v / 65535.0f;
    }
    return _lastValue;
}


// ---------------------------------------------------------------------------
// Registry.
// ---------------------------------------------------------------------------

SensorRegistry::SensorRegistry()
    : _count(0) {
    for (int i = 0; i < BODYMAP_MAX_SENSORS; i++) _sensors[i] = nullptr;
}

SensorRegistry::~SensorRegistry() {
    clear();
}

void SensorRegistry::clear() {
    for (int i = 0; i < _count; i++) {
        delete _sensors[i];
        _sensors[i] = nullptr;
    }
    _count = 0;
}

bool SensorRegistry::add(Sensor* s) {
    if (!s) return false;
    if (_count >= BODYMAP_MAX_SENSORS) return false;
    // begin() may refuse (e.g. softuart on ESP8266); keep the sensor
    // anyway so its channel still emits a legitimate default of 0.0.
    s->begin();
    _sensors[_count++] = s;
    return true;
}


static bool wireBegunOnce = false;


int SensorRegistry::loadFromJson(const String& json) {
    String body = jsonExtractChannelsArray(json);
    if (!body.length()) {
        Serial.println("[sensors] config is empty or malformed");
        return 0;
    }

    int n = body.length();
    int i = jsonSkipWs(body, 0);
    int loaded = 0;
    int softUartSlot = 1;       // 1 → Serial1, 2 → Serial2

    while (i < n && _count < BODYMAP_MAX_SENSORS) {
        int end = jsonEndOfValue(body, i);
        if (end < 0) break;

        String entry = body.substring(i, end);
        entry.trim();

        if (entry.length() < 2 || entry[0] != '{' ||
            entry[entry.length() - 1] != '}') {
            Serial.print("[sensors] skip non-object entry: ");
            Serial.println(entry);
        } else {
            String obj = entry.substring(1, entry.length() - 1);
            String channel = jsonGetString(obj, "channel");
            String kind    = jsonGetString(obj, "kind");

            if (!channel.length() || !kind.length()) {
                Serial.println("[sensors] skip entry missing channel/kind");
            } else {
                Sensor* s = nullptr;

                if (kind == "digital") {
                    int pin = jsonGetInt(obj, "pin", -1);
                    String pull = jsonGetString(obj, "pull");
                    bool activeLow = jsonGetBool(obj, "active_low", false);
                    if (pin < 0) {
                        Serial.println("[sensors] digital: missing pin");
                    } else {
                        s = new DigitalSensor(channel.c_str(), pin,
                                              pull.c_str(), activeLow);
                    }
                }
                else if (kind == "analog") {
                    int pin      = jsonGetInt(obj, "pin", -1);
                    float scale  = jsonGetFloat(obj, "scale",  1.0f);
                    float offset = jsonGetFloat(obj, "offset", 0.0f);
                    int avg      = jsonGetInt(obj, "avg", 1);
                    if (pin < 0) {
                        Serial.println("[sensors] analog: missing pin");
                    } else {
                        s = new AnalogSensor(channel.c_str(), pin,
                                             scale, offset, avg);
                    }
                }
                else if (kind == "attiny_i2c") {
                    int addr = jsonGetInt(obj, "addr", -1);
                    int bytes = jsonGetInt(obj, "bytes", 2);
                    float scale  = jsonGetFloat(obj, "scale",  1.0f);
                    float offset = jsonGetFloat(obj, "offset", 0.0f);
                    if (addr <= 0 || addr > 127) {
                        Serial.println("[sensors] attiny_i2c: addr must be 1..127");
                    } else {
                        if (!wireBegunOnce) {
                            // ESP32-S3 SuperMini defaults: SDA=8, SCL=9.
                            Wire.begin();
                            Wire.setClock(100000);
                            wireBegunOnce = true;
                        }
                        s = new AttinyI2CSensor(channel.c_str(),
                                                (uint8_t)addr, (uint8_t)bytes,
                                                scale, offset);
                    }
                }
                else if (kind == "attiny_pwm") {
                    int pin = jsonGetInt(obj, "pin", -1);
                    uint32_t timeoutUs =
                        (uint32_t)jsonGetInt(obj, "timeout_us", 50000);
                    if (pin < 0) {
                        Serial.println("[sensors] attiny_pwm: missing pin");
                    } else {
                        s = new AttinyPwmSensor(channel.c_str(), pin, timeoutUs);
                    }
                }
                else if (kind == "attiny_softuart") {
                    int pin = jsonGetInt(obj, "pin", -1);
                    uint32_t baud = (uint32_t)jsonGetInt(obj, "baud", 1200);
                    if (pin < 0) {
                        Serial.println("[sensors] attiny_softuart: missing pin");
                    } else if (softUartSlot > 2) {
                        Serial.println("[sensors] attiny_softuart: no UARTs left (cap 2)");
                    } else {
                        s = new AttinySoftUartSensor(channel.c_str(), pin,
                                                     baud, softUartSlot);
                        softUartSlot++;
                    }
                }
                else {
                    Serial.print("[sensors] unknown kind: ");
                    Serial.println(kind);
                }

                if (s) {
                    if (add(s)) {
                        loaded++;
                        Serial.print("[sensors] + ");
                        Serial.print(kind);
                        Serial.print(" → ");
                        Serial.println(channel);
                    } else {
                        Serial.println("[sensors] registry full — dropping");
                        delete s;
                    }
                }
            }
        }

        i = jsonSkipWs(body, end);
        if (i < n && body[i] == ',') i = jsonSkipWs(body, i + 1);
        else break;
    }

    return loaded;
}


void SensorRegistry::sampleAll(VelourClient& velour) {
    for (int i = 0; i < _count; i++) {
        Sensor* s = _sensors[i];
        if (!s) continue;
        velour.addReading(s->channel(), s->sample());
    }
}
