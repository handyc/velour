"""Seed ten "doored district" Aether worlds for testing the door-teleport
feature end to end.

Each world is a small outdoor plaza ringed by procedural buildings, each
with a Door entity at its plaza-facing side. Walking into any door lands
the player in a random published Aether world.

Per world:
  - HDRI background (rotated per-district)
  - 8 procedural buildings in a ring of radius 12
  - 8 Door entities (name starts with "Door") at radius 8 on the same
    bearing, positioned for a natural walk-in approach
  - 6 NPCs, each with a SavedFace FK, a Grammar Engine language_slug,
    humanoid-builder + face-animator + wander scripts
  - 10 L-system plants scattered around the plaza

Run: ``venv/bin/python manage.py seed_aether_districts``
"""

import math
import secrets

from django.core.management.base import BaseCommand

from aether.models import Entity, EntityScript, SavedFace, Script, World
from grammar_engine.models import Language

from aether.management.commands.seed_cafe_variants import (
    _ent, SKINS, SHIRTS, PANTS, SHOES, HAIRS, EYES, BUILDS, get_script,
)
from aether.management.commands.seed_velour_in_my_city import (
    _ensure_language, _make_npc,
    TOURIST_LANG_SLUG, DIASPORA_LANG_SLUG,
)


DISTRICTS = [
    {
        'n': 1, 'slug': 'aether-district-cobblers-row',
        'title': 'District 1 — Cobbler\'s Row',
        'desc': 'Workshops, awnings, the smell of leather and oil.',
        'hdri': 'brown_photostudio_02',
        'sky': '#c8a880', 'ground': '#5a4030', 'fog': '#a08868',
        'local': 'Cobblish', 'palette': 'warm',
    },
    {
        'n': 2, 'slug': 'aether-district-emerald-heights',
        'title': 'District 2 — Emerald Heights',
        'desc': 'Hillside of hedged gardens and bright little doors.',
        'hdri': 'forest_slope',
        'sky': '#88b490', 'ground': '#4a6a38', 'fog': '#8ca898',
        'local': 'Leafspeak', 'palette': 'cool',
    },
    {
        'n': 3, 'slug': 'aether-district-silvershore',
        'title': 'District 3 — Silvershore',
        'desc': 'Whitewashed cottages, gulls, a long tide mark.',
        'hdri': 'kloofendal_48d_partly_cloudy',
        'sky': '#bcd6e4', 'ground': '#d8c8a8', 'fog': '#c0d4de',
        'local': 'Tidespeech', 'palette': 'cool',
    },
    {
        'n': 4, 'slug': 'aether-district-scholars-quarter',
        'title': 'District 4 — Scholar\'s Quarter',
        'desc': 'Stone libraries, a bell tower, ivy on every column.',
        'hdri': 'potsdamer_platz',
        'sky': '#6a7082', 'ground': '#4a4840', 'fog': '#6a6c74',
        'local': 'Glossian', 'palette': 'neutral',
    },
    {
        'n': 5, 'slug': 'aether-district-apothecary-lane',
        'title': 'District 5 — Apothecary Lane',
        'desc': 'Narrow houses, clay pots on every doorstep.',
        'hdri': 'brown_photostudio_02',
        'sky': '#b88050', 'ground': '#6a4020', 'fog': '#a07048',
        'local': 'Herbic', 'palette': 'warm',
    },
    {
        'n': 6, 'slug': 'aether-district-pilgrims-square',
        'title': 'District 6 — Pilgrim\'s Square',
        'desc': 'A chapel plaza with long afternoon shadows.',
        'hdri': 'kloofendal_48d_partly_cloudy',
        'sky': '#d0c4a8', 'ground': '#8a7a5a', 'fog': '#c0b498',
        'local': 'Pilgrimish', 'palette': 'neutral',
    },
    {
        'n': 7, 'slug': 'aether-district-sun-gate',
        'title': 'District 7 — Sun Gate',
        'desc': 'Whitewash over adobe; a dry fountain in the middle.',
        'hdri': 'brown_photostudio_02',
        'sky': '#e0c088', 'ground': '#c09060', 'fog': '#d8b078',
        'local': 'Sunglot', 'palette': 'warm',
    },
    {
        'n': 8, 'slug': 'aether-district-frostbound',
        'title': 'District 8 — Frostbound',
        'desc': 'Stone houses shouldering against the wind.',
        'hdri': 'snowy_park_01',
        'sky': '#d4e0e8', 'ground': '#b8c4cc', 'fog': '#c8d4dc',
        'local': 'Frostbounder', 'palette': 'cool',
    },
    {
        'n': 9, 'slug': 'aether-district-fogbourne',
        'title': 'District 9 — Fogbourne',
        'desc': 'You can\'t see the next house until you\'re inside it.',
        'hdri': 'potsdamer_platz',
        'sky': '#9aa8b0', 'ground': '#5a6068', 'fog': '#8890a0',
        'local': 'Mistglot', 'palette': 'cool',
    },
    {
        'n': 10, 'slug': 'aether-district-wayfarers-end',
        'title': 'District 10 — Wayfarer\'s End',
        'desc': 'The last plaza before the road leaves town for good.',
        'hdri': 'forest_slope',
        'sky': '#a0b098', 'ground': '#50604a', 'fog': '#8ca090',
        'local': 'Wayfarish', 'palette': 'neutral',
    },
]


