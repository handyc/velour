"""Import 3D objects from external repositories into the Aether library.

Sources:
  - Sketchfab (API token required, set SKETCHFAB_API_TOKEN in env)
  - Poly Haven (no auth needed, CC0 license)

Usage:
  # Search Sketchfab for chairs and import metadata
  python manage.py import_library --source sketchfab --query chair --count 24

  # Import Poly Haven HDRIs
  python manage.py import_library --source polyhaven --type hdri

  # Import a specific Sketchfab model by UID
  python manage.py import_library --source sketchfab --uid abc123def456

  # Seed common object categories
  python manage.py import_library --seed-categories

  # Seed built-in NPC scripts
  python manage.py import_library --seed-scripts
"""

import json
import os
from urllib.error import HTTPError
from urllib.request import Request, urlopen

from django.core.management.base import BaseCommand

from aether.models import LibraryObject, ObjectCategory, Script, WorldPreset


SKETCHFAB_API = 'https://api.sketchfab.com/v3'
POLYHAVEN_API = 'https://api.polyhaven.com'

DEFAULT_CATEGORIES = [
    ('Furniture', [
        'Seating', 'Tables', 'Storage', 'Beds', 'Desks', 'Shelving',
    ]),
    ('Lighting', [
        'Lamps', 'Ceiling lights', 'Wall lights', 'Outdoor lights',
    ]),
    ('Nature', [
        'Trees', 'Plants', 'Rocks', 'Flowers', 'Terrain',
    ]),
    ('Food', [
        'Fruits', 'Prepared food', 'Drinks', 'Kitchen items',
    ]),
    ('Vehicles', [
        'Cars', 'Trucks', 'Bikes', 'Aircraft', 'Boats',
    ]),
    ('Architecture', [
        'Buildings', 'Walls', 'Doors', 'Windows', 'Stairs',
    ]),
    ('Electronics', [
        'Computers', 'Phones', 'Screens', 'Cables', 'Audio',
    ]),
    ('Characters', [
        'Humans', 'Animals', 'Fantasy', 'Robots', 'NPCs',
    ]),
    ('Tools', [
        'Hand tools', 'Power tools', 'Lab equipment', 'Instruments',
    ]),
    ('Decoration', [
        'Art', 'Rugs', 'Curtains', 'Vases', 'Clocks',
    ]),
    ('Skyboxes', [
        'Daytime', 'Sunset', 'Night', 'Overcast', 'Space',
    ]),
]

