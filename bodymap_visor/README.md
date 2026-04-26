# aether-visor — wire protocol

The Pi-side visor is a native renderer (`src/main.c` + `src/kms.c`)
that pulls a world description from the Velour server and renders
it stereoscopically to a single panel split left/right.

This document is the **wire protocol** between the two halves so
the C side and the Django side stay in step.

## Endpoint

```
GET /aether/<slug>/visor.json[?stereo=1&ipd=0.063&fov=90&w=1920&h=1080]
```

Returns a JSON manifest. Public worlds are readable without auth;
unpublished worlds require staff session.

### Optional query parameters

The visor passes calibration values per-request so the operator
can re-tune from the URL bar without editing world rows:

| param   | unit    | default | meaning                            |
|---------|---------|---------|------------------------------------|
| `stereo`| 0/1     | 0       | render two eyes (vs mono preview)  |
| `ipd`   | metres  | 0.063   | interpupillary distance            |
| `fov`   | degrees | 90      | per-eye horizontal field of view   |
| `w`     | px      | 1920    | per-eye framebuffer width          |
| `h`     | px      | 1080    | per-eye framebuffer height         |
| `near`  | metres  | 0.05    | near clip plane                    |
| `far`   | metres  | 200     | far clip plane                     |

## Manifest shape

```jsonc
{
  "world": {
    "slug":         "cafe-1",
    "title":        "Cafe 1",
    "skyColor":     "#87ceeb",
    "groundColor":  "#3a7d44",
    "groundSize":   200.0,
    "ambientLight": 0.5,
    "fogNear":      0,
    "fogFar":       0,
    "fogColor":     "#87ceeb",
    "gravity":      9.8,
    "hdri":         "https://…/hdri.exr"   // absolute URL
  },
  "spawn":  [x, y, z],
  "stereo": {
    "enabled":      false,
    "ipd_m":        0.063,
    "fov_deg":      90.0,
    "eye_width_px": 1920,
    "eye_height_px": 1080,
    "clip_near_m":  0.05,
    "clip_far_m":   200.0
  },
  "entities": [
    {
      "id":            42,
      "name":          "table-3",
      "mesh":          "https://…/asset.glb",   // absolute URL
      "meshType":      "gltf",
      "primitive":     "",                      // box / sphere / etc.
      "color":         "#808080",
      "position":      [x, y, z],
      "rotation":      [rx_deg, ry_deg, rz_deg],
      "scale":         [sx, sy, sz],
      "behavior":      "static",
      "behaviorSpeed": 1.0,
      "behaviorTags":  ["wander"]               // EntityScript slugs
    }
  ],
  "portals": [
    {
      "label":      "to-cafe-2",
      "targetSlug": "cafe-2",
      "manifest":   "https://…/cafe-2/visor.json",
      "position":   [x, y, z],
      "size":       [w, h]
    }
  ]
}
```

All asset/manifest URLs are absolutised by the server, so the C
side never needs to URL-resolve. The visor walks `entities` once,
spawns a renderable per row, and re-fetches the manifest on
portal traversal (no incremental sync — full re-load is the
spec).

## C-side phase status

- ✅ `kms.c` / `kms.h` — DRM/KMS + GBM + EGL + GLES3 bring-up
  (Phase 1, scaffolding shipped 2026-04-18)
- ✅ `main.c` — main loop with stereo viewport split and
  per-eye matrix dispatch (Phase 2)
- ✅ `net.c` / `net.h` — libcurl fetch of the manifest URL
- ✅ `world.c` / `world.h` — cJSON parse → struct world_manifest
  with entities, portals, stereo block
- ✅ `stereo.c` / `stereo.h` — per-eye projection + view matrix
  (YXZ Euler, IPD-offset eye position, column-major output) +
  viewport rect computation
- ✅ `pose.c` / `pose.h` — Unix-domain SOCK_DGRAM consumer of
  bodymap ESP mesh head poses, drains to latest sample on each
  frame
- ⏳ `gltf.c` — cgltf load of referenced .glb assets and a
  vertex-shader / fragment-shader entity renderer

What main does today: opens DRM, fetches one manifest at startup,
parses it, opens the pose UDS at `/run/aether-visor/pose.sock`,
and per frame drains the latest pose, computes both eye matrices
via stereo.c, and stamps each viewport with a slightly-shifted
shade of the manifest sky colour so an operator can verify the
left/right viewport split before glTF entity rendering lands.

Build deps (Debian / Raspberry Pi OS):

```
sudo apt install -y libdrm-dev libgbm-dev libegl1-mesa-dev \
    libgles2-mesa-dev libcurl4-openssl-dev libcjson-dev pkg-config
```

The HUD path (`bodymap_hud/`) is the active head-mounted target.
The visor is the higher-end VR build.
