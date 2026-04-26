// Manifest JSON → struct world_manifest. Uses cJSON (header-only,
// MIT). Only the fields the renderer actually uses are extracted;
// extra fields are silently ignored so server-side additions don't
// break the C side. Missing/malformed values fall back to sane
// defaults rather than failing the whole parse.

#include <stdlib.h>
#include <string.h>
#include <stdio.h>

#include <cjson/cJSON.h>

#include "world.h"

static char *dup_str(const cJSON *node) {
    if (!cJSON_IsString(node) || !node->valuestring) return NULL;
    return strdup(node->valuestring);
}

static float get_num(const cJSON *node, float fallback) {
    if (cJSON_IsNumber(node)) return (float)node->valuedouble;
    return fallback;
}

static int get_int(const cJSON *node, int fallback) {
    if (cJSON_IsNumber(node)) return (int)node->valueint;
    return fallback;
}

static int get_bool(const cJSON *node, int fallback) {
    if (cJSON_IsBool(node)) return cJSON_IsTrue(node) ? 1 : 0;
    return fallback;
}

static void parse_vec3(const cJSON *arr, float out[3], float fallback) {
    out[0] = out[1] = out[2] = fallback;
    if (!cJSON_IsArray(arr)) return;
    int i = 0;
    cJSON *e;
    cJSON_ArrayForEach(e, arr) {
        if (i >= 3) break;
        out[i++] = get_num(e, fallback);
    }
}

static void parse_vec2(const cJSON *arr, float out[2], float fallback) {
    out[0] = out[1] = fallback;
    if (!cJSON_IsArray(arr)) return;
    int i = 0;
    cJSON *e;
    cJSON_ArrayForEach(e, arr) {
        if (i >= 2) break;
        out[i++] = get_num(e, fallback);
    }
}

static void parse_hex_color(const char *hex, float out[3]) {
    out[0] = out[1] = out[2] = 0.5f;
    if (!hex || hex[0] != '#' || strlen(hex) < 7) return;
    unsigned r, g, b;
    if (sscanf(hex + 1, "%02x%02x%02x", &r, &g, &b) == 3) {
        out[0] = r / 255.0f;
        out[1] = g / 255.0f;
        out[2] = b / 255.0f;
    }
}

static int parse_entities(const cJSON *arr, struct world_entity **out,
                          size_t *out_n) {
    *out = NULL;
    *out_n = 0;
    if (!cJSON_IsArray(arr)) return 1;
    size_t n = (size_t)cJSON_GetArraySize(arr);
    if (n == 0) return 1;

    struct world_entity *ents = calloc(n, sizeof(*ents));
    if (!ents) return 0;

    size_t i = 0;
    cJSON *e;
    cJSON_ArrayForEach(e, arr) {
        struct world_entity *en = &ents[i++];
        en->id = get_int(cJSON_GetObjectItemCaseSensitive(e, "id"), 0);
        en->name = dup_str(cJSON_GetObjectItemCaseSensitive(e, "name"));
        en->mesh_url = dup_str(cJSON_GetObjectItemCaseSensitive(e, "mesh"));
        en->primitive = dup_str(cJSON_GetObjectItemCaseSensitive(e, "primitive"));
        en->color = dup_str(cJSON_GetObjectItemCaseSensitive(e, "color"));
        parse_vec3(cJSON_GetObjectItemCaseSensitive(e, "position"),
                   en->position, 0);
        parse_vec3(cJSON_GetObjectItemCaseSensitive(e, "rotation"),
                   en->rotation, 0);
        parse_vec3(cJSON_GetObjectItemCaseSensitive(e, "scale"),
                   en->scale, 1.0f);
    }
    *out = ents;
    *out_n = n;
    return 1;
}

