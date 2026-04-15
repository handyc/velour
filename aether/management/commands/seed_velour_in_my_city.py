"""Seed the "Velour in My City" spinoff series — 10 worlds that riff on
Velour Cafe (HDRI).

Every city reuses the cafe shell and the existing humanoid-builder,
waiter/barista/seated/wander animation scripts from seed_cafe_hdri.
What varies per city:

- HDRI + wall/floor/counter palette
- NPC roster: Marco the Waiter is always present (under a city-specific
  surname), plus the original cafe regulars (Ava, Sam, Kenji, Liu, Rosa,
  Dante, Yara, Benny, Cleo, Felix) and a ring of brand-new characters —
  18 NPCs total per world.
- Three languages per city, hand-assigned by role cluster: a local
  majority tongue, a diaspora/immigrant language, and a tourist tongue.

Run: `venv/bin/python manage.py seed_velour_in_my_city [--ultra]`
"""

import secrets

from django.core.management.base import BaseCommand

from aether.models import Entity, EntityScript, Script, World
from grammar_engine.models import Language

from aether.management.commands.seed_cafe_variants import (
    build_cafe_shell, _ent, CAFE_TABLES,
    SKINS, SHIRTS, PANTS, SHOES, HAIRS, EYES, BUILDS,
    get_script,
)


# ---------------------------------------------------------------------------
# City design — ten variations, each with its own palette + languages.
# ---------------------------------------------------------------------------

CITIES = [
    {
        'n': 1, 'title': 'Velour in My City 1 — Old Town',
        'desc': 'The original cafe, a few blocks deeper into the old quarter.',
        'hdri': 'brown_photostudio_02',
        'walls': '#8b7355', 'floor': '#6b4226', 'counter': '#5c3317',
        'top': '#d2b48c', 'fog': '#c8b89a',
        'local_lang': 'Boulevardese',
        'shirt_tint': None,
        'waiter_surname': 'of the Boulevard',
    },
    {
        'n': 2, 'title': 'Velour in My City 2 — Riverside',
        'desc': 'A cafe where the canal windows catch the morning light.',
        'hdri': 'kloofendal_48d_partly_cloudy',
        'walls': '#9eb3c7', 'floor': '#6b6e7a', 'counter': '#4a5665',
        'top': '#cbd5e0', 'fog': '#c0d0dc',
        'local_lang': 'Riversidish',
        'shirt_tint': ['#2e6ca0', '#4b82ad', '#6ca0c0', '#94b7cf', '#2a5a8a'],
        'waiter_surname': 'on the River',
    },
    {
        'n': 3, 'title': 'Velour in My City 3 — Forest District',
        'desc': 'A green-wood cafe wedged between two old planes.',
        'hdri': 'forest_slope',
        'walls': '#4a5a38', 'floor': '#3a4228', 'counter': '#2f3820',
        'top': '#9ab07a', 'fog': '#4a6640',
        'local_lang': 'Canopic',
        'shirt_tint': ['#556b2f', '#6b8e23', '#3a5f0b', '#4a7c59', '#2e8b57'],
        'waiter_surname': 'of the Grove',
    },
    {
        'n': 4, 'title': 'Velour in My City 4 — Metropolis',
        'desc': 'The downtown branch — brushed steel, espresso, no patience.',
        'hdri': 'potsdamer_platz',
        'walls': '#4a4a5a', 'floor': '#3a3a40', 'counter': '#2a2a30',
        'top': '#808090', 'fog': '#30303a',
        'local_lang': 'Midtownese',
        'shirt_tint': ['#2a2a30', '#3a3a44', '#555560', '#1f1f27', '#6a6a78'],
        'waiter_surname': '(Marc)',
    },
    {
        'n': 5, 'title': 'Velour in My City 5 — Snow Quarter',
        'desc': 'A cafe with frost on the panes and steam off every cup.',
        'hdri': 'snowy_park_01',
        'walls': '#d0dce6', 'floor': '#aab8c2', 'counter': '#7a8c99',
        'top': '#f0f8ff', 'fog': '#e8eef2',
        'local_lang': 'Frostspeak',
        'shirt_tint': ['#e8ecef', '#b5c2cc', '#7a8c99', '#4a6070', '#d0d8e0'],
        'waiter_surname': 'Whitewind',
    },
    {
        'n': 6, 'title': 'Velour in My City 6 — Harborside',
        'desc': 'Mooring lines creak outside. The coffee tastes of salt.',
        'hdri': 'kloofendal_48d_partly_cloudy',
        'walls': '#6b7a8a', 'floor': '#5a656e', 'counter': '#3a4552',
        'top': '#b0c4cf', 'fog': '#6a7684',
        'local_lang': 'Harborspeak',
        'shirt_tint': ['#15456a', '#2a6080', '#4c7a94', '#748c9c', '#0b3657'],
        'waiter_surname': 'Longshore',
    },
    {
        'n': 7, 'title': 'Velour in My City 7 — Desert Arcade',
        'desc': 'An arcade cafe under a tile colonnade, shade half the day.',
        'hdri': 'brown_photostudio_02',
        'walls': '#d4a76a', 'floor': '#b88a50', 'counter': '#8b5a2b',
        'top': '#f4d7a0', 'fog': '#d4b080',
        'local_lang': 'Duneglot',
        'shirt_tint': ['#b85c2a', '#d4a76a', '#a05030', '#e6b87a', '#6a3a1a'],
        'waiter_surname': 'al-Rihla',
    },
    {
        'n': 8, 'title': 'Velour in My City 8 — Nightline',
        'desc': 'Open past midnight. Neon in the window, violet on the floor.',
        'hdri': 'potsdamer_platz',
        'walls': '#2a1e3a', 'floor': '#15102a', 'counter': '#0a0818',
        'top': '#7a6ad4', 'fog': '#1a0e2a',
        'local_lang': 'Noktaru',
        'shirt_tint': ['#6040b0', '#a060e0', '#ff4080', '#20a0e0', '#8a2be2'],
        'waiter_surname': '.exe',
    },
    {
        'n': 9, 'title': 'Velour in My City 9 — Greenhouse',
        'desc': 'Glass roof, ferns in every corner, a damp warm air.',
        'hdri': 'forest_slope',
        'walls': '#4a6a48', 'floor': '#3a4a38', 'counter': '#5a7a28',
        'top': '#a4c890', 'fog': '#5a7a50',
        'local_lang': 'Floralese',
        'shirt_tint': ['#6fa060', '#a8d08d', '#3f7a3f', '#88b078', '#54884a'],
        'waiter_surname': 'Verdi',
    },
    {
        'n': 10, 'title': 'Velour in My City 10 — Pier 13',
        'desc': 'At the end of a disused pier, between the tides.',
        'hdri': 'kloofendal_48d_partly_cloudy',
        'walls': '#6a5a4a', 'floor': '#4a3a2a', 'counter': '#3a2a1a',
        'top': '#c2a888', 'fog': '#8a7a6a',
        'local_lang': 'Piernese',
        'shirt_tint': ['#7a6a54', '#b89f7d', '#54432f', '#c4b89c', '#3a2f1f'],
        'waiter_surname': 'Splinter',
    },
]


