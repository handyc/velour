"""Seed a diagnostic world populated with ONLY L-system architecture
species — no plants, no procedural-building control, nothing else.

Every building in this world is a PlantSpecies from the lsystem app with
category in {building, tower, bridge, wall}, rendered via the Aether
`procedural-building` script. The species data supplies the preset
(type, colors, dimensions, floors) but the procedural-building script
does the actual geometry.

If these look identical to plain procedural buildings, that is because
there is currently no L-system-grown-geometry architecture renderer —
the `l-system-plant` script only knows about plant tokens. Architecture
species today act as *curated presets* for procedural-building.

    venv/bin/python manage.py seed_lsystem_test

Re-running deletes and recreates the world (idempotent).
"""

from django.core.management.base import BaseCommand

from aether.models import Entity, EntityScript, Script, World


WORLD_SLUG = 'lsystem-buildings-test'


class Command(BaseCommand):
    help = 'Seed a pure L-system-buildings diagnostic Aether world.'

    def handle(self, *args, **opts):
        from lsystem.models import PlantSpecies

        World.objects.filter(slug=WORLD_SLUG).delete()

        lsys_building = Script.objects.filter(slug='l-system-building').first()
        if not lsys_building:
            self.stderr.write(self.style.ERROR(
                'l-system-building script missing. Run '
                'seed_lsystem_building_script first.'))
            return

        arch_species = list(
            PlantSpecies.objects.filter(
                category__in=PlantSpecies.ARCHITECTURE_CATEGORIES,
            )
            .exclude(slug__startswith='random-')
            .order_by('category', 'slug')
        )
        if not arch_species:
            self.stderr.write(self.style.ERROR(
                'No L-system architecture species found in DB.'))
            return

        world = World.objects.create(
            slug=WORLD_SLUG,
            title='L-System Buildings Only — Diagnostic',
            description=(
                f'Pure test world. {len(arch_species)} L-system architecture '
                'species, each rendered via procedural-building using '
                'PlantSpecies.to_building_props(). No plants, no non-L-system '
                'buildings, nothing else. Walk the row from spawn.'
            ),
            skybox='procedural',
            sky_color='#9bb8d8',
            ground_color='#3a4a3a',
            ground_size=120.0,
            ambient_light=0.6,
            fog_near=80.0,
            fog_far=220.0,
            fog_color='#c8d8e4',
            gravity=-9.81,
            spawn_x=0.0, spawn_y=1.6, spawn_z=25.0,
            soundscape='',
            ambient_volume=0.0,
            published=True, featured=False,
        )

        Entity.objects.create(
            world=world, name='Ground',
            primitive='box', primitive_color='#3a4a3a',
            pos_x=0, pos_y=-0.05, pos_z=0,
            scale_x=120, scale_y=0.1, scale_z=120,
            cast_shadow=False, receive_shadow=True,
            behavior='static',
        )

        spacing = 12.0
        row_x_start = -(len(arch_species) - 1) * spacing / 2.0

        self.stdout.write(
            f'Placing {len(arch_species)} L-system architecture buildings '
            '(no plants, no other buildings):')
        for i, sp in enumerate(arch_species):
            x = row_x_start + i * spacing
            props = sp.to_aether_props(scale=1.0, seed=42 + i)

            e = Entity.objects.create(
                world=world,
                name=(
                    f'[L-SYSTEM] {sp.name} '
                    f'(species={sp.slug}, cat={sp.category}, '
                    f'style={sp.arch_style or "-"}, roof={sp.roof_style})'
                ),
                primitive='box', primitive_color='#000000',
                pos_x=x, pos_y=0, pos_z=-5,
                rot_y=0,
                scale_x=1, scale_y=1, scale_z=1,
                cast_shadow=False, receive_shadow=False,
                behavior='scripted',
            )
            EntityScript.objects.create(
                entity=e, script=lsys_building, props=props)
            self.stdout.write(
                f'  x={x:6.1f}  {sp.category:10s}  {sp.slug:22s}  '
                f'axiom={sp.axiom!r:14s} iter={sp.iterations} '
                f'angle={sp.angle} roof={sp.roof_style}')

        Entity.objects.create(
            world=world, name='Spawn marker',
            primitive='cylinder', primitive_color='#f0c040',
            pos_x=0, pos_y=0.05, pos_z=25,
            scale_x=0.4, scale_y=0.1, scale_z=0.4,
            cast_shadow=False, receive_shadow=False,
            behavior='static',
        )

        total = Entity.objects.filter(world=world).count()
        scripted = Entity.objects.filter(world=world, behavior='scripted').count()
        self.stdout.write('')
        self.stdout.write(self.style.SUCCESS(
            f'World "{world.title}" created with {total} entities '
            f'({scripted} scripted, all L-system buildings).'))
        self.stdout.write(f'  URL: /aether/{world.slug}/enter/')
        self.stdout.write(
            '  Every scripted entity in this world runs the l-system-building '
            'script against a PlantSpecies grammar (axiom + rules + iterations '
            '+ angle). Geometry is grown recursively, not preset.')