BUILTIN_SCRIPTS = [
    {
        'name': 'NPC Wander',
        'slug': 'npc-wander',
        'event': 'update',
        'description': 'Wander randomly within a radius. Props: radius (default 15), speed (default 1.5), pauseTime (default 2).',
        'code': """
if (!ctx.state.init) {
    ctx.state.init = true;
    ctx.state.target = null;
    ctx.state.pauseUntil = 0;
    ctx.state.origin = {x: ctx.entity.position.x, z: ctx.entity.position.z};
}
const radius = ctx.props.radius || 15;
const speed = ctx.props.speed || 1.5;
const pauseTime = ctx.props.pauseTime || 2;

if (ctx.elapsed < ctx.state.pauseUntil) return;

if (!ctx.state.target) {
    const angle = Math.random() * Math.PI * 2;
    const dist = Math.random() * radius;
    ctx.state.target = {
        x: ctx.state.origin.x + Math.cos(angle) * dist,
        z: ctx.state.origin.z + Math.sin(angle) * dist,
    };
}
const dx = ctx.state.target.x - ctx.entity.position.x;
const dz = ctx.state.target.z - ctx.entity.position.z;
const dist = Math.sqrt(dx*dx + dz*dz);
if (dist < 0.5) {
    ctx.state.target = null;
    ctx.state.pauseUntil = ctx.elapsed + pauseTime * (0.5 + Math.random());
} else {
    const step = speed * ctx.deltaTime;
    ctx.entity.position.x += (dx / dist) * step;
    ctx.entity.position.z += (dz / dist) * step;
    ctx.entity.rotation.y = Math.atan2(dx, dz);
}
""",
    },
    {
        'name': 'NPC Patrol',
        'slug': 'npc-patrol',
        'event': 'update',
        'description': 'Patrol between waypoints. Props: waypoints (array of {x,z}), speed (default 2), pauseTime (default 1).',
        'code': """
if (!ctx.state.init) {
    ctx.state.init = true;
    ctx.state.waypointIdx = 0;
    ctx.state.pauseUntil = 0;
}
const waypoints = ctx.props.waypoints || [{x:5,z:-5},{x:-5,z:-5},{x:-5,z:-15},{x:5,z:-15}];
const speed = ctx.props.speed || 2;
const pauseTime = ctx.props.pauseTime || 1;

if (ctx.elapsed < ctx.state.pauseUntil) return;

const wp = waypoints[ctx.state.waypointIdx];
const dx = wp.x - ctx.entity.position.x;
const dz = wp.z - ctx.entity.position.z;
const dist = Math.sqrt(dx*dx + dz*dz);
if (dist < 0.5) {
    ctx.state.waypointIdx = (ctx.state.waypointIdx + 1) % waypoints.length;
    ctx.state.pauseUntil = ctx.elapsed + pauseTime;
} else {
    const step = speed * ctx.deltaTime;
    ctx.entity.position.x += (dx / dist) * step;
    ctx.entity.position.z += (dz / dist) * step;
    ctx.entity.rotation.y = Math.atan2(dx, dz);
}
""",
    },
    {
        'name': 'NPC Follow Player',
        'slug': 'npc-follow-player',
        'event': 'update',
        'description': 'Follow the player camera within a range. Props: range (default 20), speed (default 3), minDist (default 3).',
        'code': """
const range = ctx.props.range || 20;
const speed = ctx.props.speed || 3;
const minDist = ctx.props.minDist || 3;
const dist = ctx.distToPlayer();

if (dist > range || dist < minDist) return;

const dx = ctx.player.position.x - ctx.entity.position.x;
const dz = ctx.player.position.z - ctx.entity.position.z;
const step = speed * ctx.deltaTime;
ctx.entity.position.x += (dx / dist) * step;
ctx.entity.position.z += (dz / dist) * step;
ctx.entity.rotation.y = Math.atan2(dx, dz);
""",
    },
    {
        'name': 'NPC Guard (State Machine)',
        'slug': 'npc-guard',
        'event': 'start',
        'description': 'Guard NPC with idle/alert/chase states using StateMachine. Props: alertDist (default 12), chaseDist (default 8), speed (default 3).',
        'code': """
const alertDist = ctx.props.alertDist || 12;
const chaseDist = ctx.props.chaseDist || 8;
const speed = ctx.props.speed || 3;
const origin = {x: ctx.entity.position.x, z: ctx.entity.position.z};

ctx.state.sm = new ctx.StateMachine([
    {
        name: 'idle',
        onUpdate: (dt) => {
            ctx.entity.rotation.y += 0.3 * dt;
        },
        edges: [{
            condition: () => ctx.distToPlayer() < alertDist,
            target: 'alert',
        }],
    },
    {
        name: 'alert',
        onEnter: () => { ctx.events.emit('guard_alert', {entityId: ctx.entityId}); },
        onUpdate: (dt) => {
            const dx = ctx.player.position.x - ctx.entity.position.x;
            const dz = ctx.player.position.z - ctx.entity.position.z;
            ctx.entity.rotation.y = Math.atan2(dx, dz);
        },
        edges: [
            {condition: () => ctx.distToPlayer() < chaseDist, target: 'chase'},
            {condition: () => ctx.distToPlayer() > alertDist * 1.5, target: 'idle'},
        ],
    },
    {
        name: 'chase',
        onUpdate: (dt) => {
            const dx = ctx.player.position.x - ctx.entity.position.x;
            const dz = ctx.player.position.z - ctx.entity.position.z;
            const d = Math.sqrt(dx*dx + dz*dz);
            if (d > 2) {
                const step = speed * dt;
                ctx.entity.position.x += (dx / d) * step;
                ctx.entity.position.z += (dz / d) * step;
            }
            ctx.entity.rotation.y = Math.atan2(dx, dz);
        },
        edges: [{
            condition: () => ctx.distToPlayer() > alertDist * 2,
            target: 'return',
        }],
    },
    {
        name: 'return',
        onUpdate: (dt) => {
            const dx = origin.x - ctx.entity.position.x;
            const dz = origin.z - ctx.entity.position.z;
            const d = Math.sqrt(dx*dx + dz*dz);
            if (d > 0.5) {
                const step = speed * 0.7 * dt;
                ctx.entity.position.x += (dx / d) * step;
                ctx.entity.position.z += (dz / d) * step;
                ctx.entity.rotation.y = Math.atan2(dx, dz);
            }
        },
        edges: [{
            condition: () => {
                const dx = origin.x - ctx.entity.position.x;
                const dz = origin.z - ctx.entity.position.z;
                return Math.sqrt(dx*dx + dz*dz) < 1;
            },
            target: 'idle',
        }],
    },
], 'idle');
""",
    },
    {
        'name': 'NPC Guard Update',
        'slug': 'npc-guard-update',
        'event': 'update',
        'description': 'Drives the NPC Guard state machine each frame. Attach alongside "NPC Guard (State Machine)".',
        'code': """
if (ctx.state.sm) ctx.state.sm.update(ctx.deltaTime);
""",
    },
    {
        'name': 'Look At Player',
        'slug': 'look-at-player',
        'event': 'update',
        'description': 'Smoothly rotate to face the player. Props: speed (default 3).',
        'code': """
const speed = ctx.props.speed || 3;
const dx = ctx.camera.position.x - ctx.entity.position.x;
const dz = ctx.camera.position.z - ctx.entity.position.z;
const targetAngle = Math.atan2(dx, dz);
let current = ctx.entity.rotation.y;
let diff = targetAngle - current;
while (diff > Math.PI) diff -= Math.PI * 2;
while (diff < -Math.PI) diff += Math.PI * 2;
ctx.entity.rotation.y += diff * Math.min(1, speed * ctx.deltaTime);
""",
    },
    {
        'name': 'Hover Sinusoidal',
        'slug': 'hover-sinusoidal',
        'event': 'update',
        'description': 'Hover up and down with sinusoidal motion. Props: amplitude (default 0.5), frequency (default 1).',
        'code': """
if (!ctx.state.baseY) ctx.state.baseY = ctx.entity.position.y;
const amp = ctx.props.amplitude || 0.5;
const freq = ctx.props.frequency || 1;
ctx.entity.position.y = ctx.state.baseY + Math.sin(ctx.elapsed * freq * Math.PI * 2) * amp;
""",
    },
    {
        'name': 'Spin On Interact',
        'slug': 'spin-on-interact',
        'event': 'update',
        'description': 'Spin rapidly when player is nearby, slow down when far. Props: nearDist (default 5), spinSpeed (default 8).',
        'code': """
const nearDist = ctx.props.nearDist || 5;
const spinSpeed = ctx.props.spinSpeed || 8;
const dx = ctx.camera.position.x - ctx.entity.position.x;
const dz = ctx.camera.position.z - ctx.entity.position.z;
const dist = Math.sqrt(dx*dx + dz*dz);
const factor = dist < nearDist ? 1 : Math.max(0, 1 - (dist - nearDist) / 10);
ctx.entity.rotation.y += spinSpeed * factor * ctx.deltaTime;
""",
    },
    {
        'name': 'Scale Pulse',
        'slug': 'scale-pulse',
        'event': 'update',
        'description': 'Gently pulse scale. Props: minScale (default 0.9), maxScale (default 1.1), speed (default 2).',
        'code': """
const lo = ctx.props.minScale || 0.9;
const hi = ctx.props.maxScale || 1.1;
const speed = ctx.props.speed || 2;
const t = (Math.sin(ctx.elapsed * speed) + 1) / 2;
const s = lo + (hi - lo) * t;
ctx.entity.scale.set(s, s, s);
""",
    },
    {
        'name': 'Color Shift',
        'slug': 'color-shift',
        'event': 'update',
        'description': 'Cycle hue over time. Props: speed (default 0.5).',
        'code': """
const speed = ctx.props.speed || 0.5;
if (ctx.entity.material) {
    const hue = (ctx.elapsed * speed) % 1;
    ctx.entity.material.color.setHSL(hue, 0.7, 0.5);
}
""",
    },
]