# Shared "tourist" tongue — one language that every city hears from its
# visitors, so travellers who cross cities hear a familiar accent.
TOURIST_LANG_SLUG = 'velour-series-tourist'
# Shared "diaspora" language — a minority voice in every city, the same
# slug in every world, tying the series together linguistically.
DIASPORA_LANG_SLUG = 'velour-series-diaspora'


# ---------------------------------------------------------------------------
# Roster — 18 NPCs per city.
#
# Anchors (always present): Marco (waiter, city-renamed), Ava, Sam (baristas),
# and the original six seated regulars (Kenji, Liu, Rosa, Dante, Yara, Benny).
# Plus Cleo and Felix as two of the five extras.
# The remaining 7 slots are filled from a pool, deterministic by city.
# ---------------------------------------------------------------------------

EXTRAS_POOL = [
    'Priya', 'Noor', 'Theo', 'Beatrix', 'Zuzu', 'Kwame', 'Ines',
    'Oskar', 'Magnolia', 'Jules', 'Hiro', 'Ramona', 'Ziggy', 'Solenne',
    'Rin', 'Bodhi', 'Gertrude', 'Luc', 'Tamsin', 'Archibald',
    'Nyx', 'Ottilie', 'Basil', 'Imogen', 'Quill', 'Saffron',
]

ORIGINAL_SEATED = ['Kenji', 'Liu', 'Rosa', 'Dante', 'Yara', 'Benny']
# Three "stand-around" extras + two wanderers = 5. First three come from
# the extras pool; last two are Cleo and Felix to keep the through-line.
WANDERERS = ['Cleo', 'Felix']


def _ensure_language(slug, name, notes=''):
    lang, created = Language.objects.get_or_create(
        slug=slug,
        defaults={'name': name, 'seed': secrets.randbits(31), 'notes': notes},
    )
    return lang, created


