"""Run the internal aiosmtpd SMTP server.

Usage:
    python manage.py run_smtpd
        Start the SMTP server on the configured host:port (default
        127.0.0.1:2525). Runs in the foreground — use supervisor
        or tmux to daemonize.

    python manage.py run_smtpd --port 2525 --host 127.0.0.1
        Override the host and port from the command line.

    python manage.py run_smtpd --host 0.0.0.0
        Accept connections from the LAN (including ESP nodes).

To test, in another terminal:
    python -c "
    import smtplib
    s = smtplib.SMTP('127.0.0.1', 2525)
    s.sendmail('test@velour.local', ['admin@velour.local'],
               'Subject: Hello from Velour\\n\\nThis is a test.')
    s.quit()
    "

Then check /mail/server/ in the Velour web UI — the message should
appear as a LocalDelivery row.

To use as Django's EMAIL_BACKEND target, add to settings.py:
    EMAIL_HOST = '127.0.0.1'
    EMAIL_PORT = 2525
    EMAIL_USE_TLS = False
Then any mail Velour sends (password resets, notifications) goes
to the internal server instead of an external relay.
"""

import asyncio

from django.core.management.base import BaseCommand


class Command(BaseCommand):
    help = 'Run the internal aiosmtpd SMTP server for testing.'

    def add_arguments(self, parser):
        parser.add_argument('--host', default=None,
                            help='Address to bind to (default from DB config).')
        parser.add_argument('--port', type=int, default=None,
                            help='Port to listen on (default from DB config).')

    def handle(self, *args, **opts):
        from aiosmtpd.controller import Controller
        from mail.handler import VelourSMTPHandler
        from mail.models import SMTPServerConfig

        config = SMTPServerConfig.get_self()
        host = opts['host'] or config.host
        port = opts['port'] or config.port

        if not config.is_enabled and not opts['host'] and not opts['port']:
            self.stderr.write(self.style.ERROR(
                'SMTP server is disabled in the database config. '
                'Pass --host / --port to override, or enable it in '
                'the admin.'))
            return

        handler = VelourSMTPHandler()
        controller = Controller(
            handler,
            hostname=host,
            port=port,
        )

        self.stdout.write(self.style.SUCCESS(
            f'Starting Velour internal SMTP server on {host}:{port}'))
        self.stdout.write('Press Ctrl+C to stop.')

        controller.start()
        try:
            asyncio.get_event_loop().run_forever()
        except KeyboardInterrupt:
            pass
        finally:
            controller.stop()
            self.stdout.write(self.style.SUCCESS('SMTP server stopped.'))
