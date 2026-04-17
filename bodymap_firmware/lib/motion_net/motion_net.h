// ESP-NOW broadcast layer for bodymap.
//
// Every node broadcasts a downsampled window of its own recent angular
// velocity once per second. Every node also listens to every other
// node's broadcasts and keeps the latest packet per sender MAC. The
// clustering layer reads the peer table (our local MotionBuffer + the
// peer observations) to compute pairwise SVDs and decide who's rigidly
// linked to whom.
//
// Wire format (packed, little-endian on ESP32):
//
//     [2B magic] [1B version] [1B sampleCount]
//     [4B t0Ms]  [2B dtMs]    [4B seq]
//     [6B * N] int16 gyro[N][3] — each value scaled by GYRO_SCALE rad/s
//
// With N=30 and stride=10 against a 100 Hz sampler, each packet covers
// a 3-second window, 194 bytes on the wire — comfortably inside the
// ~250 B ESP-NOW MTU and leaves room for accel/mag later.
//
// Timing note: senders stamp t0Ms from their own millis(). Nodes boot at
// different times so these timestamps aren't comparable across the mesh.
// The clustering layer handles alignment — receiver uses its own arrival
// time + the packet's dtMs to build a local time base per peer.

#ifndef BODYMAP_MOTION_NET_H
#define BODYMAP_MOTION_NET_H

#include <Arduino.h>
#include "motion_buffer.h"

#ifndef BODYMAP_NET_PACKET_SAMPLES
#define BODYMAP_NET_PACKET_SAMPLES 30
#endif

#ifndef BODYMAP_NET_SAMPLE_STRIDE
// Broadcast every Nth sample from the MotionBuffer. 10 = 100 Hz → 10 Hz
// effective rate, which is plenty for clustering (joint motions live
// well under 5 Hz).
#define BODYMAP_NET_SAMPLE_STRIDE 10
#endif

#ifndef BODYMAP_MAX_PEERS
// One entry per bodymap node we might hear from. 16 leaves headroom
// over the planned 10–11 segment nodes.
#define BODYMAP_MAX_PEERS 16
#endif

// Scale factor for int16 gyro values. 0.001 rad/s per LSB gives a range
// of ±32.7 rad/s — well beyond typical human joint rates (~10 rad/s peak).
static constexpr float BODYMAP_NET_GYRO_SCALE = 0.001f;

static constexpr uint8_t BODYMAP_NET_MAGIC0   = 0xBD;
static constexpr uint8_t BODYMAP_NET_MAGIC1   = 0x5A;
static constexpr uint8_t BODYMAP_NET_VERSION  = 1;

struct __attribute__((packed)) MotionPacket {
    uint8_t  magic0;
    uint8_t  magic1;
    uint8_t  version;
    uint8_t  sampleCount;
    uint32_t t0Ms;
    uint16_t dtMs;
    uint32_t seq;
    int16_t  gyro[BODYMAP_NET_PACKET_SAMPLES][3];
};

struct PeerObservation {
    uint8_t      mac[6];
    MotionPacket latest;
    uint32_t     lastReceivedMs;  // receiver-local millis() when packet landed
    uint32_t     packetsReceived;
};

class MotionNet {
public:
    // Init ESP-NOW, register the broadcast peer (FF:FF:FF:FF:FF:FF) on the
    // current WiFi channel, and hook the receive callback. Must be called
    // AFTER WiFi.begin() has connected — ESP-NOW shares the radio and
    // needs the channel locked in.
    bool begin();

    // Downsample the newest window from `src` and broadcast it. No-op if
    // the buffer doesn't yet hold enough samples for one full packet.
    // Returns false on send error.
    bool broadcast(const MotionBuffer& src);

    // Number of distinct peers we've heard from this session.
    size_t peerCount() const { return _peerCount; }

    // Counters for the Velour heartbeat.
    uint32_t packetsSent()     const { return _pktsTx; }
    uint32_t packetsReceived() const { return _pktsRx; }
    uint32_t sendErrors()      const { return _sendErrors; }

    // Copy the peer table into caller-provided storage. Clustering layer
    // calls this to get a stable view across all peers at once.
    size_t peerSnapshot(PeerObservation* out, size_t maxOut) const;

private:
    // ESP-NOW's C-style receive callback lands here via a trampoline.
    void _onReceive(const uint8_t* mac, const uint8_t* data, int len);

    PeerObservation _peers[BODYMAP_MAX_PEERS];
    size_t _peerCount = 0;

    uint32_t _seq       = 0;
    uint32_t _pktsTx    = 0;
    uint32_t _pktsRx    = 0;
    uint32_t _sendErrors = 0;
};

#endif  // BODYMAP_MOTION_NET_H
