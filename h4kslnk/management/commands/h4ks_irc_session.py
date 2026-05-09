"""Open a real IRC session against chat.h4ks.com (or any IRC server)
and run an stdin REPL: lines you type are PRIVMSG'd to the target,
incoming PRIVMSG/NOTICE lines are printed, everything is logged
into a BotSession + BotMessage chain in the DB.

Usage examples:
    # join a channel and chat
    manage.py h4ks_irc_session --target '#h4ks' --nick velour-test --cap 5

    # private-message a contact (use their nick as target, no #)
    manage.py h4ks_irc_session --target mattf --nick velour-helper \\
        --purpose 'follow-up about vibegames version picker'

    # plaintext / non-default port
    manage.py h4ks_irc_session --target '#h4ks' --port 6667 --no-tls

The session has a hard outgoing-message cap (default 5).  Once
reached, further input is refused and the bot waits up to
``--linger`` seconds for replies before disconnecting.

Stop with EOF (Ctrl-D) or by typing ``/quit``.  ``/help`` lists the
in-REPL commands.
"""

from __future__ import annotations

import threading
import time
from datetime import datetime, timezone

from django.core.management.base import BaseCommand, CommandError
from django.utils import timezone as djtz

from h4kslnk.irc import IrcClient
from h4kslnk.models import BotSession, BotMessage


