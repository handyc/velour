#include "kms.h"

#include <fcntl.h>
#include <stdio.h>
#include <string.h>
#include <unistd.h>

#include <gbm.h>
#include <xf86drm.h>
#include <xf86drmMode.h>

static const EGLint CONFIG_ATTRIBS[] = {
    EGL_SURFACE_TYPE,    EGL_WINDOW_BIT,
    EGL_RENDERABLE_TYPE, EGL_OPENGL_ES3_BIT,
    EGL_RED_SIZE,   8,
    EGL_GREEN_SIZE, 8,
    EGL_BLUE_SIZE,  8,
    EGL_ALPHA_SIZE, 0,
    EGL_DEPTH_SIZE, 24,
    EGL_NONE,
};

static const EGLint CONTEXT_ATTRIBS[] = {
    EGL_CONTEXT_MAJOR_VERSION, 3,
    EGL_CONTEXT_MINOR_VERSION, 1,
    EGL_NONE,
};

// Pick the first connected output + its preferred mode. Good enough for
// a single-display bring-up; the stereo pass will eventually open two
// connectors (one per micro-HDMI).
static bool pick_connector_and_mode(int fd, struct kms_display *d,
                                    drmModeModeInfo *mode_out) {
    drmModeRes *res = drmModeGetResources(fd);
    if (!res) return false;

    for (int i = 0; i < res->count_connectors; i++) {
        drmModeConnector *c = drmModeGetConnector(fd, res->connectors[i]);
        if (!c) continue;
        if (c->connection == DRM_MODE_CONNECTED && c->count_modes > 0) {
            *mode_out = c->modes[0];
            d->connector_id = c->connector_id;
            d->width  = mode_out->hdisplay;
            d->height = mode_out->vdisplay;
            drmModeFreeConnector(c);

            // Use the connector's encoder → crtc.
            drmModeEncoder *enc = drmModeGetEncoder(fd, c->encoder_id);
            if (enc) {
                d->crtc_id = enc->crtc_id;
                drmModeFreeEncoder(enc);
            } else if (res->count_crtcs > 0) {
                d->crtc_id = res->crtcs[0];
            }
            drmModeFreeResources(res);
            return d->crtc_id != 0;
        }
        drmModeFreeConnector(c);
    }
    drmModeFreeResources(res);
    return false;
}

bool kms_open(struct kms_display *d, const char *card_path) {
    memset(d, 0, sizeof(*d));

    d->drm_fd = open(card_path ? card_path : "/dev/dri/card0",
                     O_RDWR | O_CLOEXEC);
    if (d->drm_fd < 0) { perror("open drm"); return false; }

    drmModeModeInfo mode;
    if (!pick_connector_and_mode(d->drm_fd, d, &mode)) {
        fprintf(stderr, "kms: no connected output\n");
        return false;
    }

    d->gbm = gbm_create_device(d->drm_fd);
    if (!d->gbm) { fprintf(stderr, "gbm: create_device failed\n"); return false; }

    d->gbm_surface = gbm_surface_create(
        d->gbm, d->width, d->height,
        GBM_FORMAT_XRGB8888,
        GBM_BO_USE_SCANOUT | GBM_BO_USE_RENDERING);
    if (!d->gbm_surface) { fprintf(stderr, "gbm: surface_create failed\n"); return false; }

    d->egl_display = eglGetDisplay((EGLNativeDisplayType)d->gbm);
    if (!eglInitialize(d->egl_display, NULL, NULL)) {
        fprintf(stderr, "egl: init failed\n"); return false;
    }
    eglBindAPI(EGL_OPENGL_ES_API);

    EGLConfig config;
    EGLint    n;
    if (!eglChooseConfig(d->egl_display, CONFIG_ATTRIBS, &config, 1, &n) || n < 1) {
        fprintf(stderr, "egl: no matching config\n"); return false;
    }

    d->egl_context = eglCreateContext(d->egl_display, config,
                                      EGL_NO_CONTEXT, CONTEXT_ATTRIBS);
    d->egl_surface = eglCreateWindowSurface(
        d->egl_display, config,
        (EGLNativeWindowType)d->gbm_surface, NULL);

    if (d->egl_context == EGL_NO_CONTEXT || d->egl_surface == EGL_NO_SURFACE) {
        fprintf(stderr, "egl: context/surface create failed\n"); return false;
    }

    eglMakeCurrent(d->egl_display, d->egl_surface, d->egl_surface, d->egl_context);
    return true;
}

// Present the current backbuffer: swap EGL → lock next GBM bo → wrap
// as DRM framebuffer → drmModeSetCrtc → release the previous bo.
// This is the pageflip-less "SetCrtc each frame" path — simplest to
// get on screen; we'll move to atomic + pageflip events for tear-free
// stereo later.
bool kms_swap(struct kms_display *d) {
    eglSwapBuffers(d->egl_display, d->egl_surface);

    struct gbm_bo *bo = gbm_surface_lock_front_buffer(d->gbm_surface);
    if (!bo) { fprintf(stderr, "gbm: lock_front_buffer failed\n"); return false; }

    uint32_t handle = gbm_bo_get_handle(bo).u32;
    uint32_t stride = gbm_bo_get_stride(bo);
    uint32_t fb = 0;
    if (drmModeAddFB(d->drm_fd, d->width, d->height, 24, 32,
                     stride, handle, &fb)) {
        perror("drmModeAddFB");
        gbm_surface_release_buffer(d->gbm_surface, bo);
        return false;
    }

    drmModeModeInfo mode;
    drmModeConnector *c = drmModeGetConnector(d->drm_fd, d->connector_id);
    if (!c || c->count_modes == 0) {
        if (c) drmModeFreeConnector(c);
        return false;
    }
    mode = c->modes[0];
    drmModeFreeConnector(c);

    drmModeSetCrtc(d->drm_fd, d->crtc_id, fb, 0, 0,
                   &d->connector_id, 1, &mode);

    if (d->current_bo) {
        drmModeRmFB(d->drm_fd, d->current_fb);
        gbm_surface_release_buffer(d->gbm_surface, d->current_bo);
    }
    d->current_bo = bo;
    d->current_fb = fb;
    return true;
}

void kms_close(struct kms_display *d) {
    if (d->egl_display) {
        eglMakeCurrent(d->egl_display, EGL_NO_SURFACE, EGL_NO_SURFACE,
                       EGL_NO_CONTEXT);
        if (d->egl_surface) eglDestroySurface(d->egl_display, d->egl_surface);
        if (d->egl_context) eglDestroyContext(d->egl_display, d->egl_context);
        eglTerminate(d->egl_display);
    }
    if (d->current_bo) {
        drmModeRmFB(d->drm_fd, d->current_fb);
        gbm_surface_release_buffer(d->gbm_surface, d->current_bo);
    }
    if (d->gbm_surface) gbm_surface_destroy(d->gbm_surface);
    if (d->gbm)         gbm_device_destroy(d->gbm);
    if (d->drm_fd >= 0) close(d->drm_fd);
    memset(d, 0, sizeof(*d));
}
