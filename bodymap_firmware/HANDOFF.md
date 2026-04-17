# Bodymap integration handoff

Picking up the bodymap work after this branch lands. Bodymap is the
wearable biometric mesh (~10–11 ESP32-S3 SuperMini nodes, one per body
segment) — the firmware is under `bodymap_firmware/` in this repo; the
server-side Django app (`bodymap/`) is specified below but not yet built.

---

## Status matrix

| Piece | State | Notes |
|---|---|---|
| `POST /api/nodes/register` endpoint | Implemented | On branch `mac-self-registration`, awaiting merge. `nodes/tests.py` has 18 passing tests. |
| `Node.self_registered` field + migration | Implemented | `nodes/migrations/0005_node_self_registered.py`. |
| `VELOUR_PROVISIONING_SECRET` setting | Implemented | File-then-env fallback in `velour/settings.py`. Empty → endpoint returns 503. |
| `VelourClient::registerSelf()` | Implemented | `gary_test/src/velour_client.{h,cpp}` also vendored into `bodymap_firmware/lib/velour_client/`. |
| Bodymap firmware scaffold | Implemented | `bodymap_firmware/` — WiFi + registerSelf + ESP-NOW mesh + correlation clustering, with the GY-95T IMU deliberately stubbed until it's soldered. |
| `Bodymap Node v1` HardwareProfile | **Not yet created** | Needs to exist before first ESP boots. |
| `bodymap/` Django app | **Not yet built** | Spec below. |

---

## Prerequisites before first firmware flash

1. **Merge `mac-self-registration` into `main`.** The register endpoint
   that `registerSelf()` calls only exists on that branch today.
2. **Merge this branch (`bodymap-integration`).** Brings in the firmware
   tree and (once built) the `bodymap/` Django app.
3. **Create a `HardwareProfile` named `Bodymap Node v1`** in Django
   admin. `hardware_profile` validation is case-insensitive, but the
   name must exist.
4. **Set `VELOUR_PROVISIONING_SECRET`.** Either write a string to
   `BASE_DIR/provisioning_secret.txt` or set the env var. Empty → the
   endpoint stays disabled and 503s.
5. **Copy `bodymap_firmware/include/wifi_secrets.h.example` →
   `include/wifi_secrets.h`** and fill in WiFi + Velour URL + the same
   provisioning secret.
6. (Optional but recommended) **Create an `Experiment` with slug
   `bodymap`.** Then self-registered nodes auto-attach to it — makes
   dashboard filtering trivial. `api_register` never auto-creates
   experiments, by design.

---

## `bodymap/` Django app — v0 spec

A new first-party app inside Velour. Parallel to `nodes/`,
`experiments/`, etc. Registered in `INSTALLED_APPS`, URL-mounted under
`/bodymap/`.

### Models (`bodymap/models.py`)

```python
from django.db import models
from nodes.models import Node
from experiments.models import Experiment


class Segment(models.Model):
    """Which body-segment role a Node has been assigned (e.g. forearm_left,
    torso). Discovered at runtime by the firmware's clustering layer; the
    firmware POSTs its assigned role here so it persists across reboots
    and is visible to the dashboard.
    """

    ROLE_CHOICES = [
        ('torso',          'Torso'),
        ('head',           'Head'),
        ('neck',           'Neck'),
        ('upper_arm_l',    'Upper arm (left)'),
        ('upper_arm_r',    'Upper arm (right)'),
        ('forearm_l',      'Forearm (left)'),
        ('forearm_r',      'Forearm (right)'),
        ('upper_leg_l',    'Upper leg (left)'),
        ('upper_leg_r',    'Upper leg (right)'),
        ('lower_leg_l',    'Lower leg (left)'),
        ('lower_leg_r',    'Lower leg (right)'),
        ('unassigned',     'Unassigned'),
    ]

    node       = models.OneToOneField(Node, on_delete=models.CASCADE,
                                      related_name='bodymap_segment')
    experiment = models.ForeignKey(Experiment, on_delete=models.CASCADE,
                                   related_name='bodymap_segments')
    role       = models.CharField(max_length=16, choices=ROLE_CHOICES,
                                  default='unassigned')
    confidence = models.FloatField(default=0.0)  # 0..1 from clustering
    assigned_at = models.DateTimeField(auto_now=True)


class LinkObservation(models.Model):
    """Optional. Stores per-pair link-strength snapshots for visualisation
    + debugging. Write a row per peer per reporting cycle. High volume
    (N² growth per fleet, per second) — consider pruning or downsampling
    if it becomes a problem. Safe to start without this and rely solely
    on the firmware's real-time view.
    """

    reporter    = models.ForeignKey(Node, on_delete=models.CASCADE,
                                    related_name='link_observations')
    peer_mac    = models.CharField(max_length=17)  # "AA:BB:..." form
    strength    = models.FloatField()              # ρ in [0, 1]
    observed_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        indexes = [models.Index(fields=['reporter', 'observed_at'])]
```