def _make_npc(world, name, x, z, ry=0):
    return Entity(
        world=world, name=name, primitive='box', primitive_color='#000000',
        pos_x=x, pos_y=0, pos_z=z, rot_y=ry,
        scale_x=1, scale_y=1, scale_z=1,
        cast_shadow=False, receive_shadow=False, behavior='scripted',
    )


class Command(BaseCommand):
    help = 'Create the "Velour in My City" spinoff series (10 worlds).'

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

        if not humanoid:
            self.stderr.write(self.style.ERROR(
                'Run seed_cafe_hdri first — humanoid-builder script not found.'))
            return

        # Shared-across-the-series languages
        tourist_lang, _ = _ensure_language(
            TOURIST_LANG_SLUG, 'Tourist Creole',
            'Shared tourist voice — every Velour city has a few of these.')
        diaspora_lang, _ = _ensure_language(
            DIASPORA_LANG_SLUG, 'Diaspora Common',
            'Shared minority voice across the Velour series.')

        for spec in CITIES:
            self._build_city(spec, ultra, humanoid, waiter_anim, seated_anim,
                             wander_anim, barista_anim, greet,
                             tourist_lang, diaspora_lang)

    # -------------------------------------------------------------------
    def _build_city(self, spec, ultra, humanoid, waiter_anim, seated_anim,
                    wander_anim, barista_anim, greet,
                    tourist_lang, diaspora_lang):
        import random as rnd
        rng = rnd.Random(f'velour-city-{spec["n"]}')

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

        # Local language — one new Language per city so the series is
        # linguistically distinct, not a palette reskin.
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

        # A small bit of city-themed decor: three overhead lights tinted to
        # the top-color so each city reads differently even before you see
        # the HDRI.
        E = lambda *a, **k: entities.append(_ent(world, *a, **k))
        for lx in [-4, 0, 4]:
            for lz in [-3, 1, 5]:
                E(f'Light {lx},{lz}', 'sphere', spec['top'], lx, 2.8, lz,
                  sx=0.14, sy=0.14, sz=0.14, shadow=False,
                  behavior='bob', speed=0.3)

        Entity.objects.bulk_create(entities)

        # Build roster (18 NPCs).
        pool = EXTRAS_POOL[:]
        rng.shuffle(pool)
        stand_extras = pool[:3]
        new_seated = pool[3:7]   # 4 new patrons to top up seating

        npc_ents, role_by_name = self._spawn_npcs(
            world, spec, ultra, rng, humanoid,
            waiter_anim, seated_anim, wander_anim, barista_anim, greet,
            table_pos, stand_extras, new_seated,
        )

        # ----- Language assignment by role cluster -----
        # Locals (majority, ~55%): waiter + baristas + original seated
        #   regulars + most new patrons + one wanderer (Cleo).
        # Diaspora (~25%): Kenji/Liu/Rosa-style subset + one extra.
        # Tourists (~20%): Felix the returning tourist + two stand-extras.
        locals_set = {f'{spec["local_lang"]}'}  # ceremonial; actual slugs below
        role_lang = {}
        LOCAL, DIASP, TOUR = local_slug, diaspora_lang.slug, tourist_lang.slug

        # Anchors
        for nm, lang in [
            (f'Marco {spec["waiter_surname"]}', LOCAL),
            ('Ava', LOCAL), ('Sam', DIASP),
            ('Kenji', DIASP), ('Liu', LOCAL),
            ('Rosa', LOCAL), ('Dante', DIASP),
            ('Yara', LOCAL), ('Benny', LOCAL),
            ('Cleo', LOCAL), ('Felix', TOUR),
        ]:
            role_lang[nm] = lang
        # New seated
        for nm in new_seated:
            role_lang[nm] = LOCAL if rng.random() < 0.7 else DIASP
        # Standing extras lean tourist but not all
        stand_langs = [TOUR, TOUR, DIASP]
        rng.shuffle(stand_langs)
        for nm, lang in zip(stand_extras, stand_langs):
            role_lang[nm] = lang

        # Apply
        for e in npc_ents:
            e.language_slug = role_lang.get(e.name, LOCAL)
            e.save(update_fields=['language_slug'])

        total = Entity.objects.filter(world=world).count()
        self.stdout.write(self.style.SUCCESS(
            f'{spec["title"]}: {total} entities, {len(npc_ents)} NPCs, '
            f'languages: {spec["local_lang"]}+diaspora+tourist '
            f'(lang row {"created" if created else "reused"}).'
        ))

    # -------------------------------------------------------------------
    def _spawn_npcs(self, world, spec, ultra, rng, humanoid,
                    waiter_anim, seated_anim, wander_anim, barista_anim,
                    greet, table_pos, stand_extras, new_seated):
        """Build the 18-NPC roster and attach animation/greet scripts."""
        shirts = spec['shirt_tint'] or SHIRTS

        npc_ents = []
        attachments = []

        waiter_name = f'Marco {spec["waiter_surname"]}'
        waiter = _make_npc(world, waiter_name, 0, -5)
        ava = _make_npc(world, 'Ava', -1, -7, ry=180)
        sam = _make_npc(world, 'Sam', 1.5, -7, ry=180)
        waiter.save(); ava.save(); sam.save()
        npc_ents += [waiter, ava, sam]

        # Seated: fill BOTH 4-seat tables (4 NPCs) AND all six 2-seat tables
        # (6 NPCs) for 10 seated total.
        seated_names = (ORIGINAL_SEATED[:4]           # Kenji, Liu, Rosa, Dante
                        + [ORIGINAL_SEATED[4]]        # Yara
                        + [ORIGINAL_SEATED[5]]        # Benny
                        + new_seated)                 # 4 new ones → 10 total
        seated_pool = iter(seated_names)

        four_seat = [(tx, tz) for tx, tz, s in CAFE_TABLES if s == 4]
        for tx, tz in four_seat:
            for (ox, oz) in [(-0.6, -0.5), (0.6, -0.5)]:
                nm = next(seated_pool, None)
                if not nm:
                    break
                e = _make_npc(world, nm, tx + ox, tz + oz); e.save()
                npc_ents.append(e)

        two_seat = [(tx, tz) for tx, tz, s in CAFE_TABLES if s == 2]
        for tx, tz in two_seat:
            nm = next(seated_pool, None)
            if not nm:
                break
            e = _make_npc(world, nm, tx - 0.6, tz); e.save()
            npc_ents.append(e)

        # Three standing extras — spread around the room.
        stand_positions = [(-3.5, 2.5), (3.5, -1.0), (-1.0, 5.0)]
        for nm, (sx, sz) in zip(stand_extras, stand_positions):
            e = _make_npc(world, nm, sx, sz, ry=rng.uniform(0, 360)); e.save()
            npc_ents.append(e)

        # Two wanderers — Cleo + Felix.
        cleo = _make_npc(world, 'Cleo', 3, 4); cleo.save()
        felix = _make_npc(world, 'Felix', -3, 3); felix.save()
        npc_ents += [cleo, felix]

        # ----- Humanoid-builder on every NPC -----
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
                'shoulderW': build[0], 'hipW': build[1], 'heightScale': build[2],
            }))

        # ----- Role-specific animations + greetings -----
        def attach(entity, script, props=None):
            if script:
                attachments.append(EntityScript(
                    entity=entity, script=script, props=props or {}))

        # Waiter
        attach(waiter, waiter_anim, {
            'tables': [[tx, 0.79, tz] for tx, tz in table_pos],
            'kitchen': [0.0, 0.0, -9.5],
            'speed': 1.7 + (spec['n'] % 3) * 0.15,
        })
        attach(waiter, greet, {
            'greeting': f'Welcome to {spec["title"].split("— ")[-1]}!',
        })

        # Baristas — each with a slightly different line so the cities feel
        # distinct even through a single exchange.
        for b, line in [
            (ava, 'What are you in the mood for?'),
            (sam, 'Hot or iced today?'),
        ]:
            attach(b, barista_anim, {})
            attach(b, greet, {'greeting': line})

        # Seated patrons
        seated_ents = [e for e in npc_ents
                       if e.name in seated_names]
        for p in seated_ents:
            attach(p, seated_anim, {})
            attach(p, greet, {'greeting': rng.choice([
                'Hey there.', 'First time here?', 'Pull up a chair.',
                'You must try the house blend.', 'Hi!', 'Welcome.',
            ])})

        # Standing extras — re-use wander anim with tight bounds so they
        # mill in place rather than range across the room.
        stand_ents = [e for e in npc_ents if e.name in stand_extras]
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

        # Wanderers — Cleo + Felix, full-room ranges.
        attach(cleo, wander_anim, {
            'bounds': [-7, -4, 7, 5], 'speed': 1.0,
        })
        attach(cleo, greet, {'greeting': 'Still exploring!'})
        attach(felix, wander_anim, {
            'bounds': [-7, -4, 7, 5], 'speed': 1.2,
        })
        attach(felix, greet, {'greeting': 'Is this place on the map?'})

        EntityScript.objects.bulk_create(attachments)

        role_by_name = {e.name: e for e in npc_ents}
        return npc_ents, role_by_name
