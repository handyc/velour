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
    const sunLabel = makeTextSprite('Sun', {color: '#ffd966', heightM: 4});
    sunLabel.position.set(0, 14, 0);  // local — sits above the disc
    sun.add(sunLabel);

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
    const moonLabel = makeTextSprite('Moon', {color: '#e6e6e6', heightM: 3.5});
    moonLabel.position.set(0, 8, 0);
    moon.add(moonLabel);

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
        const letterColor = '#' + c.color.toString(16).padStart(6, '0');
        const letter = makeTextSprite(c.dir, {
            color: letterColor, heightM: 1.0, fontPx: 80,
        });
        letter.position.copy(post.position);
        letter.position.y += 1.6;  // float above the post head
        ctx.scene.add(letter);
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

    // Constellation lines (Phase 3). Built after the star catalog
    // resolves so each line endpoint can be a real (RA, Dec) lookup
    // by Hipparcos number into the star catalog. They share the
    // 30 s star-update cadence and the sky-darkness opacity ramp.
    ctx.state.constellationLines = null;
    ctx.state.constellationData = null;
    ctx.state.starByHip = null;

    // Milky Way (Phase 5) — scatter cloud. Same RA/Dec→alt/az math
    // as stars; rendered behind constellation lines and slightly
    // dimmer overall, with a softer fade-in (still visible into
    // nautical twilight where stars are still washed out).
    ctx.state.milkyWayPoints = null;
    ctx.state.milkyWayCoords = null;

    // NEO close-approach billboard (Phase 6). A multi-line text
    // sprite parked east-northeast of the spawn point, repainted
    // each time /chronos/sky.json fetches with the next 3 NEOs.
    {
        const sprite = new THREE.Sprite(new THREE.SpriteMaterial({
            transparent: true, depthWrite: false, fog: false,
        }));
        sprite.position.set(8, 2.8, -12);  // visible from default heading
        sprite.scale.set(0.001, 0.001, 1); // start tiny; first paint resizes
        sprite.renderOrder = 11;
        ctx.scene.add(sprite);
        ctx.state.neoBillboard = sprite;
    }

    // Time-scrubbing (Phase 7). DOM overlay slider that shifts LST
    // for stars / constellations / Milky Way only; live celestial
    // bodies (sun, moon, planets, sats) stay at server "now" because
    // shifting them correctly needs server-side recomputation.
    ctx.state.timeOffsetHours = 0;
    buildTimeScrubber();
    buildCompass();

    fetch('/static/chronos/bright_stars.json')
        .then(r => r.ok ? r.json() : null)
        .then(data => {
            if (!data || !data.stars) return;
            buildStarPoints(data.stars);
            return fetch('/static/chronos/constellation_lines.json');
        })
        .then(r => r && r.ok ? r.json() : null)
        .then(data => {
            if (data && data.constellations) buildConstellations(data);
            return fetch('/static/chronos/milky_way.json');
        })
        .then(r => r && r.ok ? r.json() : null)
        .then(data => {
            if (data && data.points) buildMilkyWay(data.points);
        })
        .catch(err => console.warn('catalog fetch failed:', err));
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

// Inverse: alt/az → RA/Dec given observer latitude and current LST.
// Used to "freeze" the celestial coordinates of sun/moon/planets so
// the time scrubber can re-project them onto the sky for a different
// effective time. Sat positions are NOT round-tripped this way —
// their TLE-driven motion is too fast for stored RA/Dec to be valid
// across a ±24 h scrub window.
function altAzToRaDec(altDeg, azDeg, latRad, lstDeg) {
    const alt = altDeg * Math.PI / 180;
    const az  = azDeg * Math.PI / 180;
    const sinAlt = Math.sin(alt), cosAlt = Math.cos(alt);
    const sinAz  = Math.sin(az),  cosAz  = Math.cos(az);
    const sinLat = Math.sin(latRad), cosLat = Math.cos(latRad);
    const sinDec = sinAlt * sinLat + cosAlt * cosLat * cosAz;
    const dec = Math.asin(Math.max(-1, Math.min(1, sinDec)));
    const cosDec = Math.cos(dec);
    const sinHa = -sinAz * cosAlt / cosDec;
    const cosHa = (sinAlt - sinDec * sinLat) / (cosDec * cosLat);
    const haDeg = Math.atan2(sinHa, cosHa) * 180 / Math.PI;
    const ra = ((lstDeg - haDeg) % 360 + 360) % 360;
    return {ra: ra, dec: dec * 180 / Math.PI};
}

