#ifndef KMS_H
#define KMS_H

#include <EGL/egl.h>
#include <GLES3/gl3.h>
#include <stdbool.h>
#include <stdint.h>

struct kms_display {
    int drm_fd;
    uint32_t connector_id;
    uint32_t crtc_id;
    uint32_t mode_blob_id;
    uint32_t width;
    uint32_t height;

    struct gbm_device  *gbm;
    struct gbm_surface *gbm_surface;

    EGLDisplay egl_display;
    EGLContext egl_context;
    EGLSurface egl_surface;

    struct gbm_bo *current_bo;
    uint32_t       current_fb;
};

bool kms_open(struct kms_display *d, const char *card_path);
void kms_close(struct kms_display *d);
bool kms_swap(struct kms_display *d);

#endif
