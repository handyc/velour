// sensors — generic channel layer for bodymap nodes.
//
// The firmware image is identical on every wearable node; what a given
// node actually samples is determined at boot by a JSON config pulled
// from `/bodymap/api/config/<slug>/`. Each entry in that array becomes
// one `Sensor` object here, and the main loop walks the registry once
// per report tick, calling `addReading()` on VelourClient for each.
//
// Five kinds of sensor are supported today:
//
//   digital         — GPIO read, optional pull-up/down + active-low.
//   analog          — analogRead(), with scale+offset and simple avg.
//   attiny_i2c      — request N bytes from an ATtiny85 at a fixed 7-bit
//                     slave address via Wire (ATtiny85 = USI slave).
//   attiny_pwm      — pulseIn() on a GPIO driven by an ATtiny13a's PWM
//                     output. Returns duty cycle in [0, 1].
//   attiny_softuart — HardwareSerial RX (UART1/UART2) reading 0xA5-framed
//                     3-byte packets from a '13a that bit-bangs them out
//                     at 1200 baud (the '13a has no hardware UART). A
//                     matching '13a template (softuart_tx_13a) lives in
//                     bodymap/attiny_sources/.
//
// The parser is hand-rolled rather than pulling ArduinoJson — config
// objects are small (~10 fields per entry) and the shape is fixed, so
// a ~150-line parser saves 20KB of flash and one dependency.

#ifndef BODYMAP_SENSORS_H
#define BODYMAP_SENSORS_H

#include <Arduino.h>

#include "velour_client.h"

// Upper bound on configured channels. The report batch is capped at
// VELOUR_MAX_READINGS (16), minus the ~6 built-in host channels the
// main loop already emits — so ~10 configured channels is the practical
// ceiling before VELOUR_MAX_READINGS needs raising too.
#ifndef BODYMAP_MAX_SENSORS
#define BODYMAP_MAX_SENSORS 12
#endif


class Sensor {
public:
    virtual ~Sensor() {}
    virtual bool begin() = 0;
    virtual float sample() = 0;
    const char* channel() const { return _channel.c_str(); }

protected:
    String _channel;
};


class DigitalSensor : public Sensor {
public:
    DigitalSensor(const char* channel, int pin,
                  const char* pull, bool activeLow);
    bool  begin() override;
    float sample() override;

private:
    int    _pin;
    String _pull;       // "up", "down", or "" for none
    bool   _activeLow;
};


class AnalogSensor : public Sensor {
public:
    AnalogSensor(const char* channel, int pin,
                 float scale, float offset, int avg);
    bool  begin() override;
    float sample() override;

private:
    int   _pin;
    float _scale;
    float _offset;
    int   _avg;
};


class AttinyI2CSensor : public Sensor {
public:
    AttinyI2CSensor(const char* channel, uint8_t addr, uint8_t bytes,
                    float scale, float offset);
    bool  begin() override;
    float sample() override;

private:
    uint8_t _addr;
    uint8_t _bytes;
    float   _scale;
    float   _offset;
};


class AttinyPwmSensor : public Sensor {
public:
    AttinyPwmSensor(const char* channel, int pin, uint32_t timeoutUs);
    bool  begin() override;
    float sample() override;

private:
    int      _pin;
    uint32_t _timeoutUs;
};


class AttinySoftUartSensor : public Sensor {
public:
    // uartNum selects which ESP32 HardwareSerial to bind (1 or 2). UART0
    // is the native USB-CDC on the S3 SuperMini and is reserved for logs.
    AttinySoftUartSensor(const char* channel, int pin,
                         uint32_t baud, int uartNum);
    ~AttinySoftUartSensor();
    bool  begin() override;
    float sample() override;

private:
    int             _pin;
    uint32_t        _baud;
    int             _uartNum;
    HardwareSerial* _serial;
    float           _lastValue;
};


class SensorRegistry {
public:
    SensorRegistry();
    ~SensorRegistry();

    // Drop every existing sensor. Called before loading a fresh config
    // or when shutting down.
    void clear();

    // Take ownership of `s`, call begin(), and append to the registry.
    // Returns true if the sensor was accepted, false if the cap was
    // reached (in which case the caller MUST delete the sensor — we
    // don't silently leak).
    bool add(Sensor* s);

    // Parse `json` (either the whole server response or just the
    // channels array) and instantiate one Sensor per entry. Returns
    // the number of sensors successfully created. Per-entry errors
    // are logged to Serial but never fatal.
    int loadFromJson(const String& json);

    // Walk the registry and push one reading per sensor into the
    // VelourClient's pending batch.
    void sampleAll(VelourClient& velour);

    int count() const { return _count; }

private:
    Sensor* _sensors[BODYMAP_MAX_SENSORS];
    int     _count;
};


#endif  // BODYMAP_SENSORS_H
