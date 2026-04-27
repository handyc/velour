"""Seed (or refresh) the Chronos Sky Dome — an Aether world that
visualizes the live chronos sky payload as a 3D scene the user can
walk around in.

The world contains one anchor entity at origin with a `chronos-sky-
updater` Script attached. The script runs in three.js's animation
loop, lazily builds sun + moon + planet + satellite meshes on its
first frame, and then re-fetches /chronos/sky.json?track=1 every
five seconds to reposition them by alt/az on a celestial sphere.

Phase 1 scope: positions and basic visuals. Defers stars,
constellations, atmospheric scattering keyed to sun altitude, NEO
flyby visualization, and time-scrubbing.

Idempotent: re-running rebuilds the World, Script, Entity, and
EntityScript via update_or_create. Safe to wire as a cron pipeline
later if we want the world's textual blurb to reflect new phases.

Usage:

    python manage.py seed_aether_sky
"""

from django.core.management.base import BaseCommand


WORLD_SLUG = 'chronos-sky'
ANCHOR_NAME = 'sky-anchor'
SCRIPT_SLUG = 'chronos-sky-updater'


# JS executed once per frame in the Aether renderer. `ctx.state` is
# persistent across frames; `ctx.entity` is the anchor Object3D we
# parent celestial bodies under. Helpers live inside the init block
# and capture ctx.state/ctx.entity by closure — they're rebuilt every
# frame, which is cheap (tens of ns).
SCRIPT_CODE = r"""
// Lazy init on the first frame. Builds sun + sun-light + moon, plus
// empty pools for planets and satellites that fill in once data arrives.
if (!ctx.state.init) {
    ctx.state.init = true;
    ctx.state.lastFetch = 5;     // fetch immediately on first frame
    ctx.state.fetching = false;
    ctx.state.R = 200;           // celestial-sphere radius (metres)
    ctx.state.lastObserver = null;
    ctx.state.computedAt = '';

    // Sun — bright self-lit sphere; its position drives a directional
    // light so the moon picks up the correct phase from Lambertian
    // shading, no shader gymnastics required.
    const sun = new THREE.Mesh(
        new THREE.SphereGeometry(8, 24, 24),
        new THREE.MeshBasicMaterial({color: 0xffd966})
    );
    sun.visible = false;
    ctx.entity.add(sun);
    ctx.state.sun = sun;

    const sunLight = new THREE.DirectionalLight(0xffffff, 0.0);
    sunLight.position.set(0, 100, 0);
    ctx.entity.add(sunLight);
    ctx.state.sunLight = sunLight;

    // Moon — Lambert sphere; phase emerges from the sun light.
    const moon = new THREE.Mesh(
        new THREE.SphereGeometry(4, 32, 32),
        new THREE.MeshLambertMaterial({color: 0xcccccc})
    );
    moon.visible = false;
    ctx.entity.add(moon);
    ctx.state.moon = moon;

    // Pools, keyed by chronos slug.
    ctx.state.planets = new Map();
    ctx.state.satellites = new Map();

    ctx.state.PLANET_COLORS = {
        mercury: 0xc0c0c0, venus:   0xffeac8, mars:    0xc1442f,
        jupiter: 0xddc99e, saturn:  0xe1c884, uranus:  0xb0e0e6,
        neptune: 0x4b6cb7, pluto:   0x8a7a6a,
    };
    ctx.state.GIANT_PLANETS = new Set(['jupiter', 'saturn']);

    // Cardinal markers — small posts on the horizon at N/E/S/W so the
    // visitor can orient. They're cheap and the Aether ground plane is
    // otherwise featureless.
    const cardinalLabels = [
        {dir: 'N', az:   0, color: 0xff6060},
        {dir: 'E', az:  90, color: 0xc8c8c8},
        {dir: 'S', az: 180, color: 0xc8c8c8},
        {dir: 'W', az: 270, color: 0xc8c8c8},
    ];
    for (const c of cardinalLabels) {
        const post = new THREE.Mesh(
            new THREE.CylinderGeometry(0.05, 0.05, 2.5, 6),
            new THREE.MeshBasicMaterial({color: c.color})
        );
        const az = c.az * Math.PI / 180;
        post.position.set(15 * Math.sin(az), 1.25, -15 * Math.cos(az));
        ctx.entity.add(post);
    }
}

// Helpers (re-declared each frame; cheap, all closures over state/entity).
function altAzToVec3(altDeg, azDeg, R) {
    const alt = altDeg * Math.PI / 180;
    const az  = azDeg * Math.PI / 180;
    return new THREE.Vector3(
         R * Math.cos(alt) * Math.sin(az),
         R * Math.sin(alt),
        -R * Math.cos(alt) * Math.cos(az)
    );
}

function applyData(data) {
    const R = ctx.state.R;
    ctx.state.computedAt = data.computed_at || '';
    if (data.observer) ctx.state.lastObserver = data.observer;

    // Sun + sun-light.
    const ss = data.solar_system || {};
    if (ss.sun && Number.isFinite(ss.sun.alt_deg)) {
        const v = altAzToVec3(ss.sun.alt_deg, ss.sun.az_deg, R);
        ctx.state.sun.position.copy(v);
        ctx.state.sun.visible = ss.sun.alt_deg > -3;
        ctx.state.sunLight.position.copy(v);
        ctx.state.sunLight.target = ctx.entity;
        // Civil twilight rolls intensity smoothly: 0 below -6°, 0.9 at +6°.
        const t = Math.max(0, Math.min(1, (ss.sun.alt_deg + 6) / 12));
        ctx.state.sunLight.intensity = 0.9 * t + 0.05;
    }

    // Moon.
    if (ss.moon && Number.isFinite(ss.moon.alt_deg)) {
        const v = altAzToVec3(ss.moon.alt_deg, ss.moon.az_deg, R);
        ctx.state.moon.position.copy(v);
        ctx.state.moon.visible = ss.moon.alt_deg > -3;
    }

    // Planets — build on first sight, reposition thereafter.
    const planets = ss.planets || [];
    const seenPlanets = new Set();
    for (const p of planets) {
        if (!p.slug) continue;
        seenPlanets.add(p.slug);
        let mesh = ctx.state.planets.get(p.slug);
        if (!mesh) {
            const color = ctx.state.PLANET_COLORS[p.slug] || 0xffffff;
            const radius = ctx.state.GIANT_PLANETS.has(p.slug) ? 2.5 : 1.5;
            mesh = new THREE.Mesh(
                new THREE.SphereGeometry(radius, 16, 16),
                new THREE.MeshBasicMaterial({color: color})
            );
            mesh.userData.planetSlug = p.slug;
            ctx.entity.add(mesh);
            ctx.state.planets.set(p.slug, mesh);
        }
        if (Number.isFinite(p.alt_deg)) {
            mesh.position.copy(altAzToVec3(p.alt_deg, p.az_deg, R));
            mesh.visible = p.alt_deg > -2;
        } else {
            mesh.visible = false;
        }
    }
    for (const [slug, mesh] of ctx.state.planets.entries()) {
        if (!seenPlanets.has(slug)) {
            ctx.entity.remove(mesh);
            ctx.state.planets.delete(slug);
        }
    }

    // Satellites.
    const rows = (data.rows || []).filter(r => r.kind === 'satellite');
    const seenSats = new Set();
    for (const s of rows) {
        if (!s.slug) continue;
        seenSats.add(s.slug);
        let mesh = ctx.state.satellites.get(s.slug);
        if (!mesh) {
            mesh = new THREE.Mesh(
                new THREE.SphereGeometry(0.6, 12, 12),
                new THREE.MeshBasicMaterial({color: 0xffffff})
            );
            mesh.userData.satSlug = s.slug;
            ctx.entity.add(mesh);
            ctx.state.satellites.set(s.slug, mesh);
        }
        if (Number.isFinite(s.alt_deg)) {
            mesh.position.copy(altAzToVec3(s.alt_deg, s.az_deg, R));
            // Only above the horizon; brightness via magnitude (lower = brighter).
            mesh.visible = s.alt_deg > 0;
            const mag = Number.isFinite(s.magnitude) ? s.magnitude : 4;
            const brightness = Math.max(0.3, Math.min(1, (6 - mag) / 6));
            mesh.material.color.setScalar(brightness);
        } else {
            mesh.visible = false;
        }
    }
    for (const [slug, mesh] of ctx.state.satellites.entries()) {
        if (!seenSats.has(slug)) {
            ctx.entity.remove(mesh);
            ctx.state.satellites.delete(slug);
        }
    }
}

// Throttled fetch — once every 5 s. fetch() is non-blocking; the
// frame loop never waits for the network.
ctx.state.lastFetch += ctx.deltaTime;
if (ctx.state.lastFetch >= 5 && !ctx.state.fetching) {
    ctx.state.lastFetch = 0;
    ctx.state.fetching = true;
    fetch('/chronos/sky.json?track=1', {credentials: 'same-origin'})
        .then(r => r.ok ? r.json() : null)
        .then(data => { if (data) applyData(data); })
        .catch(err => console.warn('chronos-sky fetch failed:', err))
        .finally(() => { ctx.state.fetching = false; });
}
"""


