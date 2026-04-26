// Head-pose consumer. The bodymap ESP mesh writes head position +
// orientation samples to a Unix domain socket; the visor reads
// non-blocking to get the latest pose each frame.
//
// Wire format (one struct per write, no framing required because
// SOCK_DGRAM):
//
//     struct pose_packet {
//         double t_sec;       // monotonic seconds since epoch
//         float  pos[3];      // metres, world frame
//         float  rot_deg[3];  // YXZ Euler degrees, head frame
//     };
//
// Total = 8 + 12 + 12 = 32 bytes. Datagram-oriented so the visor
// always reads the most recent complete frame, never half a sample.

#ifndef AETHER_VISOR_POSE_H
#define AETHER_VISOR_POSE_H

struct head_pose {
    double t_sec;
    float  pos[3];
    float  rot_deg[3];
};

// Open the UDS at `socket_path` (typically
// "/run/aether-visor/pose.sock"). Returns 1 on success.
int pose_open(const char *socket_path);

// Close the socket. Safe to call multiple times.
void pose_close(void);

// Drain the socket of all queued samples and write the most-recent
// one to *out. Returns 1 if at least one sample was read this
// call, 0 if the socket was empty (no fresh pose; caller should
// reuse the prior pose). Returns -1 on error.
int pose_recv_latest(struct head_pose *out);

#endif
