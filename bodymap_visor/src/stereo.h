// Stereo viewport math. Pure: no GL, no allocations. Given the
// stereo block from the manifest and the head pose, produces
// per-eye view + projection matrices ready to upload to the
// renderer's uniform block.
//
// Convention: column-major 4x4 matrices (the layout three.js,
// glm, and OpenGL uniformMatrix4fv all expect with transpose=GL_FALSE).

#ifndef AETHER_VISOR_STEREO_H
#define AETHER_VISOR_STEREO_H

#include <stdint.h>

struct stereo_params {
    float    ipd_m;       // interpupillary distance, metres
    float    fov_deg;     // per-eye horizontal FOV
    float    near_m;      // near clip
    float    far_m;       // far clip
    uint32_t eye_w;       // pixel width per eye
    uint32_t eye_h;       // pixel height per eye
};

// Compute the perspective projection for one eye. Same matrix for
// both eyes (left/right symmetric); only the view matrix differs.
void stereo_projection(const struct stereo_params *p,
                       float proj_out[16]);

// Compute the view matrix for one eye. `eye` is 0 (left) or 1
// (right). Head pose is centre-of-skull position (metres) +
// rotation as Euler angles in degrees (x=pitch, y=yaw, z=roll;
// applied in YXZ order, matching three.js Object3D.rotation).
//
// The eye is offset by ±ipd_m/2 along the head's local +X axis
// before the world-to-view inverse is composed.
void stereo_view(const struct stereo_params *p, int eye,
                 const float head_pos[3], const float head_rot_deg[3],
                 float view_out[16]);

// The viewport rectangle for one eye, in framebuffer pixels. The
// visor's main loop calls glViewport(x, y, w, h) with these.
void stereo_viewport(const struct stereo_params *p, int eye,
                     uint32_t fb_width, uint32_t fb_height,
                     int *out_x, int *out_y,
                     int *out_w, int *out_h);

#endif
