"""Generate a MegaCity — 16 small cafe districts merged into one Aether
world in a 4x4 grid, under a single HDRI, with a music track and
"rain-possible" weather that cycles on and off during play.

Each cell reuses the cafe-shell walls/counter/tables and gets 3 NPCs
with Grammar Engine languages + Face Forge avatars. Cells are spaced
30m apart so their footprints never overlap.

Run: ``venv/bin/python manage.py seed_megacity``
"""

import math
import random
import secrets

from django.core.management.base import BaseCommand

from aether.models import Entity, EntityScript, SavedFace, Script, World
from grammar_engine.models import Language

from aether.management.commands.seed_cafe_variants import (
    _ent, CAFE_TABLES, SKINS, SHIRTS, PANTS, SHOES, HAIRS, EYES, BUILDS,
    get_script,
)
from aether.management.commands.seed_velour_in_my_city import (
    _ensure_language, _make_npc,
    TOURIST_LANG_SLUG, DIASPORA_LANG_SLUG,
)


# Internet Archive / stream music picks. Cafe jazz radio + a handful of
# long ambients already used elsewhere in Velour. Extend this list with
# other Internet Archive items (search:
# https://archive.org/search?query=subject%3A%22jazz%22+collection%3Aamericanstories)
MUSIC_POOL = [
    'https://stream.zeno.fm/0r0xa792kwzuv',  # Cafe ambient jazz radio
    'https://archive.org/download/coffee-shop-sounds-12/Coffee%20Shop%20Sounds%2016.mp3',
    'https://archive.org/download/longambients2/City%20Streets.mp3',
]


# 16 cell palettes — recycled from the Velour in My City palette pool so
# each cell reads as a small district with a coherent warm/cool/neutral
# identity.
CELL_THEMES = [
    {'walls': '#8b7355', 'floor': '#6b4226', 'counter': '#5c3317', 'top': '#d2b48c', 'local': 'Boulevardese'},
    {'walls': '#9eb3c7', 'floor': '#6b6e7a', 'counter': '#4a5665', 'top': '#cbd5e0', 'local': 'Riversidish'},
    {'walls': '#4a5a38', 'floor': '#3a4228', 'counter': '#2f3820', 'top': '#9ab07a', 'local': 'Canopic'},
    {'walls': '#4a4a5a', 'floor': '#3a3a40', 'counter': '#2a2a30', 'top': '#808090', 'local': 'Midtownese'},
    {'walls': '#d0dce6', 'floor': '#aab8c2', 'counter': '#7a8c99', 'top': '#f0f8ff', 'local': 'Frostspeak'},
    {'walls': '#6b7a8a', 'floor': '#5a656e', 'counter': '#3a4552', 'top': '#b0c4cf', 'local': 'Harborspeak'},
    {'walls': '#d4a76a', 'floor': '#b88a50', 'counter': '#8b5a2b', 'top': '#f4d7a0', 'local': 'Duneglot'},
    {'walls': '#2a1e3a', 'floor': '#15102a', 'counter': '#0a0818', 'top': '#7a6ad4', 'local': 'Noktaru'},
    {'walls': '#4a6a48', 'floor': '#3a4a38', 'counter': '#5a7a28', 'top': '#a4c890', 'local': 'Floralese'},
    {'walls': '#6a5a4a', 'floor': '#4a3a2a', 'counter': '#3a2a1a', 'top': '#c2a888', 'local': 'Piernese'},
    {'walls': '#b86848', 'floor': '#8a4a2a', 'counter': '#6a2e1a', 'top': '#f4a060', 'local': 'Goldvoice'},
    {'walls': '#5a6870', 'floor': '#3a4248', 'counter': '#20282a', 'top': '#a0b4bc', 'local': 'Puddletongue'},
    {'walls': '#1a1a3a', 'floor': '#0a0a20', 'counter': '#14142a', 'top': '#6a78c4', 'local': 'Starlingua'},
    {'walls': '#6a3a28', 'floor': '#3a2418', 'counter': '#2a1810', 'top': '#c48658', 'local': 'Ironcant'},
    {'walls': '#3a8a5a', 'floor': '#c09868', 'counter': '#8a5a2a', 'top': '#f0d48c', 'local': 'Isletalk'},
    {'walls': '#c8d8c0', 'floor': '#94a888', 'counter': '#607a58', 'top': '#e4f0dc', 'local': 'Atriomatic'},
]


