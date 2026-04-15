"""Seed cities 11-20 of the "Velour in My City" series, this time with
Face Forge faces painted onto each NPC's head.

Reuses the cafe shell, humanoid-builder, animation scripts, Grammar
Engine languages, and roster pattern from seed_velour_in_my_city.  What
is new:

- Every NPC is bound to a random ``SavedFace`` row via ``Entity.face``.
  ``world_scene_json`` already serialises ``faceGenome`` into the scene
  payload; ``humanoid-builder`` already builds a 156° sphere-cap
  billboard in front of the head for that genome; ``face-animator``
  renders the face each frame.  The only thing that was missing was a
  seeder that actually wires all three together.

- Ten fresh city themes (Sunset Strip through Atrium Gardens) with new
  palettes, HDRI choices, and local Grammar Engine languages.

Run: ``venv/bin/python manage.py seed_velour_in_my_city_faces [--ultra]``
"""

import secrets

from django.core.management.base import BaseCommand

from aether.models import Entity, EntityScript, SavedFace, Script, World
from grammar_engine.models import Language

from aether.management.commands.seed_cafe_variants import (
    build_cafe_shell, _ent, CAFE_TABLES,
    SKINS, SHIRTS, PANTS, SHOES, HAIRS, EYES, BUILDS,
    get_script,
)
from aether.management.commands.seed_velour_in_my_city import (
    EXTRAS_POOL, ORIGINAL_SEATED,
    TOURIST_LANG_SLUG, DIASPORA_LANG_SLUG,
    _ensure_language, _make_npc,
)


# ---------------------------------------------------------------------------
# City design — ten more variations, numbered 11-20.
# ---------------------------------------------------------------------------

