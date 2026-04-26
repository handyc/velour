// Unix-domain datagram socket consumer for head poses. Drains the
// socket on each call so the visor always renders against the
// freshest sample rather than a backlog of stale ones.

#include <errno.h>
#include <fcntl.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <sys/socket.h>
#include <sys/un.h>
#include <unistd.h>

#include "pose.h"

static int g_sock = -1;

int pose_open(const char *socket_path) {
    if (g_sock >= 0) close(g_sock);
    g_sock = socket(AF_UNIX, SOCK_DGRAM, 0);
    if (g_sock < 0) {
        perror("pose: socket");
        return 0;
    }
    // Non-blocking so pose_recv_latest never stalls the render loop.
    int flags = fcntl(g_sock, F_GETFL, 0);
    fcntl(g_sock, F_SETFL, flags | O_NONBLOCK);

    struct sockaddr_un addr = {0};
    addr.sun_family = AF_UNIX;
    strncpy(addr.sun_path, socket_path, sizeof(addr.sun_path) - 1);
    // Remove any stale socket file from a prior run.
    unlink(socket_path);
    if (bind(g_sock, (struct sockaddr *)&addr, sizeof(addr)) < 0) {
        perror("pose: bind");
        close(g_sock);
        g_sock = -1;
        return 0;
    }
    return 1;
}

void pose_close(void) {
    if (g_sock >= 0) close(g_sock);
    g_sock = -1;
}

int pose_recv_latest(struct head_pose *out) {
    if (g_sock < 0) return -1;
    struct head_pose tmp;
    int got = 0;
    for (;;) {
        ssize_t n = recv(g_sock, &tmp, sizeof(tmp), 0);
        if (n == (ssize_t)sizeof(tmp)) {
            *out = tmp;
            got = 1;
            continue;  // drain — we want the latest
        }
        if (n < 0 && (errno == EAGAIN || errno == EWOULDBLOCK)) break;
        if (n < 0) {
            perror("pose: recv");
            return -1;
        }
        // Truncated packet: discard.
    }
    return got;
}
