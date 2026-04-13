"""Seed Velour Smallville — a simplified, lighter version of Metropolis.

Reuses the scripts already registered by seed_metropolis:
  procedural-building, l-system-plant, humanoid-builder-v6, npc-lod-manager.

Small town: 5 buildings, 8 plants, 4 NPCs, one road, compact 40m ground.
"""
import random

from django.core.management.base import BaseCommand

from aether.models import Entity, EntityScript, Script, World

rng = random.Random(42)


class Command(BaseCommand):
    help = 'Create Velour Smallville — a small, lightweight demo town.'

    def handle(self, *args, **options):
        building_script = Script.objects.filter(slug='procedural-building').first()
        plant_script = Script.objects.filter(slug='l-system-plant').first()
        v6_script = Script.objects.filter(slug='humanoid-builder-v6').first()
        lod_script = Script.objects.filter(slug='npc-lod-manager').first()
        motion_lib = Script.objects.filter(slug='motion-quality-library').first()
        react = Script.objects.filter(slug='plaza-react-v5').first()

        missing = []
        if not building_script:
            missing.append('procedural-building')
        if not plant_script:
            missing.append('l-system-plant')
        if not v6_script:
            missing.append('humanoid-builder-v6')
        if missing:
            self.stderr.write(self.style.ERROR(
                f'Missing scripts: {", ".join(missing)}. '
                f'Run seed_metropolis first to register them.'))
            return

        World.objects.filter(slug='velour-smallville').delete()
        world = World.objects.create(
            title='Velour Smallville',
            slug='velour-smallville',
            description='A quiet small town with a handful of buildings, '
                        'trees, and friendly locals.',
            skybox='procedural',
            sky_color='#a0c8e8',
            ground_color='#4a6838',
            ground_size=40.0,
            ambient_light=0.6,
            fog_near=30.0,
            fog_far=80.0,
            fog_color='#c8d8e8',
            gravity=-9.81,
            spawn_x=0.0, spawn_y=1.6, spawn_z=10.0,
            soundscape='nature',
            ambient_volume=0.15,
            published=True, featured=False,
        )

        attachments = []

        # Ground
        Entity.objects.bulk_create([
            Entity(world=world, name='Ground', primitive='box',
                   primitive_color='#4a6838', pos_x=0, pos_y=-0.05, pos_z=0,
                   scale_x=40, scale_y=0.1, scale_z=40,
                   cast_shadow=False, receive_shadow=False, behavior='static'),
            # One main road
            Entity(world=world, name='Main Street', primitive='box',
                   primitive_color='#484840', pos_x=0, pos_y=0.005, pos_z=0,
                   scale_x=35, scale_y=0.01, scale_z=4,
                   cast_shadow=False, receive_shadow=False, behavior='static'),
        ])

        # --- Buildings (5) ---
        BUILDINGS = [
            ('General Store', 'shop', -8, -5, 0, 1, 7, 5, '#e0d0b8', '#908070', '#604030',
             {'awningColor': '#c84040'}),
            ('Post Office', 'house', 0, -8, 0, 2, 6, 5, '#c8b8a0', '#706060', '#804830', {}),
            ('Farmhouse', 'house', 10, -6, -15, 2, 8, 6, '#d0c0a8', '#807070', '#6a3828', {}),
            ('Church', 'church', -12, -14, 10, 2, 8, 6, '#e0d8d0', '#909090', '#504838', {}),
            ('Water Tower', 'tower', 14, -14, 0, 3, 4, 4, '#a0a098', '#808080', '#606060', {}),
        ]

        for name, btype, x, z, ry, floors, w, d, color, trim, roof, extras in BUILDINGS:
            e = Entity.objects.create(
                world=world, name=name, primitive='box',
                primitive_color='#000000',
                pos_x=x, pos_y=0, pos_z=z, rot_y=ry,
                scale_x=1, scale_y=1, scale_z=1,
                cast_shadow=False, receive_shadow=False,
                behavior='scripted',
            )
            attachments.append(EntityScript(entity=e, script=building_script, props={
                'type': btype, 'floors': floors, 'width': w, 'depth': d,
                'color': color, 'trim': trim, 'roof': roof, **extras,
            }))

        # --- Plants (8) ---
        PLANTS = [
            ('Oak 1', 'oak', -5, 4, 1.2),
            ('Oak 2', 'oak', 6, 5, 1.0),
            ('Birch', 'birch', -14, 3, 0.9),
            ('Pine 1', 'pine', 15, 8, 1.3),
            ('Pine 2', 'pine', 13, 10, 1.0),
            ('Willow', 'willow', -10, 10, 1.1),
            ('Bush 1', 'bush', 3, 3, 0.5),
            ('Bush 2', 'bush', -3, 6, 0.6),
        ]

        for name, species, x, z, scale in PLANTS:
            e = Entity.objects.create(
                world=world, name=name, primitive='box',
                primitive_color='#000000',
                pos_x=x, pos_y=0, pos_z=z,
                scale_x=1, scale_y=1, scale_z=1,
                cast_shadow=False, receive_shadow=False,
                behavior='scripted',
            )
            attachments.append(EntityScript(entity=e, script=plant_script, props={
                'species': species, 'scale': scale, 'seed': hash(name) % 10000,
            }))

        # --- NPCs (4) ---
        SKINS = ['#c89870', '#a87040', '#e8c898', '#8b5030']
        SHIRTS = ['#f0e8e0', '#385838', '#2a4060', '#684038']
        PANTS = ['#1c1c28', '#282830', '#323240', '#2a2a38']
        SHOES = ['#181818', '#3a2418', '#1a1a1a', '#242424']
        HAIRS = ['#1a1008', '#301a0e', '#b89040', '#080808']
        EYES = ['#3a2818', '#3868a8', '#1e4a1e', '#5a3418']
        NAMES = ['Mae', 'Otis', 'June', 'Hank']
        POSITIONS = [(2, 3, 0), (-6, 2, 90), (8, -3, -45), (-2, -6, 150)]
        REACTIONS = ['wave', 'curious', 'notice', 'approach']

        for i, (name, (px, pz, ry)) in enumerate(zip(NAMES, POSITIONS)):
            e = Entity.objects.create(
                world=world, name=name, primitive='box',
                primitive_color='#000000',
                pos_x=px, pos_y=0, pos_z=pz, rot_y=ry,
                scale_x=1, scale_y=1, scale_z=1,
                cast_shadow=False, receive_shadow=False,
                behavior='scripted',
            )
            if motion_lib:
                attachments.append(EntityScript(entity=e, script=motion_lib, props={}))
            attachments.append(EntityScript(entity=e, script=v6_script, props={
                'skin': SKINS[i], 'shirt': SHIRTS[i],
                'pants': PANTS[i], 'shoes': SHOES[i],
                'hair': HAIRS[i], 'eyes': EYES[i],
                'shoulderW': round(0.85 + rng.random() * 0.2, 2),
                'hipW': round(0.88 + rng.random() * 0.15, 2),
                'heightScale': round(0.92 + rng.random() * 0.12, 2),
                'jawW': round(0.88 + rng.random() * 0.2, 2),
                'cheekFull': round(0.92 + rng.random() * 0.16, 2),
                'foreheadH': round(0.95 + rng.random() * 0.1, 2),
            }))
            if lod_script:
                attachments.append(EntityScript(entity=e, script=lod_script, props={}))
            if react:
                attachments.append(EntityScript(entity=e, script=react, props={
                    'reaction': REACTIONS[i],
                    'bounds': [-15, -15, 15, 15],
                    'speed': round(0.3 + rng.random() * 0.3, 2),
                }))

        EntityScript.objects.bulk_create(attachments)

        total = Entity.objects.filter(world=world).count()
        self.stdout.write(self.style.SUCCESS(
            f'Velour Smallville created: {total} entities, '
            f'{len(BUILDINGS)} buildings, {len(PLANTS)} plants, '
            f'{len(NAMES)} NPCs.'))