// Build a billboarded text sprite via CanvasTexture. Used for the
// cardinal letters and every named celestial body so the visitor
// can tell a colored dot from another colored dot.
function makeTextSprite(text, opts) {
    opts = opts || {};
    const fontPx = opts.fontPx || 56;
    const color = opts.color || '#ffffff';
    const stroke = opts.stroke || 'rgba(0,0,0,0.85)';
    const pad = 10;
    const canvas = document.createElement('canvas');
    const c2d = canvas.getContext('2d');
    c2d.font = 'bold ' + fontPx + 'px sans-serif';
    const w = Math.ceil(c2d.measureText(text).width) + pad * 2;
    const h = fontPx + pad * 2;
    canvas.width = w; canvas.height = h;
    // Re-set after resize (canvas resets state on width/height assignment).
    c2d.font = 'bold ' + fontPx + 'px sans-serif';
    c2d.textBaseline = 'middle';
    c2d.lineWidth = 5;
    c2d.strokeStyle = stroke;
    c2d.strokeText(text, pad, h / 2);
    c2d.fillStyle = color;
    c2d.fillText(text, pad, h / 2);
    const tex = new THREE.CanvasTexture(canvas);
    tex.needsUpdate = true;
    const mat = new THREE.SpriteMaterial({
        map: tex, transparent: true,
        depthWrite: false, fog: false,
    });
    const sprite = new THREE.Sprite(mat);
    const heightM = opts.heightM || 1.6;
    sprite.scale.set(heightM * w / h, heightM, 1);
    sprite.renderOrder = 10;
    return sprite;
}

// Render Mercury/Venus/Mars phase into a square canvas. Bright limb
// is fixed on the +x side of the canvas; the sprite is rotated each
// frame so that direction aligns with the screen-space line from
// planet to sun. Phase angle α with illum = (1 + cos α) / 2; the
// terminator on the projected disk is a half-ellipse with semi-axes
// (R, R·|cos α|). For illum ≥ 0.5 (gibbous) the terminator curves
// into the dark hemisphere on the left; for illum < 0.5 (crescent)
// it curves into the bright hemisphere on the right.
function drawPlanetPhase(canvas, color, illum) {
    const R = canvas.width / 2;
    const c2d = canvas.getContext('2d');
    c2d.clearRect(0, 0, canvas.width, canvas.height);
    const cr = (color >> 16) & 0xff;
    const cg = (color >> 8) & 0xff;
    const cb = color & 0xff;
    const dark = 'rgb(' + Math.round(cr * 0.12) + ','
                       + Math.round(cg * 0.13) + ','
                       + Math.round(cb * 0.18) + ')';
    const bright = 'rgb(' + cr + ',' + cg + ',' + cb + ')';
    const cx = R, cy = R;
    const a = Math.abs(2 * illum - 1) * R;
    c2d.fillStyle = dark;
    c2d.beginPath();
    c2d.arc(cx, cy, R, 0, Math.PI * 2);
    c2d.fill();
    c2d.fillStyle = bright;
    c2d.beginPath();
    // Right limb: top → right → bottom.
    c2d.arc(cx, cy, R, -Math.PI / 2, Math.PI / 2, false);
    if (illum >= 0.5) {
        // Gibbous — terminator curves left, fill the larger right portion.
        c2d.ellipse(cx, cy, a, R, 0, Math.PI / 2, 3 * Math.PI / 2, false);
    } else {
        // Crescent — terminator curves right, only the thin sliver near limb is lit.
        c2d.ellipse(cx, cy, a, R, 0, Math.PI / 2, -Math.PI / 2, true);
    }
    c2d.closePath();
    c2d.fill();
}

function makePhaseSprite(color, radius, illum) {
    const canvas = document.createElement('canvas');
    canvas.width = 128;
    canvas.height = 128;
    drawPlanetPhase(canvas, color, illum);
    const tex = new THREE.CanvasTexture(canvas);
    tex.needsUpdate = true;
    const mat = new THREE.SpriteMaterial({
        map: tex, transparent: true,
        depthWrite: false, fog: false,
    });
    const sprite = new THREE.Sprite(mat);
    const d = radius * 2.1;  // slight upsize so phase reads from a distance
    sprite.scale.set(d, d, 1);
    sprite.userData.phaseCanvas = canvas;
    sprite.renderOrder = 5;
    return sprite;
}

