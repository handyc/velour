"""Toggle the local prod-parity nginx in front of the dev runserver.

Subcommands:
  start       Generate config + collectstatic + start nginx on :8080
  stop        Stop the running local nginx
  status      Print current state
  regenerate  Rewrite the config without starting/stopping
"""
import json

from django.core.management.base import BaseCommand, CommandError

from services import local_nginx


class Command(BaseCommand):
    help = 'Manage the local prod-parity nginx (in front of runserver).'

    def add_arguments(self, parser):
        parser.add_argument('action',
                            choices=['start', 'stop', 'status', 'regenerate'])
        parser.add_argument('--json', action='store_true',
                            help='Print the status dict as JSON')

    def handle(self, *args, **opts):
        action = opts['action']

        if action == 'status':
            s = local_nginx.status()
            if opts['json']:
                self.stdout.write(json.dumps(s, indent=2, default=str))
                return
            self.stdout.write(
                f'nginx installed: {s["installed"]}\n'
                f'running:         {s["running"]}'
                + (f' (pid {s["pid"]})' if s['pid'] else '') + '\n'
                f'listen port:     {s["listen_port"]}\n'
                f'upstream:        127.0.0.1:{s["upstream_port"]}\n'
                f'static root:     {s["static_root"]}\n'
                f'config:          {s["conf_path"]}'
                + (' (exists)' if s['conf_exists'] else ' (not yet generated)')
            )
            return

        if action == 'regenerate':
            path = local_nginx.regenerate()
            self.stdout.write(self.style.SUCCESS(f'wrote {path}'))
            return

        if action == 'start':
            ok, msg = local_nginx.start()
        elif action == 'stop':
            ok, msg = local_nginx.stop()
        else:
            raise CommandError(f'unknown action {action}')

        if ok:
            self.stdout.write(self.style.SUCCESS(msg))
        else:
            raise CommandError(msg)
