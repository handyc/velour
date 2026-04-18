// aether-visor — native renderer for the Pi headgear node.
//
// Phase 1 (this file): bring up DRM/KMS + GBM + EGL + GLES3 and push a
// solid colour to the panel at ~60 Hz. Proves the Pi hands us a
// scanout-capable framebuffer and that the toolchain is wired up.
//
// Next phases drop in:
//   net.c     — libcurl fetch of /aether/<slug>/visor.json
//   world.c   — parse manifest, build entity table
//   gltf.c    — cgltf load of referenced .glb assets
//   stereo.c  — split viewport into left/right eye cameras
//   pose.c    — UDS consumer of bodymap ESP mesh pose updates
//
// Run as: ./aether-visor            (opens /dev/dri/card0, first connector)
// Stop with SIGINT; screen will stay on whatever frame was last scanned
// out until the compositor/getty reclaims the VT.

#include <math.h>
#include <signal.h>
#include <stdio.h>
#include <time.h>

#include <GLES3/gl3.h>

#include "kms.h"

static volatile sig_atomic_t g_stop = 0;
static void on_sigint(int s) { (void)s; g_stop = 1; }

static double now_sec(void) {
    struct timespec ts;
    clock_gettime(CLOCK_MONOTONIC, &ts);
    return ts.tv_sec + ts.tv_nsec / 1e9;
}

int main(int argc, char **argv) {
    const char *card = (argc > 1) ? argv[1] : "/dev/dri/card0";
    signal(SIGINT, on_sigint);

    struct kms_display d;
    if (!kms_open(&d, card)) {
        fprintf(stderr, "aether-visor: KMS bring-up failed\n");
        return 1;
    }
    fprintf(stderr, "aether-visor: %ux%u on connector %u\n",
            d.width, d.height, d.connector_id);

    glViewport(0, 0, d.width, d.height);
    double t0 = now_sec();
    uint64_t frame = 0;

    while (!g_stop) {
        double t = now_sec() - t0;
        // Slow colour sweep — visible proof of life until we start
        // rendering real scene geometry from the manifest.
        glClearColor((float)(0.5 + 0.5 * sin(t * 0.7)),
                     (float)(0.5 + 0.5 * sin(t * 0.9 + 2.0)),
                     (float)(0.5 + 0.5 * sin(t * 1.1 + 4.0)),
                     1.0f);
        glClear(GL_COLOR_BUFFER_BIT);

        if (!kms_swap(&d)) break;

        if ((++frame % 60) == 0) {
            fprintf(stderr, "frame %llu  t=%.1fs\n",
                    (unsigned long long)frame, t);
        }
    }

    kms_close(&d);
    return 0;
}