BUILDING_TYPES = ['house', 'shop', 'church', 'tower', 'warehouse']

PLANT_POOL = [
    ('oak', 1.2), ('oak', 1.0), ('pine', 1.3), ('pine', 1.0),
    ('birch', 0.95), ('willow', 1.1), ('bush', 0.55), ('bush', 0.6),
    ('palm', 1.2), ('bamboo', 1.0),
]

PALETTE_COLORS = {
    'warm': {
        'walls': ['#c8a878', '#d8b080', '#b09060', '#e0c090', '#a07848'],
        'trim':  ['#8a6840', '#6a4820', '#a07858', '#4a3010', '#784820'],
        'roof':  ['#6a3020', '#8a4028', '#4a2010', '#b05030', '#3a1808'],
    },
    'cool': {
        'walls': ['#c8d4dc', '#a0b4c0', '#dae0e4', '#88a0ac', '#b4c0c8'],
        'trim':  ['#687480', '#485460', '#88a0ac', '#384858', '#a0b0bc'],
        'roof':  ['#20304a', '#3a485a', '#506880', '#182a40', '#45607a'],
    },
    'neutral': {
        'walls': ['#c8c0b4', '#a8a090', '#d8d0c4', '#8c857a', '#b8b0a4'],
        'trim':  ['#6a6458', '#4a4438', '#8a8478', '#282418', '#948c80'],
        'roof':  ['#3a3428', '#5a4830', '#6a5438', '#242010', '#483820'],
    },
}


# Roster pattern — 6 NPCs per world. Names rotate so different districts
# feel different but a few anchors persist across worlds.
ANCHOR_NAMES = ['Mae', 'Otis', 'June']
GUEST_POOL = [
    'Hank', 'Eli', 'Anya', 'Roos', 'Teo', 'Saki', 'Nyla',
    'Bram', 'Odette', 'Finn', 'Lior', 'Rana', 'Oskar',
    'Magnolia', 'Hiro', 'Ines', 'Zuzu', 'Kwame',
]