CITIES = [
    {
        'n': 11, 'title': 'Velour in My City 11 — Sunset Strip',
        'desc': 'West-facing windows, amber on every surface at six o\'clock.',
        'hdri': 'brown_photostudio_02',
        'walls': '#b86848', 'floor': '#8a4a2a', 'counter': '#6a2e1a',
        'top': '#f4a060', 'fog': '#c67a50',
        'local_lang': 'Goldvoice',
        'shirt_tint': ['#e07030', '#c04020', '#f4a060', '#8a3a1a', '#d8704c'],
        'waiter_surname': 'Goldcoast',
    },
    {
        'n': 12, 'title': 'Velour in My City 12 — Silver Lake',
        'desc': 'Rain on the glass, the lake just beyond. Always a fresh pot.',
        'hdri': 'kloofendal_48d_partly_cloudy',
        'walls': '#5a6870', 'floor': '#3a4248', 'counter': '#20282a',
        'top': '#a0b4bc', 'fog': '#6a7a80',
        'local_lang': 'Puddletongue',
        'shirt_tint': ['#3a4852', '#6a7a82', '#94a4ac', '#28343a', '#4a5860'],
        'waiter_surname': 'Driftwell',
    },
    {
        'n': 13, 'title': 'Velour in My City 13 — Observatory',
        'desc': 'Open past midnight; the dome creaks; espresso under Orion.',
        'hdri': 'potsdamer_platz',
        'walls': '#1a1a3a', 'floor': '#0a0a20', 'counter': '#14142a',
        'top': '#6a78c4', 'fog': '#0e0e22',
        'local_lang': 'Starlingua',
        'shirt_tint': ['#2a3a6a', '#4058a0', '#6080c0', '#14204a', '#8aa4e4'],
        'waiter_surname': 'of the Dome',
    },
    {
        'n': 14, 'title': 'Velour in My City 14 — Foundry',
        'desc': 'Brick, rivets, and the low hum of the old smelter next door.',
        'hdri': 'potsdamer_platz',
        'walls': '#6a3a28', 'floor': '#3a2418', 'counter': '#2a1810',
        'top': '#c48658', 'fog': '#4a2a1c',
        'local_lang': 'Ironcant',
        'shirt_tint': ['#6a3a1a', '#8a5228', '#3a2010', '#c07a40', '#4a281a'],
        'waiter_surname': 'Forgeborn',
    },
    {
        'n': 15, 'title': 'Velour in My City 15 — Tropical Isle',
        'desc': 'The ceiling is palm thatch. The sugar bowl runs out by noon.',
        'hdri': 'forest_slope',
        'walls': '#3a8a5a', 'floor': '#c09868', 'counter': '#8a5a2a',
        'top': '#f0d48c', 'fog': '#8ac4a0',
        'local_lang': 'Isletalk',
        'shirt_tint': ['#f09060', '#3aa080', '#f4d470', '#60c8a0', '#d84060'],
        'waiter_surname': 'of the Reef',
    },
    {
        'n': 16, 'title': 'Velour in My City 16 — Capital District',
        'desc': 'Marble floor, brass trim. A government cafe run too seriously.',
        'hdri': 'brown_photostudio_02',
        'walls': '#d8d0c0', 'floor': '#b0a890', 'counter': '#706858',
        'top': '#f0e8d0', 'fog': '#c0b8a8',
        'local_lang': 'Marblespeak',
        'shirt_tint': ['#3a4050', '#505868', '#747c90', '#242a38', '#8a94a8'],
        'waiter_surname': 'of the Ministry',
    },
    {
        'n': 17, 'title': 'Velour in My City 17 — Theater Row',
        'desc': 'Red velvet banquettes. They open an hour before curtain.',
        'hdri': 'potsdamer_platz',
        'walls': '#6a1a28', 'floor': '#3a1018', 'counter': '#20080c',
        'top': '#c48098', 'fog': '#4a1820',
        'local_lang': 'Dramatese',
        'shirt_tint': ['#8a2030', '#c04858', '#6a1028', '#e0748c', '#3a0818'],
        'waiter_surname': 'Red Curtain',
    },
    {
        'n': 18, 'title': 'Velour in My City 18 — Spice Bazaar',
        'desc': 'A cafe fitted into an archway; cardamom comes with the coffee.',
        'hdri': 'brown_photostudio_02',
        'walls': '#b07830', 'floor': '#8a5820', 'counter': '#5a3818',
        'top': '#e8b870', 'fog': '#a07038',
        'local_lang': 'Spiceglot',
        'shirt_tint': ['#c44028', '#e08840', '#8a4820', '#f4c070', '#643818'],
        'waiter_surname': 'Saffron',
    },
    {
        'n': 19, 'title': 'Velour in My City 19 — Highland Crossing',
        'desc': 'A stone cafe at the pass. The mountain owes no one a warm cup.',
        'hdri': 'snowy_park_01',
        'walls': '#8a8478', 'floor': '#5a5448', 'counter': '#403a30',
        'top': '#c8c0b0', 'fog': '#94908a',
        'local_lang': 'Highlandish',
        'shirt_tint': ['#3a4a3a', '#6a5448', '#8a7a68', '#24302a', '#a8a090'],
        'waiter_surname': 'of the Pass',
    },
    {
        'n': 20, 'title': 'Velour in My City 20 — Atrium Gardens',
        'desc': 'Glass roof, living wall, a piano nobody ever plays.',
        'hdri': 'forest_slope',
        'walls': '#c8d8c0', 'floor': '#94a888', 'counter': '#607a58',
        'top': '#e4f0dc', 'fog': '#aac0a0',
        'local_lang': 'Atriomatic',
        'shirt_tint': ['#80a870', '#b4d0a0', '#3a6a3a', '#d4e8c8', '#548a50'],
        'waiter_surname': 'Fernborn',
    },
]


