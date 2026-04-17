#include "motion_buffer.h"

void MotionBuffer::push(const GyroSample& s) {
    _buf[_head] = s;
    _head = (_head + 1) % BODYMAP_MOTION_BUFFER_SAMPLES;
    if (_count < BODYMAP_MOTION_BUFFER_SAMPLES) {
        _count++;
    }
}

size_t MotionBuffer::size() const {
    return _count;
}

size_t MotionBuffer::snapshot(GyroSample* out, size_t maxOut) const {
    // Read the volatile fields once. A concurrent push() may bump them
    // while we copy — that's fine, we'll just return the snapshot that
    // was consistent at the moment we sampled these two ints.
    const size_t head  = _head;
    const size_t count = _count;
    if (count == 0 || maxOut == 0) return 0;

    const size_t n = (count < maxOut) ? count : maxOut;

    // Oldest sample lives at (head - count) mod N. When maxOut clips us,
    // we take the NEWEST n — those are what clustering wants.
    size_t start = (head + BODYMAP_MOTION_BUFFER_SAMPLES - count) % BODYMAP_MOTION_BUFFER_SAMPLES;
    start = (start + (count - n)) % BODYMAP_MOTION_BUFFER_SAMPLES;

    for (size_t i = 0; i < n; i++) {
        out[i] = _buf[(start + i) % BODYMAP_MOTION_BUFFER_SAMPLES];
    }
    return n;
}

void MotionBuffer::clear() {
    _count = 0;
    _head  = 0;
}