# World presets: bundled environment + audio templates.
# Audio URLs stream from archive.org (CC0 / public domain).
WORLD_PRESETS = [
    {
        'name': 'Forest',
        'slug': 'forest',
        'description': 'Dense woodland with birdsong and rustling leaves.',
        'skybox': 'hdri',
        'hdri_asset': 'forest_slope',
        'sky_color': '#6b8f71',
        'ground_color': '#2d4a1e',
        'fog_color': '#4a6741',
        'fog_near': 20.0,
        'fog_far': 120.0,
        'ambient_light': 0.3,
        'ambient_audio_url': 'https://archive.org/download/naturesounds-soundtheraphy/Relaxing%20Nature%20Sounds%20-%20Birdsong%20Sound.mp3',
        'ambient_volume': 0.5,
    },
    {
        'name': 'Cafe',
        'slug': 'cafe',
        'description': 'Warm indoor cafe with conversation murmur and clinking cups.',
        'skybox': 'color',
        'hdri_asset': '',
        'sky_color': '#2a1f14',
        'ground_color': '#5c4033',
        'fog_color': '#3d2b1f',
        'fog_near': 15.0,
        'fog_far': 50.0,
        'ambient_light': 0.5,
        'ambient_audio_url': 'https://archive.org/download/coffee-shop-sounds-12/Coffee%20Shop%20Sounds%2016.mp3',
        'ambient_volume': 0.35,
    },
    {
        'name': 'City Street',
        'slug': 'city-street',
        'description': 'Busy urban street with traffic, pedestrians, and distant sirens.',
        'skybox': 'hdri',
        'hdri_asset': 'potsdamer_platz',
        'sky_color': '#8a9bae',
        'ground_color': '#4a4a4a',
        'fog_color': '#7a8a9a',
        'fog_near': 40.0,
        'fog_far': 200.0,
        'ambient_light': 0.5,
        'ambient_audio_url': 'https://archive.org/download/longambients2/City%20Streets.mp3',
        'ambient_volume': 0.4,
    },
    {
        'name': 'Rainy Scene',
        'slug': 'rainy',
        'description': 'Overcast sky with steady rain and distant thunder.',
        'skybox': 'color',
        'hdri_asset': '',
        'sky_color': '#4a5568',
        'ground_color': '#2d3748',
        'fog_color': '#5a6577',
        'fog_near': 15.0,
        'fog_far': 80.0,
        'ambient_light': 0.25,
        'ambient_audio_url': 'https://archive.org/download/longambients2/Heavy%20Rain.mp3',
        'ambient_volume': 0.5,
    },
    {
        'name': 'Winter Scene',
        'slug': 'winter',
        'description': 'Snowy landscape with wind and crunching snow underfoot.',
        'skybox': 'hdri',
        'hdri_asset': 'snowy_park_01',
        'sky_color': '#c8d8e8',
        'ground_color': '#e8e8f0',
        'fog_color': '#d0dce8',
        'fog_near': 30.0,
        'fog_far': 150.0,
        'ambient_light': 0.6,
        'ambient_audio_url': 'https://archive.org/download/wind-free-sound-effect-download/Wind%20Free%20Sound%20Effect%20Download.mp3',
        'ambient_volume': 0.35,
    },
    {
        'name': 'Beach',
        'slug': 'beach',
        'description': 'Sandy shore with ocean waves, seagulls, and gentle breeze.',
        'skybox': 'hdri',
        'hdri_asset': 'kloofendal_48d_partly_cloudy',
        'sky_color': '#87CEEB',
        'ground_color': '#c2b280',
        'fog_color': '#a8c8e0',
        'fog_near': 60.0,
        'fog_far': 300.0,
        'ambient_light': 0.6,
        'ambient_audio_url': 'https://archive.org/download/longambients2/Distant%20Ocean%20Surf.mp3',
        'ambient_volume': 0.45,
    },
    {
        'name': 'Night',
        'slug': 'night',
        'description': 'Dark nighttime scene with crickets and ambient stillness.',
        'skybox': 'color',
        'hdri_asset': '',
        'sky_color': '#0a0a1a',
        'ground_color': '#1a1a2e',
        'fog_color': '#0d0d1f',
        'fog_near': 10.0,
        'fog_far': 60.0,
        'ambient_light': 0.1,
        'ambient_audio_url': 'https://archive.org/download/longambients2/Evening%20Crickets.mp3',
        'ambient_volume': 0.4,
    },
    {
        'name': 'Space Station',
        'slug': 'space-station',
        'description': 'Sci-fi interior with mechanical hum and electronic ambience.',
        'skybox': 'color',
        'hdri_asset': '',
        'sky_color': '#0a0a0a',
        'ground_color': '#1a1a2a',
        'fog_color': '#0d0d1a',
        'fog_near': 20.0,
        'fog_far': 100.0,
        'ambient_light': 0.3,
        'ambient_audio_url': 'https://archive.org/download/SSE_Library_SCIFI/COMPUTER/SCICmpt_Star%20Trek%20like%20scifi%20computer%3B%20loopable_CS_USC.mp3',
        'ambient_volume': 0.3,
    },
]


