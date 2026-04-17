#include "gy95t.h"

bool GY95T::begin(HardwareSerial& serial, uint32_t baud) {
    _serial = &serial;
    // TODO: open the UART and confirm the GY-95T is responding. Left
    // commented so a bare ESP32-S3 SuperMini without the sensor attached
    // can still boot cleanly — useful for v0 network/Velour smoke tests.
    //
    // _serial->begin(baud);
    // return _serial->available() || true;  // tighten after scoping real traffic
    (void)baud;
    return true;
}

bool GY95T::update() {
    // TODO: read the framed byte stream from _serial, decode a sample
    // into the ax/ay/az, gx/gy/gz, mx/my/mz, roll/pitch/yaw fields, and
    // bump _sampleCount + lastSampleMs on success.
    //
    // Until the sensor is physically soldered this always reports "no
    // new data", which keeps main.cpp in a clean no-IMU mode.
    return false;
}
