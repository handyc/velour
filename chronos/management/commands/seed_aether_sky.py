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
// Lazy init on the first frame. Builds sun + sun-light + moon, the
// empty entity pools for planets and satellites, the cardinal posts,
// and kicks off the static fetch of the bright-stars catalog.
if (!ctx.state.init) {
    ctx.state.init = true;
    ctx.state.lastFetch = 5;     // fetch immediately on first frame
    ctx.state.fetching = false;
    ctx.state.R = 200;           // celestial-sphere radius (metres)
    ctx.state.lastObserver = null;
    ctx.state.computedAt = '';

    // The anchor entity has scale 0.001 (a hack to keep its primitive
    // mesh imperceptible while still being included by the scene
    // serializer, which filters visible=False rows). All celestial
    // bodies and cardinal posts are therefore added to ctx.scene
    // directly — adding them as children of ctx.entity would inherit
    // the 0.001 scale and shrink the sun to 8 mm at 20 cm distance.

    // Sun — bright self-lit sphere; its position drives a directional
    // light so the moon picks up the correct phase from Lambertian
    // shading, no shader gymnastics required.
    const sun = new THREE.Mesh(
        new THREE.SphereGeometry(8, 24, 24),
        new THREE.MeshBasicMaterial({color: 0xffd966, fog: false})
    );
    sun.visible = false;
    ctx.scene.add(sun);
    ctx.state.sun = sun;

    // DirectionalLight needs its target in the scene graph for the
    // light direction to be honoured. A bare Object3D at the world
    // origin (where the player spawns) is fine.
    const sunLight = new THREE.DirectionalLight(0xffffff, 0.0);
    sunLight.position.set(0, 100, 0);
    const sunTarget = new THREE.Object3D();
    sunTarget.position.set(0, 0, 0);
    ctx.scene.add(sunLight);
    ctx.scene.add(sunTarget);
    sunLight.target = sunTarget;
    ctx.state.sunLight = sunLight;

    // Moon — Lambert sphere; phase emerges from the sun light.
    const moon = new THREE.Mesh(
        new THREE.SphereGeometry(4, 32, 32),
        new THREE.MeshLambertMaterial({color: 0xcccccc})
    );
    moon.visible = false;
    ctx.scene.add(moon);
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
        ctx.scene.add(post);
    }
    console.log('chronos-sky: anchor initialised, awaiting first fetch');

    // Bright-star points (Phase 2). Geometry is empty until the static
    // catalog fetch resolves; per-second LST math repositions them.
    ctx.state.starPoints = null;
    ctx.state.starCatalog = null;
    ctx.state.lastStarUpdate = 0;
    ctx.state.STAR_UPDATE_S = 30;   // Earth rotates 7.5°/30 s — sub-perceptual

    // Atmospheric sky (Phase 2). Three-stop palette interpolated by
    // sun altitude. SKY_DAY for daylight, SKY_DUSK for civil twilight,
    // SKY_NIGHT for astronomical night. The starting scene.background
    // (#08111f, set by the World) reads as deep night.
    ctx.state.SKY_DAY   = new THREE.Color(0x6da7d6);  // slate sky-blue
    ctx.state.SKY_DUSK  = new THREE.Color(0xff8a4f);  // sodium-orange
    ctx.state.SKY_NIGHT = new THREE.Color(0x040714);  // deep blue-black
    ctx.state.lastSunAlt = null;

    fetch('/static/chronos/bright_stars.json')
        .then(r => r.ok ? r.json() : null)
        .then(data => { if (data && data.stars) buildStarPoints(data.stars); })
        .catch(err => console.warn('star catalog fetch failed:', err));
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

// Approximate star color from Johnson B-V. Hot blue-white at -0.3, cool red
// at +1.6. Linear-segment palette — adequate at a few pixels per star.
function bvToColor(bv) {
    if (bv == null || !Number.isFinite(bv)) bv = 0.6;
    if (bv < 0)        return [0.72, 0.85, 1.00];   // O/B
    if (bv < 0.4)      return [0.95, 0.97, 1.00];   // A
    if (bv < 0.8)      return [1.00, 1.00, 0.92];   // F/G
    if (bv < 1.4)      return [1.00, 0.85, 0.65];   // K
    return                    [1.00, 0.65, 0.45];   // M
}

function buildStarPoints(catalog) {
    const n = catalog.length;
    const positions = new Float32Array(n * 3);
    const colors = new Float32Array(n * 3);
    const sizes = new Float32Array(n);
    for (let i = 0; i < n; i++) {
        const s = catalog[i];
        // mag → display size; brightest few pop, faintest still visible at 1px.
        sizes[i] = Math.max(1.0, Math.min(7.5, 5.5 - s.mag));
        const c = bvToColor(s.bv);
        colors[i*3+0] = c[0]; colors[i*3+1] = c[1]; colors[i*3+2] = c[2];
        // Park off-screen until updateStarPositions fills them in.
        positions[i*3+0] = 0; positions[i*3+1] = -1e4; positions[i*3+2] = 0;
    }
    const geom = new THREE.BufferGeometry();
    geom.setAttribute('position', new THREE.BufferAttribute(positions, 3));
    geom.setAttribute('color',    new THREE.BufferAttribute(colors,    3));
    geom.setAttribute('size',     new THREE.BufferAttribute(sizes,     1));
    const mat = new THREE.PointsMaterial({
        vertexColors: true, sizeAttenuation: false, size: 2.5,
        transparent: true, opacity: 0.0,
    });
    const points = new THREE.Points(geom, mat);
    points.frustumCulled = false;
    ctx.scene.add(points);
    ctx.state.starPoints = points;
    ctx.state.starCatalog = catalog;
    updateStarPositions();
}