class Command(BaseCommand):
    help = 'Create 10 doored-district worlds for door-teleport testing.'

    def handle(self, *args, **options):
        humanoid = get_script('humanoid-builder')
        wander = get_script('wander-articulated')
        greet = get_script('npc-greet')
        face_anim = Script.objects.filter(slug='face-animator').first()
        building_script = Script.objects.filter(slug='procedural-building').first()
        plant_script = Script.objects.filter(slug='l-system-plant').first()

        missing = [n for n, s in [
            ('humanoid-builder', humanoid),
            ('face-animator', face_anim),
            ('procedural-building', building_script),
            ('l-system-plant', plant_script),
        ] if not s]
        if missing:
            self.stderr.write(self.style.ERROR(
                f'Scripts missing: {missing}. Run seed_cafe_hdri + '
                f'seed_metropolis first.'))
            return
        if SavedFace.objects.count() == 0:
            self.stderr.write(self.style.ERROR(
                'No SavedFace rows — breed some at /aether/faces/ first.'))
            return

        tourist_lang, _ = _ensure_language(
            TOURIST_LANG_SLUG, 'Tourist Creole', '')
        diaspora_lang, _ = _ensure_language(
            DIASPORA_LANG_SLUG, 'Diaspora Common', '')

        for spec in DISTRICTS:
            self._build(
                spec, humanoid, wander, greet, face_anim,
                building_script, plant_script,
                tourist_lang, diaspora_lang,
            )

    # -------------------------------------------------------------------
    def _build(self, spec, humanoid, wander, greet, face_anim,
               building_script, plant_script,
               tourist_lang, diaspora_lang):
        import random as rnd
        rng = rnd.Random(f'aether-district-{spec["n"]}')

        slug = spec['slug']
        World.objects.filter(slug=slug).delete()

        world = World.objects.create(
            title=spec['title'], slug=slug, description=spec['desc'],
            skybox='hdri', hdri_asset=spec['hdri'],
            sky_color=spec['sky'], ground_color=spec['ground'],
            ground_size=40.0, ambient_light=0.4,
            fog_near=25.0, fog_far=60.0, fog_color=spec['fog'],
            gravity=-9.81,
            spawn_x=0, spawn_y=1.6, spawn_z=0,
            soundscape='', ambient_volume=0.25,
            published=True, featured=False,
        )

        local_slug = f'aether-district-{spec["n"]}-{spec["local"].lower()}'
        local_lang, _ = _ensure_language(
            local_slug, spec['local'],
            f'Tongue of {spec["title"]}.')

        entities = []
        E = lambda *a, **k: entities.append(_ent(world, *a, **k))

        # Ground slab — sized to host buildings + plants.
        E('Ground', 'box', spec['ground'], 0, -0.05, 0,
          sx=40, sy=0.1, sz=40, shadow=False)
        # Bulk-create the static dressing so FKs exist before scripted
        # entities are saved on top.
        Entity.objects.bulk_create(entities)

        pal = PALETTE_COLORS[spec['palette']]

        attachments = []

        # --- Buildings arranged in a ring of radius 12. ---
        BUILDING_COUNT = 8
        BUILDING_RADIUS = 12.0
        DOOR_RADIUS = 8.0
        building_types = list(BUILDING_TYPES)
        rng.shuffle(building_types)

        for i in range(BUILDING_COUNT):
            angle = (i / BUILDING_COUNT) * 2 * math.pi
            bx = round(BUILDING_RADIUS * math.cos(angle), 2)
            bz = round(BUILDING_RADIUS * math.sin(angle), 2)
            dx = round(DOOR_RADIUS * math.cos(angle), 2)
            dz = round(DOOR_RADIUS * math.sin(angle), 2)

            btype = building_types[i % len(building_types)]
            floors = rng.choice([1, 2, 2, 3])
            width = rng.choice([5, 6, 7, 8])
            depth = rng.choice([5, 6, 7])
            wall = rng.choice(pal['walls'])
            trim = rng.choice(pal['trim'])
            roof = rng.choice(pal['roof'])
            # Rotate building so its front face aims at the plaza centre.
            face_angle = math.degrees(math.atan2(-bx, -bz))

            b = Entity.objects.create(
                world=world, name=f'Building {i+1} ({btype})',
                primitive='box', primitive_color='#000000',
                pos_x=bx, pos_y=0, pos_z=bz, rot_y=round(face_angle, 1),
                scale_x=1, scale_y=1, scale_z=1,
                cast_shadow=False, receive_shadow=False, behavior='scripted',
            )
            attachments.append(EntityScript(
                entity=b, script=building_script, props={
                    'type': btype, 'floors': floors,
                    'width': width, 'depth': depth,
                    'color': wall, 'trim': trim, 'roof': roof,
                },
            ))

            # Door entity — name MUST start with "Door" so the client-side
            # teleport logic picks it up.
            Entity.objects.create(
                world=world, name=f'Door {i+1}',
                primitive='box', primitive_color='#2a1a10',
                pos_x=dx, pos_y=1.0, pos_z=dz, rot_y=round(face_angle, 1),
                scale_x=1.3, scale_y=2.0, scale_z=0.1,
                cast_shadow=False, receive_shadow=False, behavior='static',
            )

        # --- L-system plants scattered between buildings. ---
        for i in range(10):
            species, scale = rng.choice(PLANT_POOL)
            r = rng.uniform(3.0, BUILDING_RADIUS - 2.0)
            a = rng.uniform(0, 2 * math.pi)
            px = round(r * math.cos(a), 2)
            pz = round(r * math.sin(a), 2)
            p = Entity.objects.create(
                world=world, name=f'Plant {i+1} ({species})',
                primitive='box', primitive_color='#000000',
                pos_x=px, pos_y=0, pos_z=pz,
                scale_x=1, scale_y=1, scale_z=1,
                cast_shadow=False, receive_shadow=False, behavior='scripted',
            )
            attachments.append(EntityScript(
                entity=p, script=plant_script, props={
                    'species': species,
                    'scale': round(scale, 2),
                    'seed': rng.randint(1, 99999),
                },
            ))

        # --- NPCs — 6 per world, placed in the plaza interior. ---
        face_pks = list(SavedFace.objects
                        .order_by('?')
                        .values_list('pk', flat=True)[:6])
        pool = ANCHOR_NAMES + rng.sample(GUEST_POOL, 3)

        # Assign languages: 4 local + 1 diaspora + 1 tourist.
        langs = ([local_slug] * 4 + [diaspora_lang.slug, tourist_lang.slug])
        rng.shuffle(langs)

        npc_ents = []
        for i, name in enumerate(pool):
            # Place NPCs inside the plaza ring — bias positions so nobody
            # spawns right in front of a door.
            a = ((i + 0.5) / len(pool)) * 2 * math.pi + rng.uniform(-0.25, 0.25)
            r = rng.uniform(2.5, 6.5)
            nx = round(r * math.cos(a), 2)
            nz = round(r * math.sin(a), 2)
            e = _make_npc(world, name, nx, nz, ry=rng.uniform(0, 360))
            if i < len(face_pks):
                e.face_id = face_pks[i]
            e.language_slug = langs[i]
            e.save()
            npc_ents.append(e)

            build = BUILDS[i % len(BUILDS)]
            attachments.append(EntityScript(
                entity=e, script=humanoid, props={
                    'skin':  SKINS[(i + spec['n']) % len(SKINS)],
                    'shirt': SHIRTS[(i + spec['n']) % len(SHIRTS)],
                    'pants': PANTS[i % len(PANTS)],
                    'shoes': SHOES[i % len(SHOES)],
                    'hair':  HAIRS[(i + spec['n']) % len(HAIRS)],
                    'eyes':  EYES[i % len(EYES)],
                    'shoulderW': build[0], 'hipW': build[1],
                    'heightScale': build[2],
                },
            ))
            attachments.append(EntityScript(
                entity=e, script=face_anim, props={}))
            if wander:
                attachments.append(EntityScript(
                    entity=e, script=wander, props={
                        'bounds': [nx - 2.0, nz - 2.0, nx + 2.0, nz + 2.0],
                        'speed': round(rng.uniform(0.4, 0.8), 2),
                    }))
            if greet:
                attachments.append(EntityScript(
                    entity=e, script=greet, props={
                        'greeting': rng.choice([
                            f'Welcome to {spec["title"].split("— ")[-1]}.',
                            'Fresh air today.',
                            'Any door you like.',
                            'Try the one on the far side.',
                            'You lost?',
                            'Mind the step.',
                        ]),
                    }))

        EntityScript.objects.bulk_create(attachments)

        total = Entity.objects.filter(world=world).count()
        door_count = Entity.objects.filter(
            world=world, name__startswith='Door ').count()
        self.stdout.write(self.style.SUCCESS(
            f'{spec["title"]}: {total} entities, '
            f'{door_count} doors, {len(npc_ents)} NPCs, '
            f'10 L-system plants.'
        ))
