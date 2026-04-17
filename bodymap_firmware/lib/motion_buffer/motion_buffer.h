// Sliding window of angular-velocity samples for motion-correlation
// clustering. Each bodymap node keeps its own buffer of recent ω-vectors;
// the clustering layer will (eventually) broadcast snapshots over ESP-NOW
// and compute pairwise SVDs on correlated windows to figure out which
// nodes are rigidly linked through which joint type.
//
// Lock-free single-producer / single-consumer. The IMU task pushes, a
// low-priority clustering task snapshots. snapshot() takes a stable copy
// so the consumer never races a partial overwrite.
//
// Extension points:
//   - add per-sample accel for gravity-based disambiguation of singletons
//   - add a downsampled/compressed snapshot form for ESP-NOW payloads
//     (250-byte MTU means we'll summarise, not stream raw samples)

#ifndef BODYMAP_MOTION_BUFFER_H
#define BODYMAP_MOTION_BUFFER_H

#include <Arduino.h>

// 5 seconds at 100 Hz. 16 B/sample × 500 = 8 KB. Fine on the S3's 512 KB
// SRAM; leaves room to expand to multi-channel samples later.
#ifndef BODYMAP_MOTION_BUFFER_SAMPLES
#define BODYMAP_MOTION_BUFFER_SAMPLES 500
#endif

struct GyroSample {
    uint32_t tMs;      // millis() at capture
    float    gx, gy, gz;  // angular velocity, rad/s, node-local frame
};

class MotionBuffer {
public:
    // Producer side. Overwrites the oldest sample once the buffer is full.
    void push(const GyroSample& s);

    // How many samples are currently stored (0..BODYMAP_MOTION_BUFFER_SAMPLES).
    size_t size() const;

    bool isFull() const { return size() == BODYMAP_MOTION_BUFFER_SAMPLES; }

    // Copy the newest `min(size(), maxOut)` samples into `out`, in
    // oldest-to-newest order. Returns the number of samples written.
    // Consumer side; safe to call while push() runs concurrently.
    size_t snapshot(GyroSample* out, size_t maxOut) const;

    // Reset to empty. Mostly for tests / manual re-init; not needed in
    // the steady-state control flow.
    void clear();

private:
    GyroSample _buf[BODYMAP_MOTION_BUFFER_SAMPLES];
    volatile size_t _head = 0;   // next write slot
    volatile size_t _count = 0;  // valid samples currently in buffer
};

#endif  // BODYMAP_MOTION_BUFFER_H