// Greenwich Mean Sidereal Time (degrees), then add longitude for LST.
// IAU 1982 polynomial; accurate to a few seconds for our purposes.
function computeLST(date, lonDeg) {
    const ms = date.getTime();
    const jd = ms / 86400000 + 2440587.5;
    const t = (jd - 2451545.0) / 36525;
    let gmst = 280.46061837
             + 360.98564736629 * (jd - 2451545.0)
             + 0.000387933 * t * t
             - t * t * t / 38710000;
    return ((gmst + lonDeg) % 360 + 360) % 360;
}

function updateStarPositions() {
    if (!ctx.state.starPoints || !ctx.state.lastObserver) return;
    const obs = ctx.state.lastObserver;
    const latRad = obs.lat * Math.PI / 180;
    const sinLat = Math.sin(latRad), cosLat = Math.cos(latRad);
    const lstRad = computeLST(new Date(), obs.lon) * Math.PI / 180;
    const R = ctx.state.R;
    const positions = ctx.state.starPoints.geometry.attributes.position.array;
    const cat = ctx.state.starCatalog;
    for (let i = 0; i < cat.length; i++) {
        const s = cat[i];
        const decRad = s.dec * Math.PI / 180;
        const sinDec = Math.sin(decRad), cosDec = Math.cos(decRad);
        const haRad = lstRad - s.ra * Math.PI / 180;
        const sinHa = Math.sin(haRad), cosHa = Math.cos(haRad);
        const sinAlt = sinDec * sinLat + cosDec * cosLat * cosHa;
        if (sinAlt < -0.05) {
            // Below horizon — park out of view; size attribute keeps a
            // valid range so the GPU never reads a NaN.
            positions[i*3+1] = -1e4;
            continue;
        }
        const altR = Math.asin(Math.max(-1, Math.min(1, sinAlt)));
        const cosAlt = Math.cos(altR);
        const sinAz = -cosDec * sinHa / cosAlt;
        const cosAz = (sinDec - sinAlt * sinLat) / (cosAlt * cosLat);
        const azR = Math.atan2(sinAz, cosAz);
        positions[i*3+0] =  R * cosAlt * Math.sin(azR);
        positions[i*3+1] =  R * sinAlt;
        positions[i*3+2] = -R * cosAlt * Math.cos(azR);
    }
    ctx.state.starPoints.geometry.attributes.position.needsUpdate = true;
}

// Atmospheric sky and stellar opacity, both keyed off sun altitude.
// Two interpolation segments meeting at sun_alt = -6° (civil twilight),
// where SKY_DUSK peaks. Above +6°, full SKY_DAY; below -12°, full
// SKY_NIGHT. The fog color tracks so the horizon doesn't disagree
// with the sky.
function updateAtmosphere(sunAltDeg) {
    if (sunAltDeg == null || !Number.isFinite(sunAltDeg)) return;
    const dayMix = Math.max(0, Math.min(1, (sunAltDeg + 6) / 12));
    const twiMix = sunAltDeg >= -12
        ? Math.max(0, 1 - Math.abs(sunAltDeg + 6) / 12)
        : 0;
    const c = new THREE.Color()
        .copy(ctx.state.SKY_NIGHT)
        .lerp(ctx.state.SKY_DUSK, twiMix)
        .lerp(ctx.state.SKY_DAY,  dayMix);
    if (ctx.scene.background && ctx.scene.background.copy) {
        ctx.scene.background.copy(c);
    }
    if (ctx.scene.fog && ctx.scene.fog.color) {
        ctx.scene.fog.color.copy(c);
    }
    if (ctx.state.starPoints) {
        // Stars opaque at sun_alt < -8°, fully invisible at sun_alt > -2°.
        const op = Math.max(0, Math.min(1, (-sunAltDeg - 2) / 6));
        ctx.state.starPoints.material.opacity = op;
        ctx.state.starPoints.visible = op > 0.02;
    }
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
        // Civil twilight rolls intensity smoothly: 0 below -6°, 0.9 at +6°.
        const t = Math.max(0, Math.min(1, (ss.sun.alt_deg + 6) / 12));
        ctx.state.sunLight.intensity = 0.9 * t + 0.05;
        ctx.state.lastSunAlt = ss.sun.alt_deg;
        updateAtmosphere(ss.sun.alt_deg);
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
            ctx.scene.add(mesh);
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
            ctx.scene.remove(mesh);
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
            ctx.scene.add(mesh);
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
            ctx.scene.remove(mesh);
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

// Reposition stars on a 30 s cadence (Earth rotates 7.5° per 30 s — well
// below the perceptual jitter threshold for points at radius 200 m).
ctx.state.lastStarUpdate += ctx.deltaTime;
if (ctx.state.starPoints && ctx.state.lastStarUpdate >= ctx.state.STAR_UPDATE_S) {
    ctx.state.lastStarUpdate = 0;
    updateStarPositions();
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
