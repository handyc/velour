"""Push a Room or Building into an Aether World.

Examples:
    venv/bin/python manage.py roomplanner_to_aether --building home
    venv/bin/python manage.py roomplanner_to_aether --room velour-lab
    venv/bin/python manage.py roomplanner_to_aether --room velour-lab --lego
    venv/bin/python manage.py roomplanner_to_aether --building home --lego --cm-per-stud 20
"""

from django.core.management.base import BaseCommand, CommandError

from roomplanner.aether_export import (
    export_building,
    export_room,
    export_summary,
)
from roomplanner.lego_export import (
    DEFAULT_STUD_CM,
    export_building_to_lego,
    export_room_to_lego,
)
from roomplanner.models import Building, Room


class Command(BaseCommand):
    help = "Export a Room or Building to a walkable Aether World."

    def add_arguments(self, parser):
        group = parser.add_mutually_exclusive_group(required=True)
        group.add_argument('--room',     help='Room slug (single-room export)')
        group.add_argument('--building', help='Building slug (multi-floor export)')
        parser.add_argument('--lego', action='store_true',
            help='Emit the studded-brick variant instead of the regular Aether export.')
        parser.add_argument('--cm-per-stud', type=float, default=DEFAULT_STUD_CM,
            help=f'Scale ratio for --lego (default {DEFAULT_STUD_CM:g}; '
                 'smaller = denser, larger = chunkier). Ignored without --lego.')

    def handle(self, *args, **opts):
        lego = opts['lego']
        stud_cm = opts['cm_per_stud']

        if opts['room']:
            try:
                room = Room.objects.get(slug=opts['room'])
            except Room.DoesNotExist:
                raise CommandError(f'no room with slug {opts["room"]!r}')
            world = (export_room_to_lego(room, cm_per_stud=stud_cm)
                     if lego else export_room(room))
        else:
            try:
                building = Building.objects.get(slug=opts['building'])
            except Building.DoesNotExist:
                raise CommandError(f'no building with slug {opts["building"]!r}')
            world = (export_building_to_lego(building, cm_per_stud=stud_cm)
                     if lego else export_building(building))

        if lego:
            # Lego export packs every brick into one scripted entity, so
            # export_summary's per-kind breakdown isn't meaningful — count
            # the bricks instead.
            bricks = 0
            for ent in world.entities.all():
                for es in ent.scripts.all():
                    bricks += len(((es.props or {}).get('bricks')) or [])
            self.stdout.write(self.style.SUCCESS(
                f'wrote {bricks} bricks at {stud_cm:g} cm/stud to '
                f'/aether/{world.slug}/'
            ))
            return

        s = export_summary(world)
        self.stdout.write(self.style.SUCCESS(
            f'wrote {s["total"]} entities to /aether/{world.slug}/'
        ))
        for kind, n in sorted(s['by_kind'].items()):
            self.stdout.write(f'  {kind:10s} {n}')
