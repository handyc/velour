// Stereo math. Standard pinhole projection + per-eye horizontal
// translation by IPD/2. Matrices are column-major (i.e.
// proj[col*4 + row]) so they upload directly to glUniformMatrix4fv
// with transpose=GL_FALSE.

#include <math.h>
#include <string.h>

#include "stereo.h"

#define DEG (3.14159265358979323846f / 180.0f)

static void mat4_identity(float m[16]) {
    memset(m, 0, sizeof(float) * 16);
    m[0] = m[5] = m[10] = m[15] = 1.0f;
}

static void mat4_mul(const float a[16], const float b[16], float out[16]) {
    float tmp[16];
    for (int col = 0; col < 4; col++) {
        for (int row = 0; row < 4; row++) {
            float s = 0;
            for (int k = 0; k < 4; k++) {
                s += a[k * 4 + row] * b[col * 4 + k];
            }
            tmp[col * 4 + row] = s;
        }
    }
    memcpy(out, tmp, sizeof(tmp));
}

void stereo_projection(const struct stereo_params *p, float out[16]) {
    float aspect = (p->eye_h > 0)
        ? (float)p->eye_w / (float)p->eye_h
        : 1.0f;
    float fov_h_rad = p->fov_deg * DEG;
    // Convert horizontal FOV → vertical FOV through aspect, then
    // build the standard glFrustum-equivalent.
    float fov_v_rad = 2.0f * atanf(tanf(fov_h_rad * 0.5f) / aspect);
    float f = 1.0f / tanf(fov_v_rad * 0.5f);
    float nf = 1.0f / (p->near_m - p->far_m);

    memset(out, 0, sizeof(float) * 16);
    out[0]  = f / aspect;
    out[5]  = f;
    out[10] = (p->far_m + p->near_m) * nf;
    out[11] = -1.0f;
    out[14] = (2.0f * p->far_m * p->near_m) * nf;
}

// Build a YXZ rotation matrix from Euler degrees, then translate.
// Same convention as three.js Object3D with rotation order YXZ.
static void head_to_world(const float pos[3], const float rot_deg[3],
                          float out[16]) {
    float rx = rot_deg[0] * DEG;
    float ry = rot_deg[1] * DEG;
    float rz = rot_deg[2] * DEG;

    float cy = cosf(ry), sy = sinf(ry);
    float cx = cosf(rx), sx = sinf(rx);
    float cz = cosf(rz), sz = sinf(rz);

    // Y rotation
    float Ry[16] = {
         cy, 0, -sy, 0,
          0, 1,   0, 0,
         sy, 0,  cy, 0,
          0, 0,   0, 1
    };
    // X rotation
    float Rx[16] = {
         1,   0,  0, 0,
         0,  cx, sx, 0,
         0, -sx, cx, 0,
         0,   0,  0, 1
    };
    // Z rotation
    float Rz[16] = {
         cz, sz, 0, 0,
        -sz, cz, 0, 0,
          0,  0, 1, 0,
          0,  0, 0, 1
    };
    float YX[16];
    mat4_mul(Ry, Rx, YX);
    mat4_mul(YX, Rz, out);
    out[12] = pos[0];
    out[13] = pos[1];
    out[14] = pos[2];
}

// Invert an affine matrix where the upper-left 3x3 is a rotation
// (transpose) and the translation is rotated by the transposed
// rotation and negated.
static void affine_invert(const float m[16], float out[16]) {
    out[0]  = m[0]; out[1]  = m[4]; out[2]  = m[8];  out[3]  = 0;
    out[4]  = m[1]; out[5]  = m[5]; out[6]  = m[9];  out[7]  = 0;
    out[8]  = m[2]; out[9]  = m[6]; out[10] = m[10]; out[11] = 0;
    out[12] = -(m[0] * m[12] + m[1] * m[13] + m[2]  * m[14]);
    out[13] = -(m[4] * m[12] + m[5] * m[13] + m[6]  * m[14]);
    out[14] = -(m[8] * m[12] + m[9] * m[13] + m[10] * m[14]);
    out[15] = 1.0f;
}

void stereo_view(const struct stereo_params *p, int eye,
                 const float head_pos[3], const float head_rot_deg[3],
                 float out[16]) {
    float head_world[16];
    head_to_world(head_pos, head_rot_deg, head_world);

    // Eye offset along head local +X. Eye 0 = left (-IPD/2),
    // eye 1 = right (+IPD/2).
    float eye_offset = (eye == 0 ? -1.0f : +1.0f) * p->ipd_m * 0.5f;
    float eye_local[16];
    mat4_identity(eye_local);
    eye_local[12] = eye_offset;

    float eye_world[16];
    mat4_mul(head_world, eye_local, eye_world);
    affine_invert(eye_world, out);
}

void stereo_viewport(const struct stereo_params *p, int eye,
                     uint32_t fb_width, uint32_t fb_height,
                     int *out_x, int *out_y,
                     int *out_w, int *out_h) {
    (void)p;
    int half = (int)(fb_width / 2);
    *out_y = 0;
    *out_h = (int)fb_height;
    *out_w = half;
    *out_x = (eye == 0) ? 0 : half;
}