CELL_NAMES = [
    'Boulevard', 'Riverside', 'Canopy', 'Midtown',
    'Frostgate', 'Harbor', 'Dune', 'Nocturne',
    'Floral', 'Pier', 'Goldcoast', 'Puddlewick',
    'Starlit', 'Iron', 'Isle', 'Atrium',
]

NPC_POOL = [
    'Mae', 'Otis', 'June', 'Hank', 'Eli', 'Anya', 'Roos', 'Teo',
    'Saki', 'Nyla', 'Bram', 'Odette', 'Finn', 'Lior', 'Rana', 'Oskar',
    'Magnolia', 'Hiro', 'Ines', 'Zuzu', 'Kwame', 'Marco', 'Ava', 'Sam',
    'Kenji', 'Liu', 'Rosa', 'Dante', 'Yara', 'Benny', 'Cleo', 'Felix',
    'Priya', 'Noor', 'Theo', 'Beatrix', 'Jules', 'Ramona', 'Ziggy',
    'Solenne', 'Rin', 'Bodhi', 'Gertrude', 'Luc', 'Tamsin', 'Nyx',
    'Ottilie', 'Basil',
]


def _build_cell(world, entities, npc_ents, attachments, ox, oz,
                theme, humanoid, face_anim, wander, greet,
                local_slug, diaspora_slug, tourist_slug,
                face_pks, npc_names, rng):
    """Stamp one cafe cell at the given world-space offset.

    Mirrors build_cafe_shell but threads ``ox``/``oz`` through every
    position so 16 cells can live in one world without overlapping.
    """
    E = lambda *a, **k: entities.append(_ent(world, *a, **k))
    wall_color = theme['walls']
    floor_color = theme['floor']
    counter_color = theme['counter']
    top_color = theme['top']

    E('Cafe Floor', 'box', floor_color, ox, -0.05, oz - 2,
      sx=18, sy=0.1, sz=16, shadow=False)
    # Leave the back/right/left walls off for the MegaCity — a single
    # enclosing set of walls would make 16 cells feel like a maze.  The
    # counter, kitchen, and door anchor the cell visually instead.
    E('Counter', 'box', counter_color, ox, 0.55, oz - 6,
      sx=6, sy=1.1, sz=0.8)
    E('Counter Top', 'box', top_color, ox, 1.12, oz - 6,
      sx=6.1, sy=0.04, sz=0.9)
    E('Kitchen Counter', 'box', '#696969', ox, 0.45, oz - 9,
      sx=4, sy=0.9, sz=0.6)
    E('Coffee Machine', 'box', '#1a1a1a', ox - 1.5, 1.35, oz - 6,
      sx=0.5, sy=0.6, sz=0.4)
    E('Cash Register', 'box', '#2a2a2a', ox + 1.5, 1.25, oz - 6,
      sx=0.4, sy=0.3, sz=0.3)

    # Door at the plaza-facing side. Skip the "front" door for MegaCity
    # cells — walking across cell boundaries is the intended traversal.
    # Tables: reuse CAFE_TABLES but only keep the two 4-seaters (for a
    # sparse look; 16 cells already add up to a dense scene).
    table_positions = []
    for i, (tx, tz, seats) in enumerate(CAFE_TABLES):
        if seats != 4:
            continue
        ax, az = ox + tx, oz + tz
        table_positions.append((ax, az))
        E(f'Table', 'cylinder', counter_color, ax, 0.38, az,
          sx=0.9, sy=0.76, sz=0.9)
        E(f'Tabletop', 'cylinder', top_color, ax, 0.77, az,
          sx=1.0, sy=0.04, sz=1.0, shadow=False)
        for (cx, cz) in [(-0.6, -0.5), (0.6, -0.5), (-0.6, 0.5), (0.6, 0.5)]:
            E(f'Chair', 'box', '#8b6914', ax + cx, 0.28, az + cz,
              sx=0.4, sy=0.06, sz=0.4)

    # A soft overhead "marker" sphere so you can see cells from a
    # distance under fog — tinted to the cell's top colour.
    E(f'Beacon', 'sphere', top_color, ox, 4.0, oz,
      sx=0.25, sy=0.25, sz=0.25, shadow=False,
      behavior='bob', speed=0.4)

    # --- 3 NPCs per cell (waiter + 2 patrons). ---
    local = local_slug
    langs = [local, local, rng.choice([diaspora_slug, tourist_slug])]
    npc_positions = [
        (ox, oz - 5, 0),                    # waiter
        (ox + CAFE_TABLES[3][0] - 0.6,      # seated near first 4-seat table
         oz + CAFE_TABLES[3][1] - 0.5, 0),
        (ox + CAFE_TABLES[4][0] + 0.6,      # seated at second 4-seat table
         oz + CAFE_TABLES[4][1] - 0.5, 0),
    ]
    for j, ((nx, nz, ry), lang) in enumerate(zip(npc_positions, langs)):
        name = npc_names[j] if j < len(npc_names) else f'NPC'
        e = _make_npc(world, name, nx, nz, ry=ry)
        if face_pks[j] is not None:
            e.face_id = face_pks[j]
        e.language_slug = lang
        e.save()
        npc_ents.append(e)

        build = BUILDS[j % len(BUILDS)]
        attachments.append(EntityScript(entity=e, script=humanoid, props={
            'skin':  SKINS[j % len(SKINS)],
            'shirt': SHIRTS[j % len(SHIRTS)],
            'pants': PANTS[j % len(PANTS)],
            'shoes': SHOES[j % len(SHOES)],
            'hair':  HAIRS[j % len(HAIRS)],
            'eyes':  EYES[j % len(EYES)],
            'shoulderW': build[0], 'hipW': build[1],
            'heightScale': build[2],
        }))
        attachments.append(EntityScript(
            entity=e, script=face_anim, props={}))
        if wander:
            attachments.append(EntityScript(
                entity=e, script=wander, props={
                    'bounds': [nx - 1.5, nz - 1.5, nx + 1.5, nz + 1.5],
                    'speed': round(0.5 + rng.random() * 0.3, 2),
                }))
        if greet:
            attachments.append(EntityScript(
                entity=e, script=greet, props={
                    'greeting': rng.choice([
                        'Welcome to the city.',
                        'Just cross the square if you like.',
                        'Rain again tomorrow, maybe.',
                        'Pull up a chair.',
                    ]),
                }))


