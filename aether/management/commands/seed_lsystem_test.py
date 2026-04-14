"""Seed a diagnostic world that places one of every L-system architecture
species in a labeled row, plus a row of L-system plants for comparison
and a single procedural-building as a control.

Walk in and look around — if the architecture row renders as buildings,
the L-system architecture pipeline works end-to-end. If they render as
trees or as nothing, the plant-script's renderer doesn't know about
the architecture branch (which is what an earlier diagnosis suggested).

    venv/bin/python manage.py seed_lsystem_test

Re-running deletes and recreates the world (idempotent).
"""

from django.core.management.base import BaseCommand
from django.utils.text import slugify

from aether.models import Entity, EntityScript, Script, World


WORLD_SLUG = 'lsystem-buildings-test'


class Command(BaseCommand):
    help = 'Seed a diagnostic Aether world to verify L-system building rendering.'

    def handle(self, *args, **opts):
        from lsystem.models import PlantSpecies

        # --- wipe any prior copy
        World.objects.filter(slug=WORLD_SLUG).delete()

        plant_script = Script.objects.filter(slug='l-system-plant').first()
        proc_building = Script.objects.filter(slug='procedural-building').first()
        if not plant_script:
            self.stderr.write(self.style.ERROR(
                'l-system-plant script missing. Run seed_metropolis first.'))
            return

        # --- build the world
        world = World.objects.create(
            slug=WORLD_SLUG,
            title='L-System Buildings — Diagnostic',
            description=(
                'Test world. Front row: every L-system architecture species. '
                'Back row: a few L-system plants for comparison. '
                'Far right: a procedural-building as a control. '
                'Walk forward from spawn to inspect.'
            ),
            skybox='procedural',
            sky_color='#9bb8d8',
            ground_color='#3a4a3a',
            ground_size=80.0,
            ambient_light=0.55,
            fog_near=60.0,
            fog_far=180.0,
            fog_color='#c8d8e4',
            gravity=-9.81,
            spawn_x=0.0, spawn_y=1.6, spawn_z=20.0,
            soundscape='',
            ambient_volume=0.0,
            published=True, featured=False,
        )

        # --- ground
        Entity.objects.create(
            world=world, name='Ground',
            primitive='box', primitive_color='#3a4a3a',
            pos_x=0, pos_y=-0.05, pos_z=0,
            scale_x=80, scale_y=0.1, scale_z=80,
            cast_shadow=False, receive_shadow=True,
            behavior='static',
        )

        # --- ARCHITECTURE ROW (front, z = -10) — one of each species
        arch_species = list(
            PlantSpecies.objects.filter(
                category__in=PlantSpecies.ARCHITECTURE_CATEGORIES,
            )
            .exclude(slug__startswith='random-')      # skip dupes
            .order_by('category', 'slug')
        )
        spacing = 8.0
        row_x_start = -(len(arch_species) - 1) * spacing / 2.0

        self.stdout.write(f'Placing {len(arch_species)} architecture species:')
        for i, sp in enumerate(arch_species):
            x = row_x_start + i * spacing
            props = sp.to_aether_props(scale=2.0, seed=42 + i)
            e = Entity.objects.create(
                world=world,
                name=f'[ARCH] {sp.name} ({sp.category}/{sp.slug})',
                primitive='box', primitive_color='#000000',
                pos_x=x, pos_y=0, pos_z=-10,
                rot_y=0,
                scale_x=1, scale_y=1, scale_z=1,
                cast_shadow=False, receive_shadow=False,
                behavior='scripted',
            )
            EntityScript.objects.create(
                entity=e, script=plant_script, props=props)
            self.stdout.write(f'  x={x:6.1f}  {sp.category:10s}  {sp.slug}')

        # --- PLANT ROW (back, z = -20) — a few species for comparison
        plant_examples = ['oak', 'pine', 'birch', 'palm', 'willow', 'cactus']
        plant_x_start = -(len(plant_examples) - 1) * spacing / 2.0

        self.stdout.write('')
        self.stdout.write(f'Placing {len(plant_examples)} comparison plants:')
        for i, species in enumerate(plant_examples):
            x = plant_x_start + i * spacing
            e = Entity.objects.create(
                world=world,
                name=f'[PLANT] {species}',
                primitive='box', primitive_color='#000000',
                pos_x=x, pos_y=0, pos_z=-20,
                scale_x=1, scale_y=1, scale_z=1,
                cast_shadow=False, receive_shadow=False,
                behavior='scripted',
            )
            EntityScript.objects.create(
                entity=e, script=plant_script,
                props={'species': species, 'scale': 1.0, 'seed': 42 + i},
            )
            self.stdout.write(f'  x={x:6.1f}  plant      {species}')

        # --- CONTROL: one procedural-building far right
        if proc_building:
            ctrl = Entity.objects.create(
                world=world, name='[CONTROL] procedural-building',
                primitive='box', primitive_color='#000000',
                pos_x=30, pos_y=0, pos_z=-10,
                scale_x=1, scale_y=1, scale_z=1,
                cast_shadow=False, receive_shadow=False,
                behavior='scripted',
            )
            EntityScript.objects.create(
                entity=ctrl, script=proc_building,
                props={
                    'type': 'house', 'floors': 2,
                    'width': 8, 'depth': 6,
                    'color': '#c8b8a0', 'trim': '#807060', 'roof': '#5a3030',
                },
            )
            self.stdout.write('')
            self.stdout.write('Placed control: procedural-building at x=30, z=-10')

        # --- info marker at spawn
        Entity.objects.create(
            world=world, name='Spawn marker',
            primitive='cylinder', primitive_color='#f0c040',
            pos_x=0, pos_y=0.05, pos_z=20,
            scale_x=0.4, scale_y=0.1, scale_z=0.4,
            cast_shadow=False, receive_shadow=False,
            behavior='static',
        )

        total = Entity.objects.filter(world=world).count()
        self.stdout.write('')
        self.stdout.write(self.style.SUCCESS(
            f'World "{world.title}" created with {total} entities.'))
        self.stdout.write(f'  URL: /aether/{world.slug}/enter/')
        self.stdout.write(
            '  Walk north (forward) from spawn. Architecture row is closer; '
            'plant row is behind it; procedural-building is to the right.')
