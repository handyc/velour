// aether-visor — native renderer for the Pi headgear node.
//
// Phase 1 (kms.c + main scaffolding): bring up DRM/KMS + GBM + EGL
// + GLES3 and push a solid colour to the panel at ~60 Hz.
//
// Phase 2 (THIS file + net.c + world.c + stereo.c + pose.c):
//   net.c     — libcurl fetch of /aether/<slug>/visor.json
//   world.c   — parse manifest into struct world_manifest
//   stereo.c  — per-eye projection + view + viewport math
//   pose.c    — UDS consumer of bodymap ESP mesh pose updates
//
// Compile:    make
// Run as:     ./aether-visor [card] [manifest-url]
// Default:    /dev/dri/card0  http://velour.local:7777/aether/cafe-1/visor.json
// Stop with SIGINT.
//
// What this main loop does today:
//   • opens the DRM panel
//   • fetches one manifest at startup
//   • parses it
//   • opens the pose UDS at /run/aether-visor/pose.sock (best-effort)
//   • per frame: reads latest pose, computes both eye matrices via
//     stereo.c, clears the framebuffer to the manifest's sky colour,
//     and stamps each eye's viewport with a distinct shade so a
//     human looking at the panel can verify left/right are wired
//     correctly. Real geometry rendering still pending — the pose
//     and matrices are computed and printed each second so the math
//     can be verified before the renderer lands.

#include <math.h>
#include <signal.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <time.h>

#include <GLES3/gl3.h>

#include "kms.h"
#include "net.h"
#include "world.h"
#include "stereo.h"
#include "pose.h"

static volatile sig_atomic_t g_stop = 0;
static void on_sigint(int s) { (void)s; g_stop = 1; }

static double now_sec(void) {
    struct timespec ts;
    clock_gettime(CLOCK_MONOTONIC, &ts);
    return ts.tv_sec + ts.tv_nsec / 1e9;
}

static void render_eye_clear(int eye, const struct world_manifest *w,
                             const float view[16], const float proj[16]) {
    // Stamp a debug shade per eye so the operator can confirm the
    // viewport split is correct. Replace with real scene geometry
    // once world.c → entity table is wired into the renderer.
    (void)view; (void)proj;
    float r = w->sky_color[0];
    float g = w->sky_color[1];
    float b = w->sky_color[2];
    if (eye == 0) { r *= 0.85f; }
    else          { b *= 0.85f; }
    glClearColor(r, g, b, 1.0f);
    glClear(GL_COLOR_BUFFER_BIT);
}

int main(int argc, char **argv) {
    const char *card = (argc > 1) ? argv[1] : "/dev/dri/card0";
    const char *url  = (argc > 2) ? argv[2]
        : "http://velour.local:7777/aether/cafe-1/visor.json?stereo=1";

    signal(SIGINT, on_sigint);

    struct kms_display d;
    if (!kms_open(&d, card)) {
        fprintf(stderr, "aether-visor: KMS bring-up failed\n");
        return 1;
    }
    fprintf(stderr, "aether-visor: %ux%u on connector %u\n",
            d.width, d.height, d.connector_id);

    net_init();
    char *json = NULL;
    size_t json_len = 0;
    if (!net_fetch(url, &json, &json_len)) {
        fprintf(stderr, "aether-visor: manifest fetch failed: %s\n", url);
        kms_close(&d);
        net_shutdown();
        return 2;
    }
    struct world_manifest world = {0};
    if (!world_parse(json, json_len, &world)) {
        fprintf(stderr, "aether-visor: manifest parse failed\n");
        free(json);
        kms_close(&d);
        net_shutdown();
        return 3;
    }
    free(json);
    fprintf(stderr, "world: %s — %zu entities, %zu portals, stereo=%d\n",
            world.world_slug ? world.world_slug : "(no slug)",
            world.n_entities, world.n_portals, world.stereo.enabled);

    pose_open("/run/aether-visor/pose.sock");

    // Start at the spawn position; head rotation defaults to facing
    // -Z (zero yaw/pitch/roll).
    struct head_pose head = {
        .pos = { world.spawn[0], world.spawn[1], world.spawn[2] },
        .rot_deg = { 0.0f, 0.0f, 0.0f },
    };

    float proj[16];
    stereo_projection(&world.stereo, proj);

    double t0 = now_sec();
    uint64_t frame = 0;

    while (!g_stop) {
        double t = now_sec() - t0;

        // Drain pose socket for the latest sample. If the source is
        // silent, reuse the previous head pose — better stale than
        // a sudden snap.
        struct head_pose latest;
        if (pose_recv_latest(&latest) > 0) head = latest;

        for (int eye = 0; eye < 2; eye++) {
            float view[16];
            stereo_view(&world.stereo, eye, head.pos, head.rot_deg, view);
            int vx, vy, vw, vh;
            stereo_viewport(&world.stereo, eye, d.width, d.height,
                            &vx, &vy, &vw, &vh);
            glViewport(vx, vy, vw, vh);
            render_eye_clear(eye, &world, view, proj);
        }

        if (!kms_swap(&d)) break;

        if ((++frame % 60) == 0) {
            fprintf(stderr,
                    "frame %llu  t=%.1fs  head=(%.2f,%.2f,%.2f) "
                    "rot=(%.1f,%.1f,%.1f)\n",
                    (unsigned long long)frame, t,
                    head.pos[0], head.pos[1], head.pos[2],
                    head.rot_deg[0], head.rot_deg[1], head.rot_deg[2]);
        }
    }

    pose_close();
    world_free(&world);
    kms_close(&d);
    net_shutdown();
    return 0;
}