class Command(BaseCommand):
    help = 'Import 3D objects into the Aether library from external sources'

    def add_arguments(self, parser):
        parser.add_argument('--source', choices=['sketchfab', 'polyhaven'],
                            help='Source repository')
        parser.add_argument('--query', help='Search query (e.g. "chair")')
        parser.add_argument('--uid', help='Import specific model by UID')
        parser.add_argument('--type', help='Asset type filter (e.g. hdri)')
        parser.add_argument('--count', type=int, default=24,
                            help='Max results per query (default 24)')
        parser.add_argument('--seed-categories', action='store_true',
                            help='Seed default object categories')
        parser.add_argument('--seed-scripts', action='store_true',
                            help='Seed built-in NPC scripts')
        parser.add_argument('--seed-presets', action='store_true',
                            help='Seed world presets (forest, cafe, etc.)')

    def handle(self, **options):
        if options['seed_categories']:
            self._seed_categories()
        if options['seed_scripts']:
            self._seed_scripts()
        if options['seed_presets']:
            self._seed_presets()
        if options['source'] == 'sketchfab':
            if options['uid']:
                self._import_sketchfab_model(options['uid'])
            elif options['query']:
                self._search_sketchfab(options['query'], options['count'])
            else:
                self.stderr.write('Sketchfab requires --query or --uid')
        elif options['source'] == 'polyhaven':
            self._import_polyhaven(options.get('type') or 'hdris')

    def _seed_categories(self):
        created = 0
        for parent_name, children in DEFAULT_CATEGORIES:
            parent, _ = ObjectCategory.objects.get_or_create(
                slug=parent_name.lower().replace(' ', '-'),
                defaults={'name': parent_name},
            )
            for child_name in children:
                _, was_created = ObjectCategory.objects.get_or_create(
                    slug=f'{parent.slug}-{child_name.lower().replace(" ", "-")}',
                    defaults={'name': child_name, 'parent': parent},
                )
                if was_created:
                    created += 1
        self.stdout.write(f'Seeded {created} new categories')

    def _seed_scripts(self):
        created = 0
        for data in BUILTIN_SCRIPTS:
            _, was_created = Script.objects.update_or_create(
                slug=data['slug'],
                defaults={
                    'name': data['name'],
                    'description': data['description'],
                    'code': data['code'].strip(),
                    'event': data['event'],
                    'is_builtin': True,
                },
            )
            if was_created:
                created += 1
        self.stdout.write(f'Seeded {len(BUILTIN_SCRIPTS)} built-in scripts '
                          f'({created} new)')

    def _seed_presets(self):
        created = 0
        for data in WORLD_PRESETS:
            _, was_created = WorldPreset.objects.update_or_create(
                slug=data['slug'],
                defaults={k: v for k, v in data.items() if k != 'slug'},
            )
            if was_created:
                created += 1
        self.stdout.write(f'Seeded {len(WORLD_PRESETS)} world presets '
                          f'({created} new)')

    def _sketchfab_headers(self):
        token = os.environ.get('SKETCHFAB_API_TOKEN', '')
        headers = {'User-Agent': 'Velour-Aether/1.0'}
        if token:
            headers['Authorization'] = f'Token {token}'
        return headers

    def _search_sketchfab(self, query, count):
        url = (f'{SKETCHFAB_API}/models'
               f'?q={query}&downloadable=true&count={count}'
               f'&sort_by=-likeCount')
        req = Request(url, headers=self._sketchfab_headers())
        try:
            resp = urlopen(req, timeout=15)
            data = json.loads(resp.read())
        except (HTTPError, Exception) as e:
            self.stderr.write(f'Sketchfab API error: {e}')
            return

        results = data.get('results', [])
        imported = 0
        for model in results:
            uid = model.get('uid', '')
            if not uid:
                continue
            if LibraryObject.objects.filter(source='sketchfab',
                                            source_uid=uid).exists():
                continue

            # Extract thumbnail
            thumbs = model.get('thumbnails', {}).get('images', [])
            thumb_url = ''
            for t in thumbs:
                if t.get('width', 0) >= 200:
                    thumb_url = t.get('url', '')
                    break

            # License mapping
            license_data = model.get('license', {})
            license_slug = license_data.get('slug', '') if license_data else ''
            license_map = {
                'cc0': 'cc0', 'cc-by-4.0': 'cc-by',
                'cc-by-sa-4.0': 'cc-by-sa', 'cc-by-nc-4.0': 'cc-by-nc',
                'cc-by-nc-sa-4.0': 'cc-by-nc',
            }
            license_code = license_map.get(license_slug, 'unknown')

            tags = model.get('tags', [])
            tag_names = [t.get('name', '') for t in tags if t.get('name')]

            LibraryObject.objects.create(
                name=model.get('name', 'Unnamed'),
                description=model.get('description', '')[:500],
                source='sketchfab',
                source_uid=uid,
                source_url=model.get('viewerUrl', ''),
                license=license_code,
                author=model.get('user', {}).get('displayName', ''),
                thumbnail=thumb_url,
                poly_count=model.get('faceCount', 0) or 0,
                tags=', '.join(tag_names[:20]),
            )
            imported += 1

        self.stdout.write(f'Imported {imported} models from Sketchfab '
                          f'(query: "{query}")')

    def _import_sketchfab_model(self, uid):
        if LibraryObject.objects.filter(source='sketchfab',
                                        source_uid=uid).exists():
            self.stdout.write(f'Model {uid} already in library')
            return

        url = f'{SKETCHFAB_API}/models/{uid}'
        req = Request(url, headers=self._sketchfab_headers())
        try:
            resp = urlopen(req, timeout=15)
            model = json.loads(resp.read())
        except (HTTPError, Exception) as e:
            self.stderr.write(f'Sketchfab API error: {e}')
            return

        thumbs = model.get('thumbnails', {}).get('images', [])
        thumb_url = ''
        for t in thumbs:
            if t.get('width', 0) >= 200:
                thumb_url = t.get('url', '')
                break

        LibraryObject.objects.create(
            name=model.get('name', 'Unnamed'),
            description=model.get('description', '')[:500],
            source='sketchfab',
            source_uid=uid,
            source_url=model.get('viewerUrl', ''),
            license='unknown',
            author=model.get('user', {}).get('displayName', ''),
            thumbnail=thumb_url,
            poly_count=model.get('faceCount', 0) or 0,
            tags=', '.join(
                t.get('name', '') for t in model.get('tags', [])
                if t.get('name')
            ),
        )
        self.stdout.write(f'Imported model: {model.get("name")}')

    def _import_polyhaven(self, asset_type):
        """Import assets from Poly Haven (CC0, no auth needed)."""
        url = f'{POLYHAVEN_API}/assets?t={asset_type}'
        req = Request(url, headers={'User-Agent': 'Velour-Aether/1.0'})
        try:
            resp = urlopen(req, timeout=15)
            data = json.loads(resp.read())
        except (HTTPError, Exception) as e:
            self.stderr.write(f'Poly Haven API error: {e}')
            return

        imported = 0
        for slug, info in data.items():
            if LibraryObject.objects.filter(source='polyhaven',
                                            source_uid=slug).exists():
                continue

            tags = info.get('tags', [])
            categories = info.get('categories', [])

            LibraryObject.objects.create(
                name=info.get('name', slug),
                source='polyhaven',
                source_uid=slug,
                source_url=f'https://polyhaven.com/a/{slug}',
                license='cc0',
                author=', '.join(info.get('authors', {}).keys()),
                thumbnail=f'https://cdn.polyhaven.com/asset_img/thumbs/{slug}.png?width=256',
                tags=', '.join(tags + categories),
            )
            imported += 1

        self.stdout.write(f'Imported {imported} assets from Poly Haven '
                          f'(type: {asset_type})')
