"""Grant / revoke per-app access for a user.

Convention: one Django Group per app, named ``app:<slug>``. Membership
in that group means the user can reach ``/<slug>/...`` URLs when
``VELOUR_PER_APP_ACCESS_ENFORCED`` is True.

Examples:
  manage.py grant_app_access alice taxon s3lab strateta
  manage.py grant_app_access alice --revoke terminal
  manage.py grant_app_access alice --list
  manage.py grant_app_access alice --grant-all
"""
from __future__ import annotations

from django.contrib.auth import get_user_model
from django.core.management.base import BaseCommand, CommandError

from app_factory.access import GROUP_PREFIX, grant, prefix_to_slug, revoke


class Command(BaseCommand):
    help = 'Grant / revoke per-app access for a user (Django Group app:<slug>).'

    def add_arguments(self, parser):
        parser.add_argument('username')
        parser.add_argument('apps', nargs='*',
                            help='App slugs (e.g. taxon s3lab). Optional with --list / --grant-all.')
        parser.add_argument('--revoke', action='store_true',
                            help='Remove membership instead of granting.')
        parser.add_argument('--list', action='store_true',
                            help='Show current per-app access for the user; do not modify.')
        parser.add_argument('--grant-all', action='store_true',
                            help='Grant access to every installed app.')

    def handle(self, *args, **opts):
        User = get_user_model()
        try:
            user = User.objects.get(username=opts['username'])
        except User.DoesNotExist:
            raise CommandError(f'no such user: {opts["username"]!r}')

        all_slugs = sorted(set(prefix_to_slug().values()))

        if opts['list']:
            current = sorted(
                g.name[len(GROUP_PREFIX):]
                for g in user.groups.all()
                if g.name.startswith(GROUP_PREFIX)
            )
            self.stdout.write(f'{user.username}: superuser={user.is_superuser} staff={user.is_staff}')
            self.stdout.write(f'  app groups ({len(current)}/{len(all_slugs)}):')
            for slug in all_slugs:
                marker = '✓' if slug in current else ' '
                self.stdout.write(f'    [{marker}] {slug}')
            return

        if opts['grant_all']:
            slugs = all_slugs
        else:
            slugs = opts['apps']
            if not slugs:
                raise CommandError(
                    'pass app slugs to grant/revoke, or use --list / --grant-all'
                )
            unknown = [s for s in slugs if s not in all_slugs]
            if unknown:
                raise CommandError(
                    f'unknown app slug(s): {unknown}. '
                    f'known: {all_slugs}'
                )

        if opts['revoke']:
            n = revoke(user, slugs)
            verb = 'revoked'
        else:
            n = grant(user, slugs)
            verb = 'granted'
        self.stdout.write(self.style.SUCCESS(
            f'{verb} {n} app group(s) for {user.username}'
        ))