class Command(BaseCommand):
    help = 'Open an IRC session, REPL stdin → PRIVMSG, log everything to DB.'

    def add_arguments(self, parser):
        parser.add_argument('--server', default='chat.h4ks.com')
        parser.add_argument('--port', type=int, default=6697)
        parser.add_argument('--no-tls', action='store_true')
        parser.add_argument('--nick', required=True,
                            help='Bot nick.  Convention: "velour-<purpose>".')
        parser.add_argument('--target', required=True,
                            help='#channel or contact nick (PM).')
        parser.add_argument('--cap', type=int, default=5,
                            help='Hard cap on outgoing PRIVMSGs (default 5).')
        parser.add_argument('--linger', type=float, default=10.0,
                            help='Seconds to keep listening after cap '
                                 'reached or you /quit (default 10).')
        parser.add_argument('--purpose', default='',
                            help='Free-text purpose, stored on the session.')
        parser.add_argument('--password', default=None,
                            help='IRC PASS, if the server requires one.')
        parser.add_argument('--say', action='append', default=[],
                            help='Send this PRIVMSG immediately after '
                                 'connect/join, then drop into listen '
                                 'mode (no stdin REPL).  Repeatable.')
        parser.add_argument('--listen-only', action='store_true',
                            help='Skip the stdin REPL.  Useful with '
                                 '--say for one-shot probes.')

    def handle(self, *args, **opts):
        nick = opts['nick']
        target = opts['target']
        if not nick or len(nick) > 30:
            raise CommandError('nick must be 1..30 chars')

        session = BotSession.objects.create(
            nick=nick, target=target,
            server=opts['server'], port=opts['port'],
            use_tls=not opts['no_tls'],
            message_cap=opts['cap'], purpose=opts['purpose'],
            autonomous=False,
            status='connecting', started_at=djtz.now(),
        )
        log_sys = lambda body: BotMessage.objects.create(
            session=session, direction='sys', sender='', body=body)
        log_in = lambda sender, body: BotMessage.objects.create(
            session=session, direction='in', sender=sender, body=body)
        log_out = lambda body: BotMessage.objects.create(
            session=session, direction='out', sender=nick, body=body)

        self.stdout.write(self.style.NOTICE(
            f'session #{session.pk} · {nick} → {target} · cap {opts["cap"]}'))
        log_sys(f'connecting to {opts["server"]}:{opts["port"]} '
                f'{"+TLS" if not opts["no_tls"] else "plain"}')

        client = IrcClient(opts['server'], opts['port'],
                           tls=not opts['no_tls'])
        try:
            reg_lines = client.connect(
                nick=nick, password=opts['password'])
            for line in reg_lines:
                if line.command in ('001', '002', '003', '004', '005',
                                    '375', '372', '376', 'NOTICE'):
                    log_sys(f'{line.command} {line.trailing}')
        except Exception as e:
            session.status = 'error'
            session.error = str(e)
            session.ended_at = djtz.now()
            session.save()
            log_sys(f'connect failed: {e}')
            raise CommandError(f'connect failed: {e}')

        if target.startswith('#'):
            client.join(target)
            log_sys(f'joining {target}')

        session.status = 'running'
        session.save(update_fields=['status'])

        # ── background reader ──────────────────────────────
        stop_event = threading.Event()

        def reader():
            while not stop_event.is_set():
                try:
                    lines = client.read_lines(timeout=0.5)
                except Exception as e:
                    log_sys(f'read error: {e}')
                    break
                for line in lines:
                    if line.command == 'PRIVMSG' and line.params:
                        sender = line.sender_nick
                        body = line.trailing
                        log_in(sender, body)
                        self.stdout.write(f'\n← {sender}: {body}')
                        self.stdout.write('> ', ending='')
                        self.stdout.flush()
                    elif line.command == 'NOTICE' and line.params:
                        log_sys(f'NOTICE from {line.sender_nick}: '
                                f'{line.trailing}')
                    elif line.command == 'JOIN':
                        log_sys(f'{line.sender_nick} joined {line.params[0] if line.params else line.trailing}')
                    elif line.command == 'PART':
                        log_sys(f'{line.sender_nick} parted')
                    elif line.command == 'QUIT':
                        log_sys(f'{line.sender_nick} quit: {line.trailing}')

        t = threading.Thread(target=reader, daemon=True)
        t.start()

        # ── one-shot pre-sends from --say ─────────────────
        sent = 0
        cap = opts['cap']
        for line in opts['say']:
            if sent >= cap:
                break
            # Give the server a beat to settle JOIN before PRIVMSG.
            time.sleep(0.6)
            client.privmsg(target, line)
            log_out(line)
            sent += 1
            self.stdout.write(f'  → {target}: {line}  [{sent}/{cap}]')

        # ── listen-only? sleep linger and bail ────────────
        if opts['listen_only']:
            self.stdout.write(self.style.NOTICE(
                f'listen-only · waiting {opts["linger"]}s for replies'))
            time.sleep(opts['linger'])
            stop_event.set()
            client.quit('done')
            session.status = 'done'
            session.ended_at = djtz.now()
            session.save()
            self.stdout.write(self.style.SUCCESS(
                f'session #{session.pk} closed; sent {sent} msgs'))
            return

        # ── REPL loop ──────────────────────────────────────
        self.stdout.write(self.style.SUCCESS(
            f'connected.  type messages, /help, or /quit.  cap={cap}'))
        self.stdout.write('> ', ending='')
        self.stdout.flush()

        try:
            while True:
                try:
                    line = input()
                except EOFError:
                    break
                line = line.strip()
                if not line:
                    self.stdout.write('> ', ending='')
                    self.stdout.flush()
                    continue
                if line == '/quit':
                    break
                if line == '/help':
                    self.stdout.write(
                        '  type a message and hit ENTER to send to '
                        f'{target}\n'
                        '  /quit          disconnect cleanly\n'
                        '  /me <action>   /me text\n'
                        '  /raw <line>    raw IRC line (debug)\n'
                        f'  cap={cap}, sent={sent}')
                    self.stdout.write('> ', ending='')
                    self.stdout.flush()
                    continue
                if line.startswith('/raw '):
                    raw = line[5:]
                    log_sys(f'raw: {raw}')
                    client._raw_send(raw)
                    self.stdout.write('> ', ending='')
                    self.stdout.flush()
                    continue
                action = None
                if line.startswith('/me '):
                    action = line[4:]
                    body = f'\x01ACTION {action}\x01'
                    display = f'* {nick} {action}'
                else:
                    body = line
                    display = line

                if sent >= cap:
                    self.stdout.write(self.style.WARNING(
                        f'cap reached ({cap}); /quit to leave'))
                    self.stdout.write('> ', ending='')
                    self.stdout.flush()
                    continue

                client.privmsg(target, body)
                log_out(display)
                sent += 1
                self.stdout.write(f'  → {target}: {display}  [{sent}/{cap}]')
                self.stdout.write('> ', ending='')
                self.stdout.flush()
        except KeyboardInterrupt:
            log_sys('SIGINT')

        # ── linger + close ─────────────────────────────────
        log_sys(f'lingering {opts["linger"]}s')
        time.sleep(opts['linger'])
        stop_event.set()
        client.quit('done')

        session.status = 'done'
        session.ended_at = djtz.now()
        session.save()
        self.stdout.write(self.style.SUCCESS(
            f'session #{session.pk} closed; sent {sent} msgs'))