function repaintPhaseSprite(sprite, color, illum) {
    const canvas = sprite.userData.phaseCanvas;
    if (!canvas) return;
    drawPlanetPhase(canvas, color, illum);
    if (sprite.material.map) sprite.material.map.needsUpdate = true;
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
    const byHip = new Map();
    for (let i = 0; i < n; i++) {
        const s = catalog[i];
        // mag → display size; brightest few pop, faintest still visible at 1px.
        sizes[i] = Math.max(1.0, Math.min(7.5, 5.5 - s.mag));
        const c = bvToColor(s.bv);
        colors[i*3+0] = c[0]; colors[i*3+1] = c[1]; colors[i*3+2] = c[2];
        // Park off-screen until updateStarPositions fills them in.
        positions[i*3+0] = 0; positions[i*3+1] = -1e4; positions[i*3+2] = 0;
        if (s.hip != null) byHip.set(s.hip, i);
    }
    ctx.state.starByHip = byHip;
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

// Build a THREE.LineSegments from the constellations payload. Each
// vertex is filled with the *current* alt/az of its referenced star,
// computed once at build time by reading the star Points geometry
// (which buildStarPoints populated by calling updateStarPositions).
// Subsequent re-positions piggyback on updateStarPositions; we don't
// recompute alt/az here, just copy from the star buffer.
function buildConstellations(payload) {
    const byHip = ctx.state.starByHip;
    if (!byHip) return;
    const segments = [];
    const labels = [];  // [{sprite, starIndices: [...]}]
    for (const c of payload.constellations || []) {
        const localStarIndices = new Set();
        let segmentsHere = 0;
        for (const [hipA, hipB] of (c.lines || [])) {
            const ia = byHip.get(hipA);
            const ib = byHip.get(hipB);
            if (ia != null && ib != null) {
                segments.push([ia, ib]);
                localStarIndices.add(ia);
                localStarIndices.add(ib);
                segmentsHere++;
            }
        }
        if (!segmentsHere) continue;
        const sprite = makeTextSprite(c.name, {
            color: '#9ab8d8', heightM: 1.3, fontPx: 38,
        });
        sprite.position.set(0, -1e4, 0);  // park; refresh places it
        sprite.material.opacity = 0;
        sprite.renderOrder = 9;  // behind stars (10) but above lines
        ctx.scene.add(sprite);
        labels.push({sprite: sprite, starIndices: [...localStarIndices]});
    }
    if (!segments.length) return;
    const positions = new Float32Array(segments.length * 6);
    const geom = new THREE.BufferGeometry();
    geom.setAttribute('position', new THREE.BufferAttribute(positions, 3));
    const mat = new THREE.LineBasicMaterial({
        color: 0x5a7090, transparent: true, opacity: 0.0,
        // Lines render slightly translucent and blue-grey so they
        // suggest the figure without competing with the stars.
    });
    const lines = new THREE.LineSegments(geom, mat);
    lines.frustumCulled = false;
    ctx.scene.add(lines);
    ctx.state.constellationLines = lines;
    ctx.state.constellationSegments = segments;
    ctx.state.constellationLabels = labels;
    refreshConstellations();
    console.log('chronos-sky: constellations loaded:',
                payload.constellations.length, 'figures,',
                segments.length, 'segments,',
                labels.length, 'labels');
}

// Reposition each constellation's name sprite at the centroid of its
// member stars. Star positions are already in updateStarPositions's
// buffer, so we just average — cheap. Labels below the horizon are
// hidden by parking them off-screen.
function refreshConstellationLabels() {
    const labels = ctx.state.constellationLabels;
    const stars = ctx.state.starPoints;
    if (!labels || !stars) return;
    const starPos = stars.geometry.attributes.position.array;
    const R = ctx.state.R;
    for (const lab of labels) {
        let sx = 0, sy = 0, sz = 0, n = 0;
        for (const idx of lab.starIndices) {
            const off = idx * 3;
            // Skip endpoints below horizon (parked at y = -1e4).
            if (starPos[off + 1] < -1000) continue;
            sx += starPos[off + 0];
            sy += starPos[off + 1];
            sz += starPos[off + 2];
            n++;
        }
        // If fewer than half the stars are above the horizon, skip the
        // label — the figure is too cropped to read.
        if (n * 2 < lab.starIndices.length) {
            lab.sprite.position.set(0, -1e4, 0);
            continue;
        }
        sx /= n; sy /= n; sz /= n;
        // Renormalise to the celestial sphere so the label sits at the
        // same depth as its stars (avoids parallax against the dome).
        const m = Math.sqrt(sx * sx + sy * sy + sz * sz);
        if (m > 1e-3) {
            const k = R / m;
            lab.sprite.position.set(sx * k, sy * k, sz * k);
        }
    }
}

// Re-fill the LineSegments position buffer from the current star
// positions. Called from updateStarPositions so lines move in lock-
// step with their endpoint stars.
function refreshConstellations() {
    const lines = ctx.state.constellationLines;
    const segments = ctx.state.constellationSegments;
    const stars = ctx.state.starPoints;
    if (!lines || !segments || !stars) return;
    const starPos = stars.geometry.attributes.position.array;
    const linePos = lines.geometry.attributes.position.array;
    for (let i = 0; i < segments.length; i++) {
        const [ia, ib] = segments[i];
        // Each star occupies 3 floats in starPos; each segment 6 in linePos.
        const sa = ia * 3, sb = ib * 3;
        const off = i * 6;
        // Hide the whole segment if either endpoint is below horizon
        // (parked at y = -1e4 by updateStarPositions).
        if (starPos[sa+1] < -1000 || starPos[sb+1] < -1000) {
            // Collapse both ends to the same off-screen point.
            for (let j = 0; j < 6; j++) linePos[off+j] = -1e4;
            continue;
        }
        linePos[off+0] = starPos[sa+0];
        linePos[off+1] = starPos[sa+1];
        linePos[off+2] = starPos[sa+2];
        linePos[off+3] = starPos[sb+0];
        linePos[off+4] = starPos[sb+1];
        linePos[off+5] = starPos[sb+2];
    }
    lines.geometry.attributes.position.needsUpdate = true;
    refreshConstellationLabels();
}

// Time scrubber (Phase 7). DOM overlay — slider + readout + reset.
// Idempotent: re-running won't double-inject because we check for
// the existing element by id. Pointer-events on the wrapper so the
// scene's pointer-lock controls don't swallow slider drags.
function buildTimeScrubber() {
    if (document.getElementById('chronos-sky-scrubber')) return;
    const wrap = document.createElement('div');
    wrap.id = 'chronos-sky-scrubber';
    wrap.style.cssText = [
        'position:fixed', 'bottom:14px', 'left:50%',
        'transform:translateX(-50%)',
        'background:rgba(8,12,22,0.86)', 'color:#dceaff',
        'padding:8px 14px',
        'border:1px solid #3a4a60', 'border-radius:6px',
        'z-index:1000', 'pointer-events:auto',
        'font-family:"Helvetica Neue",Arial,sans-serif',
        'font-size:12px', 'display:flex', 'align-items:center',
        'gap:10px',
    ].join(';') + ';';
    wrap.innerHTML =
        '<label style="white-space:nowrap;color:#8fb6e6;">Time</label>' +
        '<input id="chronos-sky-scrubber-input" type="range" ' +
        '       min="-24" max="24" step="0.25" value="0" ' +
        '       style="width:240px;">' +
        '<span id="chronos-sky-scrubber-readout" ' +
        '      style="min-width:120px;text-align:right;' +
        '             font-family:ui-monospace,monospace;color:#dceaff;">' +
        'now</span>' +
        '<button id="chronos-sky-scrubber-reset" type="button" ' +
        '        style="background:#21262d;color:#dceaff;' +
        '               border:1px solid #3a4a60;padding:3px 9px;' +
        '               border-radius:4px;cursor:pointer;">' +
        'Now</button>' +
        '<small style="color:#6e8090;">stars · planets · sun · moon</small>';
    document.body.appendChild(wrap);

    const input = document.getElementById('chronos-sky-scrubber-input');
    const readout = document.getElementById('chronos-sky-scrubber-readout');
    const reset = document.getElementById('chronos-sky-scrubber-reset');

    function fmtOffset(h) {
        if (Math.abs(h) < 0.005) return 'now';
        const sign = h >= 0 ? '+' : '−';
        const abs = Math.abs(h);
        const hh = Math.floor(abs);
        const mm = Math.round((abs - hh) * 60);
        const t = new Date(Date.now() + h * 3600 * 1000);
        const hhmm = (hh.toString().padStart(2, '0') + 'h' +
                      mm.toString().padStart(2, '0'));
        return sign + hhmm + ' · ' + t.toUTCString().slice(17, 22) + 'Z';
    }
    function apply(h) {
        ctx.state.timeOffsetHours = h;
        readout.textContent = fmtOffset(h);
        // Force an instant re-position so the slider feels responsive.
        // updateStarPositions covers stars + constellations + Milky Way;
        // repositionLiveBodies covers sun + moon + planets + atmosphere.
        updateStarPositions();
        repositionLiveBodies();
    }
    input.addEventListener('input', () => apply(parseFloat(input.value)));
    reset.addEventListener('click', () => {
        input.value = '0';
        apply(0);
    });
}

// Compass HUD (Phase 8). Top-right rose that rotates against the
// camera's yaw so its "N" tick always indicates true north on
// screen. Polaris's altitude (= observer latitude) is shown below
// the rose so the visitor knows where to look up to find the pole
// star itself. Idempotent injection — re-entering the world reuses
// the existing element.
function buildCompass() {
    if (document.getElementById('chronos-sky-compass')) return;
    const wrap = document.createElement('div');
    wrap.id = 'chronos-sky-compass';
    wrap.style.cssText = [
        'position:fixed', 'top:14px', 'right:14px',
        'width:96px',
        'background:rgba(8,12,22,0.78)',
        'border:1px solid #3a4a60', 'border-radius:8px',
        'padding:6px 6px 4px', 'z-index:1000',
        'pointer-events:none',
        'font-family:"Helvetica Neue",Arial,sans-serif',
        'color:#dceaff', 'text-align:center',
    ].join(';') + ';';
    wrap.innerHTML =
        '<svg viewBox="-50 -50 100 100" width="84" height="84" ' +
        '     style="display:block;margin:0 auto;overflow:visible;">' +
        '  <circle r="44" fill="rgba(8,12,22,0.55)" ' +
        '          stroke="#3a4a60" stroke-width="1"/>' +
        '  <g id="chronos-sky-compass-rose">' +
        '    <line x1="0" y1="-44" x2="0" y2="-30" ' +
        '          stroke="#ff6060" stroke-width="2.5"/>' +
        '    <text y="-18" text-anchor="middle" ' +
        '          font-size="13" fill="#ff6060" font-weight="bold">N</text>' +
        '    <text x="22" y="4" text-anchor="middle" ' +
        '          font-size="10" fill="#9ab" font-weight="bold">E</text>' +
        '    <text y="26" text-anchor="middle" ' +
        '          font-size="10" fill="#9ab" font-weight="bold">S</text>' +
        '    <text x="-22" y="4" text-anchor="middle" ' +
        '          font-size="10" fill="#9ab" font-weight="bold">W</text>' +
        '  </g>' +
        '  <polygon points="0,-5 -4,5 4,5" fill="#dceaff"/>' +
        '</svg>' +
        '<div id="chronos-sky-compass-readout" ' +
        '     style="font-size:10px;color:#8fb6e6;margin-top:2px;' +
        '            font-family:ui-monospace,monospace;letter-spacing:0.3px;">' +
        '  ↑ Polaris</div>';
    document.body.appendChild(wrap);
}

function updateCompass() {
    const rose = document.getElementById('chronos-sky-compass-rose');
    if (!rose || !ctx.camera) return;
    const fwd = new THREE.Vector3();
    ctx.camera.getWorldDirection(fwd);
    fwd.y = 0;
    if (fwd.lengthSq() < 1e-6) return;
    fwd.normalize();
    // Bearing: clockwise angle from -Z (north). At fwd=(0,0,-1) → 0;
    // fwd=(1,0,0) (east) → π/2. SVG rotate is clockwise positive, but
    // we want the N tick to drift left when looking east, so apply
    // the negative bearing.
    const bearing = Math.atan2(fwd.x, -fwd.z);
    rose.setAttribute('transform',
        'rotate(' + (-bearing * 180 / Math.PI).toFixed(1) + ')');
    // Refresh the readout when observer changes — Polaris altitude
    // equals the observer's latitude (north hemisphere) or "below
    // horizon" when at southern lat.
    const obs = ctx.state.lastObserver;
    if (obs && ctx.state.compassObsKey !== obs.lat) {
        ctx.state.compassObsKey = obs.lat;
        const out = document.getElementById('chronos-sky-compass-readout');
        if (out) {
            const polarisAlt = obs.lat;
            if (polarisAlt > 0.5) {
                out.textContent = '↑ Polaris ' + polarisAlt.toFixed(0) + '°';
            } else if (polarisAlt < -0.5) {
                out.textContent = 'Polaris hidden';
            } else {
                out.textContent = 'Polaris on horizon';
            }
        }
    }
}

// NEO billboard (Phase 6). Multi-line text panel showing the next
// few asteroid close approaches from /chronos/sky.json's `neos`
// field. Repainted on each successful fetch.
function renderTextLinesToCanvas(lines, opts) {
    opts = opts || {};
    const fontPx = opts.fontPx || 26;
    const lineH = Math.round(fontPx * 1.45);
    const padX = 24, padY = 18;
    const canvas = document.createElement('canvas');
    const c2d = canvas.getContext('2d');
    const baseFont = '"Helvetica Neue", Arial, sans-serif';
    c2d.font = '600 ' + fontPx + 'px ' + baseFont;
    let maxW = 0;
    for (const line of lines) {
        const w = c2d.measureText(line.text || line).width;
        if (w > maxW) maxW = w;
    }
    canvas.width  = Math.ceil(maxW) + padX * 2;
    canvas.height = Math.ceil(lineH * lines.length) + padY * 2;
    // re-bind font after resize (canvas state resets)
    c2d.font = '600 ' + fontPx + 'px ' + baseFont;
    c2d.fillStyle = 'rgba(8, 12, 22, 0.86)';
    c2d.fillRect(0, 0, canvas.width, canvas.height);
    c2d.strokeStyle = '#3a4a60';
    c2d.lineWidth = 3;
    c2d.strokeRect(1.5, 1.5, canvas.width - 3, canvas.height - 3);
    c2d.textBaseline = 'top';
    let y = padY;
    for (const line of lines) {
        const text = line.text || line;
        c2d.fillStyle = line.color || '#dceaff';
        c2d.fillText(text, padX, y);
        y += lineH;
    }
    const tex = new THREE.CanvasTexture(canvas);
    tex.needsUpdate = true;
    return tex;
}

function updateNeoBillboard(neos) {
    const sprite = ctx.state.neoBillboard;
    if (!sprite) return;
    const lines = [
        {text: 'Near-Earth approaches (next out)', color: '#ffd966'},
        {text: '', color: '#dceaff'},
    ];
    if (!neos || neos.length === 0) {
        lines.push({text: '  none in window', color: '#8b9eb6'});
    } else {
        for (const n of neos.slice(0, 3)) {
            const d = new Date(n.when_iso);
            const dateStr = d.toUTCString().slice(5, 16);  // "27 Apr 2026"
            const ldStr = (typeof n.dist_ld === 'number')
                ? n.dist_ld.toFixed(1) + ' LD' : '';
            const vStr = (typeof n.v_km_s === 'number')
                ? n.v_km_s.toFixed(1) + ' km/s' : '';
            const sizeStr = n.size_label || '';
            lines.push({text: '  ' + dateStr + '   ' + n.designation,
                        color: '#dceaff'});
            const detail = ['     ' + ldStr, sizeStr, vStr]
                .filter(s => s).join('  ·  ');
            lines.push({text: detail, color: '#8fb6e6'});
            lines.push({text: '', color: '#dceaff'});
        }
    }
    const tex = renderTextLinesToCanvas(lines, {fontPx: 26});
    if (sprite.material.map) sprite.material.map.dispose();
    sprite.material.map = tex;
    sprite.material.needsUpdate = true;
    // Match world scale to the canvas aspect — keep height fixed at
    // ~3.2 m so the panel stays a consistent visual size.
    const heightM = 3.2;
    const aspect = tex.image.width / tex.image.height;
    sprite.scale.set(heightM * aspect, heightM, 1);
}

// Milky Way (Phase 5). Scatter cloud along the galactic plane with
// brightness baked in by build_milky_way.py. Each point is one (ra,
// dec, brightness) triple; we use the same RA/Dec→alt/az math as
// stars and update on the same 30 s cadence.
function buildMilkyWay(points) {
    const n = points.length;
    const positions = new Float32Array(n * 3);
    const colors = new Float32Array(n * 3);
    const sizes = new Float32Array(n);
    // Pack the (ra, dec) pairs into a flat Float32Array for cache-
    // friendly iteration in updateMilkyWayPositions. Brightness goes
    // into the per-vertex color so we don't have to modulate at draw.
    const coords = new Float32Array(n * 2);
    for (let i = 0; i < n; i++) {
        const p = points[i];
        coords[i*2+0] = p.ra;
        coords[i*2+1] = p.dec;
        const b = Math.max(0.05, Math.min(1.0, p.b ?? 0.5));
        // Slight blue cast — the band reads as cooler than typical
        // foreground stars on a real night sky.
        colors[i*3+0] = b * 0.85;
        colors[i*3+1] = b * 0.90;
        colors[i*3+2] = b * 1.00;
        sizes[i] = 1.5 + b * 1.2;
        positions[i*3+1] = -1e4;  // park
    }
    const geom = new THREE.BufferGeometry();
    geom.setAttribute('position', new THREE.BufferAttribute(positions, 3));
    geom.setAttribute('color',    new THREE.BufferAttribute(colors,    3));
    geom.setAttribute('size',     new THREE.BufferAttribute(sizes,     1));
    const mat = new THREE.PointsMaterial({
        vertexColors: true, sizeAttenuation: false, size: 1.8,
        transparent: true, opacity: 0.0,
    });
    const cloud = new THREE.Points(geom, mat);
    cloud.frustumCulled = false;
    cloud.renderOrder = -1;  // behind stars + constellation lines
    ctx.scene.add(cloud);
    ctx.state.milkyWayPoints = cloud;
    ctx.state.milkyWayCoords = coords;
    updateMilkyWayPositions();
    console.log('chronos-sky: Milky Way loaded:', n, 'scatter points');
}

function updateMilkyWayPositions() {
    const cloud = ctx.state.milkyWayPoints;
    const coords = ctx.state.milkyWayCoords;
    if (!cloud || !coords || !ctx.state.lastObserver) return;
    const obs = ctx.state.lastObserver;
    const latRad = obs.lat * Math.PI / 180;
    const sinLat = Math.sin(latRad), cosLat = Math.cos(latRad);
    const offsetMs = (ctx.state.timeOffsetHours || 0) * 3.6e6;
    const effectiveTime = new Date(Date.now() + offsetMs);
    const lstRad = computeLST(effectiveTime, obs.lon) * Math.PI / 180;
    const R = ctx.state.R;
    const positions = cloud.geometry.attributes.position.array;
    const n = coords.length / 2;
    for (let i = 0; i < n; i++) {
        const ra = coords[i*2+0];
        const dec = coords[i*2+1];
        const decRad = dec * Math.PI / 180;
        const sinDec = Math.sin(decRad), cosDec = Math.cos(decRad);
        const haRad = lstRad - ra * Math.PI / 180;
        const sinHa = Math.sin(haRad), cosHa = Math.cos(haRad);
        const sinAlt = sinDec * sinLat + cosDec * cosLat * cosHa;
        if (sinAlt < -0.05) {
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
    cloud.geometry.attributes.position.needsUpdate = true;
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
    const offsetMs = (ctx.state.timeOffsetHours || 0) * 3.6e6;
    const effectiveTime = new Date(Date.now() + offsetMs);
    const lstRad = computeLST(effectiveTime, obs.lon) * Math.PI / 180;
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
    refreshConstellations();
    updateMilkyWayPositions();
}

// Re-project sun, moon, and planets from their stored RA/Dec onto
// the sky for the scrubber's effective time. Drives the sun-light
// position + intensity + atmosphere from the *scrubbed* sun altitude
// so dragging the slider past sunset darkens the sky and brings out
// the stars even when wall-clock time is mid-afternoon.
//
// Satellites are not in this loop — their positions move too fast
// (~5 minutes per ISS pass) for stored RA/Dec to be meaningful.
// They keep using direct alt/az from the latest server fetch.
function repositionLiveBodies() {
    const obs = ctx.state.lastObserver;
    if (!obs) return;
    const latRad = obs.lat * Math.PI / 180;
    const sinLat = Math.sin(latRad), cosLat = Math.cos(latRad);
    const offsetMs = (ctx.state.timeOffsetHours || 0) * 3.6e6;
    const effectiveTime = new Date(Date.now() + offsetMs);
    const lstRad = computeLST(effectiveTime, obs.lon) * Math.PI / 180;
    const R = ctx.state.R;

    function project(mesh, horizonAlt) {
        if (!mesh || mesh.userData.ra == null) return null;
        const decRad = mesh.userData.dec * Math.PI / 180;
        const sinDec = Math.sin(decRad), cosDec = Math.cos(decRad);
        const haRad = lstRad - mesh.userData.ra * Math.PI / 180;
        const sinHa = Math.sin(haRad), cosHa = Math.cos(haRad);
        const sinAlt = sinDec * sinLat + cosDec * cosLat * cosHa;
        const altR = Math.asin(Math.max(-1, Math.min(1, sinAlt)));
        const cosAlt = Math.cos(altR);
        const sinAz = -cosDec * sinHa / cosAlt;
        const cosAz = (sinDec - sinAlt * sinLat) / (cosAlt * cosLat);
        const azR = Math.atan2(sinAz, cosAz);
        mesh.position.set(
             R * cosAlt * Math.sin(azR),
             R * sinAlt,
            -R * cosAlt * Math.cos(azR)
        );
        const altDeg = altR * 180 / Math.PI;
        mesh.visible = altDeg > horizonAlt;
        return altDeg;
    }

    const sun = ctx.state.sun;
    const sunAlt = project(sun, -3);
    if (sunAlt != null) {
        ctx.state.sunLight.position.copy(sun.position);
        const t = Math.max(0, Math.min(1, (sunAlt + 6) / 12));
        ctx.state.sunLight.intensity = 0.9 * t + 0.05;
        ctx.state.lastSunAlt = sunAlt;
        updateAtmosphere(sunAlt);
    }
    project(ctx.state.moon, -3);
    for (const mesh of ctx.state.planets.values()) {
        project(mesh, -2);
    }
    // Rotate phase sprites so their bright limb points at the sun's
    // screen-space position. Project both into NDC (y up); atan2 of
    // the delta gives the angle to apply to material.rotation. Three.js
    // sprite rotation is mathematical-positive (CCW in NDC), which
    // matches atan2(dy, dx) when dy is NDC-y.
    if (ctx.state.sun && ctx.state.sun.visible) {
        const sunNDC = ctx.state.sun.position.clone().project(ctx.camera);
        for (const mesh of ctx.state.planets.values()) {
            if (!mesh.userData.phaseCanvas || !mesh.visible) continue;
            const pNDC = mesh.position.clone().project(ctx.camera);
            const dx = sunNDC.x - pNDC.x;
            const dy = sunNDC.y - pNDC.y;
            if (dx * dx + dy * dy > 1e-8) {
                mesh.material.rotation = Math.atan2(dy, dx);
            }
        }
    }
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
        if (ctx.state.constellationLines) {
            // Lines render at ~60% of star opacity so they recede when
            // looked at directly but support the stars at a glance.
            const lineOp = op * 0.55;
            ctx.state.constellationLines.material.opacity = lineOp;
            ctx.state.constellationLines.visible = lineOp > 0.02;
        }
        if (ctx.state.constellationLabels) {
            // Labels fade in slightly later than lines, so the stars
            // settle in first; once the sky is dark, labels read
            // brighter than the lines themselves.
            const labelOp = Math.max(0, Math.min(0.85, op * 0.85));
            for (const lab of ctx.state.constellationLabels) {
                lab.sprite.material.opacity = labelOp;
                lab.sprite.visible = labelOp > 0.02
                                  && lab.sprite.position.y > -1000;
            }
        }
    }
    if (ctx.state.milkyWayPoints) {
        // Milky Way fades in slightly before bright stars do — the band
        // is bigger and dimmer per dot so it needs a darker sky to read.
        // Fully visible by sun_alt = -10°; gone by sun_alt = -3°.
        const mwOp = Math.max(0, Math.min(0.85, (-sunAltDeg - 3) / 7));
        ctx.state.milkyWayPoints.material.opacity = mwOp;
        ctx.state.milkyWayPoints.visible = mwOp > 0.02;
    }
}

function applyData(data) {
    const R = ctx.state.R;
    ctx.state.computedAt = data.computed_at || '';
    if (data.observer) ctx.state.lastObserver = data.observer;
    updateNeoBillboard(data.neos);

    const obs = ctx.state.lastObserver;
    const latRad = obs ? obs.lat * Math.PI / 180 : null;
    const lstNowDeg = obs ? computeLST(new Date(), obs.lon) : null;

    // Sun — store RA/Dec for scrubbed re-projection. Actual position
    // and sun-light + atmosphere update happens in repositionLiveBodies.
    const ss = data.solar_system || {};
    if (ss.sun && Number.isFinite(ss.sun.alt_deg) && latRad != null) {
        const rd = altAzToRaDec(
            ss.sun.alt_deg, ss.sun.az_deg, latRad, lstNowDeg);
        ctx.state.sun.userData.ra = rd.ra;
        ctx.state.sun.userData.dec = rd.dec;
    }

    // Moon — store RA/Dec.
    if (ss.moon && Number.isFinite(ss.moon.alt_deg) && latRad != null) {
        const rd = altAzToRaDec(
            ss.moon.alt_deg, ss.moon.az_deg, latRad, lstNowDeg);
        ctx.state.moon.userData.ra = rd.ra;
        ctx.state.moon.userData.dec = rd.dec;
    }

    // Planets — build on first sight, store RA/Dec for re-projection.
    const planets = ss.planets || [];
    const seenPlanets = new Set();
    for (const p of planets) {
        if (!p.slug) continue;
        seenPlanets.add(p.slug);
        let mesh = ctx.state.planets.get(p.slug);
        const color = ctx.state.PLANET_COLORS[p.slug] || 0xffffff;
        const radius = ctx.state.GIANT_PLANETS.has(p.slug) ? 2.5 : 1.5;
        if (!mesh) {
            if (Number.isFinite(p.illuminated_frac)) {
                // Inner planet — billboard with the right phase shape.
                mesh = makePhaseSprite(color, radius, p.illuminated_frac);
                mesh.userData.phaseFrac = p.illuminated_frac;
                mesh.userData.color = color;
            } else {
                mesh = new THREE.Mesh(
                    new THREE.SphereGeometry(radius, 16, 16),
                    new THREE.MeshBasicMaterial({color: color})
                );
            }
            mesh.userData.planetSlug = p.slug;
            mesh.userData.radius = radius;
            ctx.scene.add(mesh);
            ctx.state.planets.set(p.slug, mesh);
            const labelColor = '#' + color.toString(16).padStart(6, '0');
            const label = makeTextSprite(p.name || p.slug, {
                color: labelColor, heightM: 2.4,
            });
            label.position.set(0, radius * 2 + 1.5, 0);
            mesh.add(label);
        }
        // Repaint the phase canvas if the lit fraction has shifted
        // perceptibly (~1% in either direction). For Venus that's a
        // few hours of orbital motion; once a fetch is plenty.
        if (mesh.userData.phaseCanvas
            && Number.isFinite(p.illuminated_frac)) {
            const prev = mesh.userData.phaseFrac;
            if (prev == null || Math.abs(prev - p.illuminated_frac) > 0.01) {
                repaintPhaseSprite(mesh, color, p.illuminated_frac);
                mesh.userData.phaseFrac = p.illuminated_frac;
            }
        }
        if (Number.isFinite(p.alt_deg) && latRad != null) {
            const rd = altAzToRaDec(
                p.alt_deg, p.az_deg, latRad, lstNowDeg);
            mesh.userData.ra = rd.ra;
            mesh.userData.dec = rd.dec;
        }
    }
    for (const [slug, mesh] of ctx.state.planets.entries()) {
        if (!seenPlanets.has(slug)) {
            ctx.scene.remove(mesh);
            ctx.state.planets.delete(slug);
        }
    }

    // Sun/moon/planets now re-projected through stored RA/Dec, so the
    // time scrubber moves them along with the stars + Milky Way.
    repositionLiveBodies();

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
            // Only label brighter sats — fainter ones spam labels at
            // every blink. Threshold matches typical naked-eye limit.
            if (Number.isFinite(s.magnitude) && s.magnitude < 4.0) {
                const label = makeTextSprite(s.name || s.slug, {
                    color: '#cccccc', heightM: 1.6, fontPx: 48,
                });
                label.position.set(0, 1.4, 0);
                mesh.add(label);
            }
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

// Compass HUD — every frame; cheap DOM transform.
updateCompass();
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
