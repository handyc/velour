"""Manually invoke Identity's tile reflection / generation.

Usage:
    python manage.py identity_tile_reflect
        Roll the "feels like it" check and generate a tile set if
        the roll clears.

    python manage.py identity_tile_reflect --force
        Ignore the probability gate and generate a tile set
        unconditionally.

    python manage.py identity_tile_reflect --reflect-on SLUG
        Print Identity's philosophical commentary on an existing
        tile set without generating anything.
"""

from django.core.management.base import BaseCommand


class Command(BaseCommand):
    help = "Identity's tile reflection and autonomous generation."

    def add_arguments(self, parser):
        parser.add_argument('--force', action='store_true',
                            help='Generate unconditionally — skip the '
                                 '"feels like it" probability gate.')
        parser.add_argument('--reflect-on', default='',
                            help='Slug of an existing TileSet to '
                                 'reflect on. No generation happens.')

    def handle(self, *args, **opts):
        if opts['reflect_on']:
            from tiles.models import TileSet
            from identity.tiles_reflection import reflect_on_tileset
            try:
                ts = TileSet.objects.get(slug=opts['reflect_on'])
            except TileSet.DoesNotExist:
                self.stderr.write(self.style.ERROR(
                    f'No tile set with slug {opts["reflect_on"]!r}'))
                return
            self.stdout.write(self.style.SUCCESS(
                f'Reflection on {ts.name}:'))
            self.stdout.write('')
            self.stdout.write(reflect_on_tileset(ts))
            return

        from identity.tiles_reflection import (
            identity_feels_like_making_tiles,
            generate_tileset_from_identity,
        )
        if not opts['force']:
            should, reason = identity_feels_like_making_tiles()
            if not should:
                self.stdout.write(self.style.WARNING(
                    f'Identity did not feel like making tiles. {reason}'))
                return
            self.stdout.write(self.style.SUCCESS(
                f'Identity feels like making tiles. {reason}'))
        ts = generate_tileset_from_identity()
        self.stdout.write(self.style.SUCCESS(
            f'Created tile set {ts.slug} — {ts.tile_count} tiles'))
        self.stdout.write('')
        self.stdout.write(ts.description)
