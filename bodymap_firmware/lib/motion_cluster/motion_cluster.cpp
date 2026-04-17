#include "motion_cluster.h"

#include <math.h>
#include <string.h>

namespace {

// 3x3 matrix accumulator — column-major layout is irrelevant since we
// only ever compute Frobenius norms and sum outer products.
struct Mat3 {
    float m[3][3];
};

static inline void mat3Zero(Mat3& A) {
    for (int i = 0; i < 3; i++)
        for (int j = 0; j < 3; j++)
            A.m[i][j] = 0.0f;
}

static inline void mat3AddOuter(Mat3& A, const float a[3], const float b[3]) {
    for (int i = 0; i < 3; i++)
        for (int j = 0; j < 3; j++)
            A.m[i][j] += a[i] * b[j];
}

static inline float mat3FrobSq(const Mat3& A) {
    float s = 0.0f;
    for (int i = 0; i < 3; i++)
        for (int j = 0; j < 3; j++)
            s += A.m[i][j] * A.m[i][j];
    return s;
}

// Dequantize the peer's packed int16 gyro samples back to float rad/s.
// N is always BODYMAP_NET_PACKET_SAMPLES; callers pass the dequant
// target as a flat [N][3] buffer.
static void dequantizePeer(const MotionPacket& pkt, float out[][3]) {
    for (size_t i = 0; i < BODYMAP_NET_PACKET_SAMPLES; i++) {
        out[i][0] = pkt.gyro[i][0] * BODYMAP_NET_GYRO_SCALE;
        out[i][1] = pkt.gyro[i][1] * BODYMAP_NET_GYRO_SCALE;
        out[i][2] = pkt.gyro[i][2] * BODYMAP_NET_GYRO_SCALE;
    }
}

// Pull our own newest window, downsampled to the same rate as peer
// packets. Returns true iff we have enough samples for a full window.
static bool extractSelfWindow(const MotionBuffer& buf, float out[][3]) {
    const size_t stride = BODYMAP_NET_SAMPLE_STRIDE;
    const size_t want   = BODYMAP_NET_PACKET_SAMPLES * stride;
    if (buf.size() < want) return false;

    GyroSample raw[BODYMAP_NET_PACKET_SAMPLES * BODYMAP_NET_SAMPLE_STRIDE];
    const size_t got = buf.snapshot(raw, want);
    if (got < want) return false;

    for (size_t i = 0; i < BODYMAP_NET_PACKET_SAMPLES; i++) {
        const GyroSample& s = raw[i * stride];
        out[i][0] = s.gx;
        out[i][1] = s.gy;
        out[i][2] = s.gz;
    }
    return true;
}

// Vector-signal coherence:
//
//     ρ² = ‖M_AB‖_F² / (tr(M_AA) · tr(M_BB))
//
// Bounded in [0, 1] by the matrix Cauchy-Schwarz inequality. Intuition:
// numerator is how much (a_k ⊗ b_k) outer products align across samples,
// denominator is the total power of each signal. No mean-centering —
// angular velocity has a genuine zero and centering distorts the scale
// for near-static periods.
static float correlationCoefficient(const float a[][3], const float b[][3], size_t n) {
    float trAA = 0.0f, trBB = 0.0f;
    Mat3 MAB;
    mat3Zero(MAB);
    for (size_t k = 0; k < n; k++) {
        trAA += a[k][0]*a[k][0] + a[k][1]*a[k][1] + a[k][2]*a[k][2];
        trBB += b[k][0]*b[k][0] + b[k][1]*b[k][1] + b[k][2]*b[k][2];
        mat3AddOuter(MAB, a[k], b[k]);
    }
    const float denom = trAA * trBB + 1e-9f;
    float rhoSq = mat3FrobSq(MAB) / denom;
    if (rhoSq < 0.0f) rhoSq = 0.0f;
    if (rhoSq > 1.0f) rhoSq = 1.0f;
    return sqrtf(rhoSq);
}

}  // namespace

void MotionCluster::compute(const MotionBuffer& self, const MotionNet& net) {
    float selfWin[BODYMAP_NET_PACKET_SAMPLES][3];
    if (!extractSelfWindow(self, selfWin)) {
        // Buffer hasn't warmed up — clear any stale links and bail.
        _linkCount = 0;
        return;
    }

    PeerObservation peers[BODYMAP_MAX_PEERS];
    const size_t nPeers = net.peerSnapshot(peers, BODYMAP_MAX_PEERS);

    _linkCount = 0;
    for (size_t p = 0; p < nPeers; p++) {
        if (_linkCount >= BODYMAP_MAX_PEERS) break;
        // Peer must have broadcast a full-size window for dequant to
        // line up. Short/version-bad packets wouldn't be in the table,
        // but defence-in-depth:
        if (peers[p].latest.sampleCount != BODYMAP_NET_PACKET_SAMPLES) continue;

        float peerWin[BODYMAP_NET_PACKET_SAMPLES][3];
        dequantizePeer(peers[p].latest, peerWin);

        const float rho = correlationCoefficient(selfWin, peerWin,
                                                 BODYMAP_NET_PACKET_SAMPLES);

        PeerLink& link = _links[_linkCount++];
        memcpy(link.peerMac, peers[p].mac, 6);
        link.linkStrength   = rho;
        link.peerPacketSeq  = peers[p].latest.seq;
        link.computedMs     = millis();
    }
}

size_t MotionCluster::linkSnapshot(PeerLink* out, size_t maxOut) const {
    const size_t n = (_linkCount < maxOut) ? _linkCount : maxOut;
    for (size_t i = 0; i < n; i++) out[i] = _links[i];
    return n;
}

const PeerLink* MotionCluster::strongestLink() const {
    const PeerLink* best = nullptr;
    float bestRho = -1.0f;
    for (size_t i = 0; i < _linkCount; i++) {
        if (_links[i].linkStrength > bestRho) {
            bestRho = _links[i].linkStrength;
            best = &_links[i];
        }
    }
    return best;
}

size_t MotionCluster::strongLinkCount() const {
    size_t n = 0;
    for (size_t i = 0; i < _linkCount; i++) {
        if (_links[i].linkStrength >= BODYMAP_CLUSTER_LINK_THRESHOLD) n++;
    }
    return n;
}
