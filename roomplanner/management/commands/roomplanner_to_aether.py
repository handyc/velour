"""Push a Room or Building into an Aether World.

Examples:
    venv/bin/python manage.py roomplanner_to_aether --building home
    venv/bin/python manage.py roomplanner_to_aether --room velour-lab
"""

from django.core.management.base import BaseCommand, CommandError

from roomplanner.aether_export import (
    export_building,
    export_room,
    export_summary,
)
from roomplanner.models import Building, Room


class Command(BaseCommand):
    help = "Export a Room or Building to a walkable Aether World."

    def add_arguments(self, parser):
        group = parser.add_mutually_exclusive_group(required=True)
        group.add_argument('--room',     help='Room slug (single-room export)')
        group.add_argument('--building', help='Building slug (multi-floor export)')

    def handle(self, *args, **opts):
        if opts['room']:
            try:
                room = Room.objects.get(slug=opts['room'])
            except Room.DoesNotExist:
                raise CommandError(f'no room with slug {opts["room"]!r}')
            world = export_room(room)
        else:
            try:
                building = Building.objects.get(slug=opts['building'])
            except Building.DoesNotExist:
                raise CommandError(f'no building with slug {opts["building"]!r}')
            world = export_building(building)

        s = export_summary(world)
        self.stdout.write(self.style.SUCCESS(
            f'wrote {s["total"]} entities to /aether/{world.slug}/'
        ))
        for kind, n in sorted(s['by_kind'].items()):
            self.stdout.write(f'  {kind:10s} {n}')
