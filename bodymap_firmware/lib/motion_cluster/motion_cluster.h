// Motion-correlation clustering — v0 scaffold.
//
// Each bodymap node runs this locally. It compares its own recent gyro
// window against every peer's most-recent broadcast window, computes a
// 3x3 cross-covariance, and emits a scalar link-strength per peer:
//
//     ρ = sqrt( ‖M_AB‖_F² / (tr(M_AA) · tr(M_BB)) )
//
// where M_AB = Σ a_k b_k^T across the window. This is vector-signal
// coherence — properly bounded in [0, 1] by matrix Cauchy-Schwarz. For
// rigidly-linked limbs it sits near 1.0, for unrelated body parts it's
// small (though never zero in bodymap: all limbs share some fraction
// of the torso's global motion).
//
// What v0 does NOT do (roadmap):
//   - 3x3 SVD per pair to extract R_AB and joint-DoF rank (hinge 1,
//     universal 2, ball 3). A Jacobi SVD at 11 peers × 1 Hz is
//     cheap; we just haven't written it yet.
//   - canonical-correlation analysis proper (whitening by M_AA^-1/2 and
//     M_BB^-1/2 before the cross-cov SVD)
//   - topology solver that turns the peer-link graph into role
//     assignments (upper-arm-L, forearm-L, torso, ...)
//   - gait counter-correlation for left/right disambiguation
//   - time alignment across peer packets (currently naive: zip newest-
//     to-newest; off by up to one broadcast period, ~1 s)
//
// Enough to see a signal from the dashboard once IMUs are live, and to
// anchor the scaffold that the proper clusterer will slot into.

#ifndef BODYMAP_MOTION_CLUSTER_H
#define BODYMAP_MOTION_CLUSTER_H

#include <Arduino.h>
#include "motion_buffer.h"
#include "motion_net.h"

// Link strength above this is treated as "probably a real link" for the
// n_strong_links summary channel. Calibrated against expected signal
// once real IMU data flows — 0.7 is a placeholder.
#ifndef BODYMAP_CLUSTER_LINK_THRESHOLD
#define BODYMAP_CLUSTER_LINK_THRESHOLD 0.7f
#endif

struct PeerLink {
    uint8_t  peerMac[6];
    float    linkStrength;   // ρ in [0, 1], -1 if not-yet-computable
    uint32_t peerPacketSeq;  // seq of the peer packet this score used
    uint32_t computedMs;     // receiver-local millis() of this computation
};

class MotionCluster {
public:
    // Run one clustering pass. Uses our own MotionBuffer (newest
    // BODYMAP_NET_PACKET_SAMPLES*BODYMAP_NET_SAMPLE_STRIDE raw samples,
    // downsampled by stride) against each peer's latest packet.
    void compute(const MotionBuffer& self, const MotionNet& net);

    size_t linkCount() const { return _linkCount; }

    // Copy the link table out in insertion order.
    size_t linkSnapshot(PeerLink* out, size_t maxOut) const;

    // Strongest current link, or nullptr if no peers computed yet.
    // Handy for reporting a single top-line ρ to Velour.
    const PeerLink* strongestLink() const;

    // Count of links whose strength exceeds BODYMAP_CLUSTER_LINK_THRESHOLD.
    size_t strongLinkCount() const;

private:
    PeerLink _links[BODYMAP_MAX_PEERS];
    size_t   _linkCount = 0;
};

#endif  // BODYMAP_MOTION_CLUSTER_H