static int parse_portals(const cJSON *arr, struct world_portal **out,
                         size_t *out_n) {
    *out = NULL;
    *out_n = 0;
    if (!cJSON_IsArray(arr)) return 1;
    size_t n = (size_t)cJSON_GetArraySize(arr);
    if (n == 0) return 1;

    struct world_portal *ps = calloc(n, sizeof(*ps));
    if (!ps) return 0;

    size_t i = 0;
    cJSON *p;
    cJSON_ArrayForEach(p, arr) {
        struct world_portal *po = &ps[i++];
        po->label = dup_str(cJSON_GetObjectItemCaseSensitive(p, "label"));
        po->target_slug = dup_str(cJSON_GetObjectItemCaseSensitive(p, "targetSlug"));
        po->manifest_url = dup_str(cJSON_GetObjectItemCaseSensitive(p, "manifest"));
        parse_vec3(cJSON_GetObjectItemCaseSensitive(p, "position"),
                   po->position, 0);
        parse_vec2(cJSON_GetObjectItemCaseSensitive(p, "size"),
                   po->size, 1.0f);
    }
    *out = ps;
    *out_n = n;
    return 1;
}

int world_parse(const char *json_buf, size_t len,
                struct world_manifest *out) {
    (void)len;
    memset(out, 0, sizeof(*out));

    cJSON *root = cJSON_Parse(json_buf);
    if (!root) {
        fprintf(stderr, "world_parse: JSON parse failed\n");
        return 0;
    }

    cJSON *world = cJSON_GetObjectItemCaseSensitive(root, "world");
    if (cJSON_IsObject(world)) {
        out->world_slug = dup_str(cJSON_GetObjectItemCaseSensitive(world, "slug"));
        out->world_title = dup_str(cJSON_GetObjectItemCaseSensitive(world, "title"));
        cJSON *sky = cJSON_GetObjectItemCaseSensitive(world, "skyColor");
        parse_hex_color(cJSON_IsString(sky) ? sky->valuestring : NULL,
                        out->sky_color);
    }
    parse_vec3(cJSON_GetObjectItemCaseSensitive(root, "spawn"),
               out->spawn, 0);

    cJSON *st = cJSON_GetObjectItemCaseSensitive(root, "stereo");
    if (cJSON_IsObject(st)) {
        out->stereo.enabled = get_bool(
            cJSON_GetObjectItemCaseSensitive(st, "enabled"), 0);
        out->stereo.ipd_m = get_num(
            cJSON_GetObjectItemCaseSensitive(st, "ipd_m"), 0.063f);
        out->stereo.fov_deg = get_num(
            cJSON_GetObjectItemCaseSensitive(st, "fov_deg"), 90.0f);
        out->stereo.eye_w = get_int(
            cJSON_GetObjectItemCaseSensitive(st, "eye_width_px"), 1920);
        out->stereo.eye_h = get_int(
            cJSON_GetObjectItemCaseSensitive(st, "eye_height_px"), 1080);
        out->stereo.near_m = get_num(
            cJSON_GetObjectItemCaseSensitive(st, "clip_near_m"), 0.05f);
        out->stereo.far_m = get_num(
            cJSON_GetObjectItemCaseSensitive(st, "clip_far_m"), 200.0f);
    } else {
        out->stereo.enabled = 0;
        out->stereo.ipd_m = 0.063f;
        out->stereo.fov_deg = 90.0f;
        out->stereo.eye_w = 1920;
        out->stereo.eye_h = 1080;
        out->stereo.near_m = 0.05f;
        out->stereo.far_m = 200.0f;
    }

    if (!parse_entities(cJSON_GetObjectItemCaseSensitive(root, "entities"),
                        &out->entities, &out->n_entities)) goto fail;
    if (!parse_portals(cJSON_GetObjectItemCaseSensitive(root, "portals"),
                       &out->portals, &out->n_portals)) goto fail;

    cJSON_Delete(root);
    return 1;

fail:
    cJSON_Delete(root);
    world_free(out);
    return 0;
}

void world_free(struct world_manifest *m) {
    if (!m) return;
    free(m->world_slug);
    free(m->world_title);
    for (size_t i = 0; i < m->n_entities; i++) {
        free(m->entities[i].name);
        free(m->entities[i].mesh_url);
        free(m->entities[i].primitive);
        free(m->entities[i].color);
    }
    free(m->entities);
    for (size_t i = 0; i < m->n_portals; i++) {
        free(m->portals[i].label);
        free(m->portals[i].target_slug);
        free(m->portals[i].manifest_url);
    }
    free(m->portals);
    memset(m, 0, sizeof(*m));
}