class Command(BaseCommand):
    help = ('Create Velour in My City 11-20 — each NPC wears a Face Forge '
            'face on a curved sphere cap over the head.')

    def add_arguments(self, parser):
        parser.add_argument('--ultra', action='store_true',
                            help='Enable ultra-realistic NPC meshes')

    def handle(self, *args, **options):
        ultra = options.get('ultra', False)

        humanoid = get_script('humanoid-builder')
        waiter_anim = get_script('waiter-articulated')
        seated_anim = get_script('seated-articulated')
        wander_anim = get_script('wander-articulated')
        barista_anim = get_script('barista-articulated')
        greet = get_script('npc-greet')
        face_anim = Script.objects.filter(slug='face-animator').first()

        if not humanoid:
            self.stderr.write(self.style.ERROR(
                'Run seed_cafe_hdri first — humanoid-builder not found.'))
            return
        if not face_anim:
            self.stderr.write(self.style.ERROR(
                'face-animator script missing — run seed_cafe_hdri first.'))
            return
        if SavedFace.objects.count() == 0:
            self.stderr.write(self.style.ERROR(
                'No SavedFace rows — breed some at /aether/faces/ first.'))
            return

        tourist_lang, _ = _ensure_language(
            TOURIST_LANG_SLUG, 'Tourist Creole',
            'Shared tourist voice — every Velour city has a few of these.')
        diaspora_lang, _ = _ensure_language(
            DIASPORA_LANG_SLUG, 'Diaspora Common',
            'Shared minority voice across the Velour series.')

        for spec in CITIES:
            self._build_city(spec, ultra, humanoid, waiter_anim, seated_anim,
                             wander_anim, barista_anim, greet, face_anim,
                             tourist_lang, diaspora_lang)

    # -------------------------------------------------------------------
    def _build_city(self, spec, ultra, humanoid, waiter_anim, seated_anim,
                    wander_anim, barista_anim, greet, face_anim,
                    tourist_lang, diaspora_lang):
        import random as rnd
        rng = rnd.Random(f'velour-city-{spec["n"]}-faces')

        slug = f'velour-in-my-city-{spec["n"]}'
        World.objects.filter(slug=slug).delete()

        world = World.objects.create(
            title=spec['title'],
            slug=slug,
            description=spec['desc'],
            skybox='hdri', hdri_asset=spec['hdri'],
            sky_color=spec['walls'], ground_color=spec['floor'], ground_size=30.0,
            ambient_light=0.35, fog_near=18.0, fog_far=48.0, fog_color=spec['fog'],
            gravity=-9.81, spawn_x=0, spawn_y=1.6, spawn_z=6.0,
            soundscape='cafe', ambient_volume=0.3,
            published=True, featured=False,
        )

        local_slug = f'velour-city-{spec["n"]}-{spec["local_lang"].lower()}'
        local_lang, created = _ensure_language(
            local_slug, spec['local_lang'],
            f'Native tongue of {spec["title"]}.')

        entities = []
        table_pos = build_cafe_shell(
            world, entities,
            wall_color=spec['walls'], floor_color=spec['floor'],
            counter_color=spec['counter'], top_color=spec['top'],
        )

        E = lambda *a, **k: entities.append(_ent(world, *a, **k))
        for lx in [-4, 0, 4]:
            for lz in [-3, 1, 5]:
                E(f'Light {lx},{lz}', 'sphere', spec['top'], lx, 2.8, lz,
                  sx=0.14, sy=0.14, sz=0.14, shadow=False,
                  behavior='bob', speed=0.3)

        Entity.objects.bulk_create(entities)

        pool = EXTRAS_POOL[:]
        rng.shuffle(pool)
        stand_extras = pool[:3]
        new_seated = pool[3:7]

        npc_ents = self._spawn_npcs(
            world, spec, ultra, rng, humanoid,
            waiter_anim, seated_anim, wander_anim, barista_anim,
            greet, face_anim, table_pos, stand_extras, new_seated,
        )

        # ----- Language assignment (same role cluster scheme as 1-10) -----
        LOCAL, DIASP, TOUR = local_slug, diaspora_lang.slug, tourist_lang.slug
        role_lang = {}
        for nm, lang in [
            (f'Marco {spec["waiter_surname"]}', LOCAL),
            ('Ava', LOCAL), ('Sam', DIASP),
            ('Kenji', DIASP), ('Liu', LOCAL),
            ('Rosa', LOCAL), ('Dante', DIASP),
            ('Yara', LOCAL), ('Benny', LOCAL),
            ('Cleo', LOCAL), ('Felix', TOUR),
        ]:
            role_lang[nm] = lang
        for nm in new_seated:
            role_lang[nm] = LOCAL if rng.random() < 0.7 else DIASP
        stand_langs = [TOUR, TOUR, DIASP]
        rng.shuffle(stand_langs)
        for nm, lang in zip(stand_extras, stand_langs):
            role_lang[nm] = lang

        for e in npc_ents:
            e.language_slug = role_lang.get(e.name, LOCAL)
            e.save(update_fields=['language_slug'])

        total = Entity.objects.filter(world=world).count()
        faces_used = sum(1 for e in npc_ents if e.face_id)
        self.stdout.write(self.style.SUCCESS(
            f'{spec["title"]}: {total} entities, {len(npc_ents)} NPCs, '
            f'{faces_used} with faces, {spec["local_lang"]}+diaspora+tourist '
            f'(lang {"created" if created else "reused"}).'
        ))

    # -------------------------------------------------------------------
    def _spawn_npcs(self, world, spec, ultra, rng, humanoid,
                    waiter_anim, seated_anim, wander_anim, barista_anim,
                    greet, face_anim, table_pos, stand_extras, new_seated):
        """Build the 18-NPC roster, assign a SavedFace, attach scripts."""
        shirts = spec['shirt_tint'] or SHIRTS

        # One random face per NPC, no repeats within a city.
        face_pks = list(SavedFace.objects
                        .order_by('?')
                        .values_list('pk', flat=True)[:18])

        waiter_name = f'Marco {spec["waiter_surname"]}'
        waiter = _make_npc(world, waiter_name, 0, -5)
        ava = _make_npc(world, 'Ava', -1, -7, ry=180)
        sam = _make_npc(world, 'Sam', 1.5, -7, ry=180)
        npc_ents = [waiter, ava, sam]

        seated_names = (ORIGINAL_SEATED[:4] + [ORIGINAL_SEATED[4]]
                        + [ORIGINAL_SEATED[5]] + list(new_seated))
        seated_pool = iter(seated_names)

        seated_ents_order = []

        four_seat = [(tx, tz) for tx, tz, s in CAFE_TABLES if s == 4]
        for tx, tz in four_seat:
            for (ox, oz) in [(-0.6, -0.5), (0.6, -0.5)]:
                nm = next(seated_pool, None)
                if not nm:
                    break
                e = _make_npc(world, nm, tx + ox, tz + oz)
                npc_ents.append(e)
                seated_ents_order.append(e)

        two_seat = [(tx, tz) for tx, tz, s in CAFE_TABLES if s == 2]
        for tx, tz in two_seat:
            nm = next(seated_pool, None)
            if not nm:
                break
            e = _make_npc(world, nm, tx - 0.6, tz)
            npc_ents.append(e)
            seated_ents_order.append(e)

        stand_positions = [(-3.5, 2.5), (3.5, -1.0), (-1.0, 5.0)]
        stand_ents = []
        for nm, (sx, sz) in zip(stand_extras, stand_positions):
            e = _make_npc(world, nm, sx, sz, ry=rng.uniform(0, 360))
            npc_ents.append(e)
            stand_ents.append(e)

        cleo = _make_npc(world, 'Cleo', 3, 4)
        felix = _make_npc(world, 'Felix', -3, 3)
        npc_ents += [cleo, felix]

        # Bind a SavedFace to every NPC before save so the FK is set.
        for i, e in enumerate(npc_ents):
            if i < len(face_pks):
                e.face_id = face_pks[i]
            e.save()

        attachments = []

        # Humanoid-builder on every NPC.
        for i, e in enumerate(npc_ents):
            build = BUILDS[i % len(BUILDS)]
            attachments.append(EntityScript(entity=e, script=humanoid, props={
                'skin':  SKINS[(i + spec['n']) % len(SKINS)],
                'shirt': shirts[(i + spec['n']) % len(shirts)],
                'pants': PANTS[i % len(PANTS)],
                'shoes': SHOES[i % len(SHOES)],
                'hair':  HAIRS[(i + spec['n']) % len(HAIRS)],
                'eyes':  EYES[i % len(EYES)],
                'ultra': ultra,
                'shoulderW': build[0], 'hipW': build[1],
                'heightScale': build[2],
            }))
            # Face-animator renders the SavedFace genome onto the sphere
            # cap that humanoid-builder parks in front of the head.
            attachments.append(EntityScript(
                entity=e, script=face_anim, props={}))

        def attach(entity, script, props=None):
            if script:
                attachments.append(EntityScript(
                    entity=entity, script=script, props=props or {}))

        attach(waiter, waiter_anim, {
            'tables': [[tx, 0.79, tz] for tx, tz in table_pos],
            'kitchen': [0.0, 0.0, -9.5],
            'speed': 1.7 + (spec['n'] % 3) * 0.15,
        })
        attach(waiter, greet, {
            'greeting': f'Welcome to {spec["title"].split("— ")[-1]}!',
        })

        for b, line in [
            (ava, 'What are you in the mood for?'),
            (sam, 'Hot or iced today?'),
        ]:
            attach(b, barista_anim, {})
            attach(b, greet, {'greeting': line})

        for p in seated_ents_order:
            attach(p, seated_anim, {})
            attach(p, greet, {'greeting': rng.choice([
                'Hey there.', 'First time here?', 'Pull up a chair.',
                'You must try the house blend.', 'Hi!', 'Welcome.',
            ])})

        for p in stand_ents:
            attach(p, wander_anim, {
                'bounds': [p.pos_x - 1.2, p.pos_z - 1.2,
                           p.pos_x + 1.2, p.pos_z + 1.2],
                'speed': 0.5,
            })
            attach(p, greet, {'greeting': rng.choice([
                'Passing through.', 'Just looking.',
                'Looking for someone.', 'I love this place.',
            ])})

        attach(cleo, wander_anim, {'bounds': [-7, -4, 7, 5], 'speed': 1.0})
        attach(cleo, greet, {'greeting': 'Still exploring!'})
        attach(felix, wander_anim, {'bounds': [-7, -4, 7, 5], 'speed': 1.2})
        attach(felix, greet, {'greeting': 'Is this place on the map?'})

        EntityScript.objects.bulk_create(attachments)

        return npc_ents