class Command(BaseCommand):
    help = 'Generate MegaCity — 16 cafe districts merged into one Aether world.'

    def add_arguments(self, parser):
        parser.add_argument(
            '--hdri', default='potsdamer_platz',
            help='Poly Haven HDRI name shared by all 16 cells.')
        parser.add_argument(
            '--music', default='',
            help='Override the ambient music URL (default: random pick).')

    def handle(self, *args, **options):
        humanoid = get_script('humanoid-builder')
        wander = get_script('wander-articulated')
        greet = get_script('npc-greet')
        face_anim = Script.objects.filter(slug='face-animator').first()

        if not humanoid or not face_anim:
            self.stderr.write(self.style.ERROR(
                'Run seed_cafe_hdri first — humanoid-builder / face-animator '
                'scripts missing.'))
            return
        if SavedFace.objects.count() == 0:
            self.stderr.write(self.style.ERROR(
                'No SavedFace rows — breed some at /aether/faces/ first.'))
            return

        hdri = options['hdri']
        music = options['music'] or random.choice(MUSIC_POOL)

        # Allow multiple MegaCities to exist side by side — find the next
        # free slug rather than counting (count is wrong if some have been
        # deleted or if a half-built one already squats on the base name).
        slug = 'megacity'
        n = 1
        while World.objects.filter(slug=slug).exists():
            n += 1
            slug = f'megacity-{n}'
        existing = n - 1

        tourist_lang, _ = _ensure_language(
            TOURIST_LANG_SLUG, 'Tourist Creole', '')
        diaspora_lang, _ = _ensure_language(
            DIASPORA_LANG_SLUG, 'Diaspora Common', '')

        world = World.objects.create(
            title='MegaCity' if existing == 0 else f'MegaCity {existing + 1}',
            slug=slug,
            description='16 cafe districts merged into one city. Music plays; '
                        'walk a few blocks and it may start raining.',
            skybox='hdri', hdri_asset=hdri,
            sky_color='#cdd6e0', ground_color='#2a2a30',
            ground_size=200.0, ambient_light=0.4,
            fog_near=45.0, fog_far=150.0, fog_color='#8a92a0',
            gravity=-9.81,
            spawn_x=0, spawn_y=1.6, spawn_z=0,
            soundscape='rain-possible', ambient_volume=0.4,
            ambient_audio_url=music,
            published=True, featured=True,
        )

        # Ensure per-cell Language rows exist.
        local_slugs = []
        for theme in CELL_THEMES:
            ls = f'megacity-{theme["local"].lower()}'
            _ensure_language(ls, f'MegaCity {theme["local"]}',
                             'MegaCity cell tongue.')
            local_slugs.append(ls)

        entities = []
        npc_ents = []
        attachments = []

        # Single-slab ground that spans all cells so there's no gap
        # walking between them.
        entities.append(_ent(
            world, 'MegaCity Ground', 'box', '#22262e',
            0, -0.1, 0, sx=160, sy=0.1, sz=160, shadow=False))

        rng = random.Random('megacity-seed')

        # Pre-pick 48 faces (3 per cell × 16 cells).
        face_pks_all = list(SavedFace.objects
                            .order_by('?')
                            .values_list('pk', flat=True)[:48])
        # Pre-pick 48 unique NPC names.
        name_pool = rng.sample(NPC_POOL, min(48, len(NPC_POOL)))

        SPACING = 30.0
        GRID = 4
        for cell_i in range(GRID * GRID):
            row = cell_i // GRID
            col = cell_i % GRID
            ox = (col - (GRID - 1) / 2.0) * SPACING
            oz = (row - (GRID - 1) / 2.0) * SPACING
            theme = CELL_THEMES[cell_i]
            local_slug = local_slugs[cell_i]

            cell_faces = (
                (face_pks_all[cell_i * 3:cell_i * 3 + 3] + [None, None, None])[:3]
            )
            cell_names = name_pool[cell_i * 3:cell_i * 3 + 3]
            if len(cell_names) < 3:
                cell_names += [f'Patron {cell_i}-{k}' for k in range(3)]

            _build_cell(
                world, entities, npc_ents, attachments, ox, oz, theme,
                humanoid, face_anim, wander, greet,
                local_slug, diaspora_lang.slug, tourist_lang.slug,
                cell_faces, cell_names, rng,
            )

        Entity.objects.bulk_create(entities)
        EntityScript.objects.bulk_create(attachments)

        total = Entity.objects.filter(world=world).count()
        self.stdout.write(self.style.SUCCESS(
            f'{world.title}: {total} entities, {len(npc_ents)} NPCs, '
            f'16 cells, HDRI={hdri}, music={music[:50]}…, '
            f'soundscape=rain-possible.'))
        self.stdout.write(self.style.SUCCESS(
            f'Enter at /aether/{world.slug}/enter/'))
        self._world = world