WORLD_DESCRIPTION = (
    'A live 3D rendering of the Velour observer\'s sky. Sun + moon + '
    'naked-eye planets + brightest satellites are positioned on a '
    'celestial sphere by their current altitude and azimuth, '
    'refreshed every five seconds from /chronos/sky.json. Look up. '
    'Look around. Walk through. Cardinal posts at N/E/S/W mark the '
    'horizon — N is the red one. The ground is non-physical; flight '
    'is enabled so you can rise to inspect a satellite track.'
)


class Command(BaseCommand):
    help = 'Create or refresh the Chronos Sky Dome Aether world.'

    def handle(self, *args, **opts):
        from aether.models import Entity, EntityScript, Script, World

        world, w_created = World.objects.update_or_create(
            slug=WORLD_SLUG,
            defaults={
                'title':         'Chronos Sky Dome',
                'description':   WORLD_DESCRIPTION,
                'skybox':        'color',
                'sky_color':     '#08111f',
                'ground_color':  '#181820',
                'ground_size':   80.0,
                'ambient_light': 0.15,
                'fog_near':      300.0,
                'fog_far':       450.0,
                'fog_color':     '#08111f',
                'gravity':       -9.81,
                'allow_flight':  True,
                'spawn_x':        0.0,
                'spawn_y':        1.6,
                'spawn_z':        0.0,
                'published':     True,
            },
        )

        script, _ = Script.objects.update_or_create(
            slug=SCRIPT_SLUG,
            defaults={
                'name':        'Chronos sky updater',
                'description': ('Fetches /chronos/sky.json every 5 s and '
                                'positions sun, moon, planets, and the '
                                'tracked satellites on a celestial sphere '
                                'by altitude/azimuth. Sun position drives '
                                'a directional light, so the moon\'s phase '
                                'reads correctly via Lambertian shading.'),
                'event':       'update',
                'is_builtin':  True,
                'code':        SCRIPT_CODE,
            },
        )

        # The anchor entity sits at world origin and is effectively
        # invisible (scale 0.001). It must stay visible=True because
        # the scene serializer filters out invisible entities and
        # the script wouldn't get loaded otherwise. The script adds
        # all the celestial bodies as children of this anchor.
        entity, _ = Entity.objects.update_or_create(
            world=world, name=ANCHOR_NAME,
            defaults={
                'primitive':       'sphere',
                'primitive_color': '#ffffff',
                'pos_x': 0.0, 'pos_y': 0.0, 'pos_z': 0.0,
                'scale_x': 0.001, 'scale_y': 0.001, 'scale_z': 0.001,
                'visible': True,
                'behavior': 'scripted',
            },
        )

        EntityScript.objects.update_or_create(
            entity=entity, script=script,
            defaults={'enabled': True, 'props': {}, 'sort_order': 0},
        )

        verb = 'Created' if w_created else 'Refreshed'
        self.stdout.write(self.style.SUCCESS(
            f'{verb} world "{world.title}" at /aether/{world.slug}/. '
            f'Anchor entity "{ANCHOR_NAME}" with script '
            f'"{script.slug}" attached.'
        ))
