"""Refresh NPC behaviour scripts in the database.

Scripts live as JS source on the ``aether.Script`` model and are reused
by every NPC across every world. When the JS is updated in the seeder
modules (e.g. to add pathfinding to wander), this command pushes the
new source into the existing rows so live worlds pick it up without a
re-seed.
"""

from django.core.management.base import BaseCommand

from aether.models import Script


class Command(BaseCommand):
    help = 'Refresh NPC behaviour scripts (wander-articulated, etc.) from source.'

    def handle(self, *args, **options):
        from aether.management.commands.seed_cafe_hdri import (
            WANDER_ANIM_SCRIPT,
        )

        updated = []
        for slug, code in [
            ('wander-articulated', WANDER_ANIM_SCRIPT),
        ]:
            try:
                s = Script.objects.get(slug=slug)
            except Script.DoesNotExist:
                self.stderr.write(self.style.WARNING(
                    f'Script "{slug}" not found — run seed_cafe_hdri first.'))
                continue
            if s.code == code:
                self.stdout.write(f'  {slug}: unchanged')
                continue
            s.code = code
            s.save()
            updated.append(slug)
            self.stdout.write(self.style.SUCCESS(
                f'  {slug}: updated ({len(code)} chars)'))

        if updated:
            self.stdout.write(self.style.SUCCESS(
                f'Refreshed {len(updated)} script(s).'))
        else:
            self.stdout.write('No changes.')
