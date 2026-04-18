"""Close-of-session reflection — run the Identity loop against a
named piece of work.

Usage:
    python manage.py identity_session_reflect \
        --subject "Bodymap ST7735S drivers" \
        --summary "Shipped ESP32-S3, ESP8266 and ATtiny85 ports."

The command is the Claude-Code entry point for the same workflow the
browser exposes at /identity/session-reflect/. It generates a
tileset, a meditation, a mental-health diagnosis and a
patient/clinician exchange, then composes a first-person journal
entry that weaves them into the subject.
"""

from django.core.management.base import BaseCommand, CommandError


class Command(BaseCommand):
    help = 'Run one end-of-session reflection for the named subject.'

    def add_arguments(self, parser):
        parser.add_argument('--subject', required=True,
                            help='Short label for the work being closed '
                                 '(e.g. "Bodymap ST7735S drivers").')
        parser.add_argument('--summary', default='',
                            help='Optional free-text note passed in as '
                                 'context for the journal composition.')
        parser.add_argument('--trigger', default='claude',
                            choices=['manual', 'claude', 'loop', 'cron'],
                            help='Where the session was triggered from.')

    def handle(self, *args, **opts):
        from identity.session_reflection import run_session_reflection

        subject = opts['subject'].strip()
        if not subject:
            raise CommandError('--subject must not be empty')

        session = run_session_reflection(
            subject=subject,
            summary=opts['summary'],
            trigger=opts['trigger'],
        )

        self.stdout.write(self.style.SUCCESS(
            f'Session #{session.pk} — {session.status}  ({subject})'))
        self.stdout.write('')
        if session.tileset_slug:
            self.stdout.write(f'  tileset:    {session.tileset_slug}')
        if session.meditation_id:
            self.stdout.write(f'  meditation: #{session.meditation_id} '
                              f'{session.meditation.title[:80]}')
        if session.diagnosis_id:
            self.stdout.write(f'  diagnosis:  #{session.diagnosis_id} '
                              f'score={session.diagnosis.health_score:.2f}')
        if session.dialogue_id:
            self.stdout.write(f'  dialogue:   #{session.dialogue_id} '
                              f'{session.dialogue.topic[:80]}')
        if session.reel_slug:
            self.stdout.write(f'  reel:       {session.reel_slug}')

        self.stdout.write('')
        self.stdout.write('--- journal ---')
        self.stdout.write(session.journal_body)
