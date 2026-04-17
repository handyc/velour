// GY-95T 9-axis IMU driver — scaffold only.
//
// As of bodymap 0.1.0 the one GY-95T in the user's possession is a bare
// chip awaiting soldering, so nothing here actually talks to hardware yet.
// The interface is pinned down so main.cpp and the clustering layer can
// compile against it; fill in begin()/update() once the sensor is wired.
//
// GY-95T notes collected from vendor listings (to verify on-device):
//  - UART by default, 115200 baud, 100 Hz streaming
//  - Onboard MCU does sensor fusion, so packets typically contain
//    accel + gyro + mag + fused Euler angles
//  - Exact packet framing varies by production batch — scope the TX line
//    before committing to a parser
//
// The field layout (ax/ay/az, gx/gy/gz, roll/pitch/yaw) matches what the
// motion-correlation clustering needs: raw angular velocity for the SVD
// pairing, acceleration + Euler for gravity-disambiguation.

#ifndef BODYMAP_GY95T_H
#define BODYMAP_GY95T_H

#include <Arduino.h>

class GY95T {
public:
    // Linear acceleration, m/s^2 (including gravity).
    float ax = 0, ay = 0, az = 0;

    // Angular velocity, rad/s. Primary input to the clustering math.
    float gx = 0, gy = 0, gz = 0;

    // Magnetic field, raw counts (units TBD per datasheet).
    float mx = 0, my = 0, mz = 0;

    // Fused orientation from the onboard MCU, radians.
    float roll = 0, pitch = 0, yaw = 0;

    // Wall-clock timestamp of the last successful update(), in millis().
    uint32_t lastSampleMs = 0;

    // Attach to a UART and kick off streaming. Returns true once the
    // driver confirms a valid packet header — not just "port opened".
    bool begin(HardwareSerial& serial, uint32_t baud = 115200);

    // Drain whatever bytes have arrived and decode the newest full sample.
    // Returns true iff a new sample landed since the last call. Non-blocking.
    bool update();

    // How many samples have been decoded since begin(). Useful as a
    // sanity signal for the clustering warmup ("do we have enough data
    // to start pairing nodes yet").
    uint32_t sampleCount() const { return _sampleCount; }

private:
    HardwareSerial* _serial = nullptr;
    uint32_t _sampleCount = 0;
};

#endif  // BODYMAP_GY95T_H
