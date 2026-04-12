"""Render tiling artworks for all tilesets that don't have one yet.

    python manage.py render_artworks           # only missing
    python manage.py render_artworks --all     # re-render everything
"""

from django.core.management.base import BaseCommand


class Command(BaseCommand):
    help = 'Render PNG tiling artworks for tilesets and save to Attic.'

    def add_arguments(self, parser):
        parser.add_argument('--all', action='store_true',
                            help='Re-render all, not just missing.')

    def handle(self, *args, **options):
        from attic.models import MediaItem
        from identity.models import Identity
        from identity.tile_artwork import generate_artwork_from_tileset
        from tiles.models import TileSet

        identity = Identity.get_self()
        tilesets = TileSet.objects.all()
        rendered = 0

        for ts in tilesets:
            if ts.tile_count == 0:
                continue
            slug = f'artwork-{ts.slug}'
            if not options['all'] and MediaItem.objects.filter(slug=slug).exists():
                self.stdout.write(f'  skip: {ts.name} (already exists)')
                continue
            item = generate_artwork_from_tileset(
                ts, mood=identity.mood,
                mood_intensity=identity.mood_intensity)
            if item:
                rendered += 1
                self.stdout.write(f'  rendered: {ts.name} ({item.size_bytes} bytes)')

        self.stdout.write(self.style.SUCCESS(f'Done. {rendered} artworks rendered.'))
