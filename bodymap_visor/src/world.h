// In-memory representation of the visor.json manifest.
// Strings are owned by world_manifest and freed by world_free.

#ifndef AETHER_VISOR_WORLD_H
#define AETHER_VISOR_WORLD_H

#include <stddef.h>
#include <stdint.h>

struct world_entity {
    int      id;
    char    *name;
    char    *mesh_url;       // empty when primitive
    char    *primitive;      // "box", "sphere", "" if mesh
    char    *color;          // hex string
    float    position[3];
    float    rotation[3];    // degrees
    float    scale[3];
};

struct world_portal {
    char    *label;
    char    *target_slug;
    char    *manifest_url;
    float    position[3];
    float    size[2];
};

struct world_stereo {
    int      enabled;
    float    ipd_m;
    float    fov_deg;
    int      eye_w;
    int      eye_h;
    float    near_m;
    float    far_m;
};

struct world_manifest {
    char                *world_slug;
    char                *world_title;
    float                spawn[3];
    float                sky_color[3];     // parsed hex
    struct world_stereo  stereo;

    struct world_entity *entities;
    size_t               n_entities;

    struct world_portal *portals;
    size_t               n_portals;
};

// Parse a buffer of manifest JSON into `out`. Returns 1 on
// success. On failure returns 0; `out` is left zeroed and any
// partially-allocated state is freed internally.
int world_parse(const char *json_buf, size_t len,
                struct world_manifest *out);

// Free everything `world_parse` allocated. Safe to call on a
// zeroed world_manifest.
void world_free(struct world_manifest *m);

#endif