### URL layout (`bodymap/urls.py`)

- `/bodymap/` — list view of all bodymap nodes + their segment roles
- `/bodymap/<experiment_slug>/` — body diagram for a specific bodymap fleet
- `/bodymap/api/segment/` (POST, bearer-auth) — firmware reports its
  assigned role + confidence here. Matches the auth pattern used by
  `/api/nodes/<slug>/report/`.

### Firmware ↔ server contract

Today the firmware already reports `top_rho`, `n_strong_links`,
`peer_count`, `pkts_tx`, `pkts_rx` as regular sensor channels on the
existing `/api/nodes/<slug>/report/` endpoint. Everything useful about
mesh health is already visible through the standard node detail page.

The new piece is **role assignment**, once the clustering layer (v1)
produces one. Add this to `VelourClient`:

```cpp
// POST /bodymap/api/segment/  { "role": "forearm_l", "confidence": 0.87 }
bool reportSegment(const char* role, float confidence);
```

Call once after clustering stabilises; re-call only when the assigned
role changes (or on re-registration). Idempotent server-side on
(node_id) — updates the existing `Segment` row.

### Admin (`bodymap/admin.py`)

Register `Segment` + `LinkObservation`. The Segment admin should allow
operator override of the firmware's assignment — if clustering gets it
wrong, a human types the correct role and the server stops accepting
autogen updates for that node until cleared (add an `operator_locked`
bool to `Segment`). The firmware doesn't need to know about the lock;
the server just ignores its `reportSegment` calls when locked.

### Templates

- `templates/bodymap/list.html` — table of nodes + current roles.
- `templates/bodymap/diagram.html` — SVG body silhouette with each
  assigned node positioned on the relevant segment. Each node links to
  its detail page in `nodes/`.

### Settings changes

- Add `'bodymap'` to `INSTALLED_APPS` in `velour/settings.py`.
- Add `path('bodymap/', include('bodymap.urls'))` to `velour/urls.py`.

---

## Branch / merge workflow suggestion

```
main
  └── mac-self-registration   (register endpoint + VelourClient changes)
        └── bodymap-integration   (firmware tree + bodymap/ Django app)
```

Merge in order: `mac-self-registration → main`, then
`bodymap-integration → main`. Or squash both into one PR titled
"bodymap fleet integration" — your call. The two are logically separate
but the first is a prerequisite for the second.

---

## First smoke test (once there's at least one flashed ESP)

1. Server: set `VELOUR_PROVISIONING_SECRET`, create `Bodymap Node v1`
   HardwareProfile, create `bodymap` Experiment.
2. Fill `include/wifi_secrets.h` with matching values.
3. `pio run -t upload` to flash.
4. On the Velour node list you should see a new row appear within
   ~15 s, slug `bodymap-<last6mac>`, experiment = `bodymap`,
   `self_registered=True`.
5. On the node detail page within ~10 s: `heartbeat=1.0`, `buf_fill=0.0`
   (IMU still stubbed), `peer_count=0` until a second node joins.
6. Flash a second node. Both should show `peer_count` climbing on the
   next heartbeat.

---

## Known limitations to address in v1

- **GY-95T driver is a stub.** `update()` always returns false, so
  `buf_fill` stays 0 and no real angular velocity flows. Once the chip
  is soldered, implement the UART framing in `lib/gy95t/gy95t.cpp` —
  exact packet format varies by production batch, scope the TX line
  before committing to a parser.
- **Correlation metric is scalar.** Per-pair coherence (the current ρ)
  tells us whether two nodes are probably linked, but not how or in
  which direction. v1: add 3×3 Jacobi SVD of the whitened cross-
  covariance to extract joint-DoF rank (hinge/universal/ball) and the
  relative rotation R_AB.
- **No topology solver.** The peer-link graph needs a solver that walks
  from the root (most-connected node ≈ torso) outward and labels
  limbs. Left/right disambiguation uses gait counter-correlation once
  we have that.
- **No time alignment across peers.** Windows currently line up
  newest-to-newest regardless of the ~1 s broadcast jitter. Workable at
  1 Hz correlation cadence, but tighter sync would improve ρ.
- **Register endpoint is not yet pushed to GitHub / deployed.** Until
  that happens, `registerSelf()` will get a 404 from any existing
  deployment — the stored-credentials path still works for subsequent
  boots but there's no way to get the initial credentials without the
  server having the endpoint.

---

## Memory breadcrumbs for future Claude sessions

Relevant memories under
`~/.claude/projects/-home-handyc-projects-bodymap/memory/`:

- `project_bodymap.md` — high-level bodymap design
- `project_velour_register_unmerged.md` — status of the register endpoint
- `reference_velour_api.md` — Velour API contract for ESP fleet
- `reference_velour.md` — Velour overview

When this work resumes, start by re-reading those and then
`bodymap_firmware/HANDOFF.md` (this file).
