"""Minimal stdlib IRC client for h4kslnk bot sessions.

Just enough protocol to: connect (TLS or plain), register, join a
channel or open a PRIVMSG conversation, send/receive PRIVMSG, handle
PING, and quit cleanly.  No external libraries.

The client exposes a callback API rather than running a full event
loop on its own — `IrcClient.run(send_iter, on_recv)` reads incoming
lines on a background thread and lets the caller drive sends.  The
`h4ks_irc_session` management command wraps this in an stdin REPL
with an outgoing-message hard cap.
"""

from __future__ import annotations

import socket
import ssl
import threading
import time
from dataclasses import dataclass
from typing import Callable


@dataclass
class IrcLine:
    """One parsed IRC line.  Keep it simple — ``raw`` always holds
    the original wire form so the caller can fall back when fields
    don't fit the simple shape."""
    raw: str
    prefix: str = ''
    command: str = ''
    params: tuple = ()
    trailing: str = ''

    @property
    def sender_nick(self) -> str:
        """Extract just the nick part of ``nick!user@host``."""
        if not self.prefix:
            return ''
        return self.prefix.split('!', 1)[0]


def parse_line(raw: str) -> IrcLine:
    """Parse one IRC wire line.  RFC 1459 / 2812 shape:
        [':' prefix SPACE] command SPACE [params] [':' trailing]
    """
    s = raw.rstrip('\r\n')
    prefix = ''
    if s.startswith(':'):
        if ' ' in s:
            prefix, s = s[1:].split(' ', 1)
        else:
            prefix, s = s[1:], ''
    trailing = ''
    if ' :' in s:
        s, trailing = s.split(' :', 1)
    elif s.startswith(':'):
        trailing, s = s[1:], ''
    parts = s.split() if s else []
    command = parts[0].upper() if parts else ''
    params = tuple(parts[1:])
    return IrcLine(raw=raw, prefix=prefix, command=command,
                   params=params, trailing=trailing)


class IrcClient:
    """Connect to an IRC server and read/write lines.

    Usage:
        c = IrcClient('chat.h4ks.com', 6697, tls=True)
        c.connect(nick='velour-test', user='velour', realname='Velour bot')
        c.join('#h4ks')
        c.privmsg('#h4ks', 'hello')
        for line in c.read_lines(timeout=5):
            print(line.raw)
        c.quit('see you later')
    """

    def __init__(self, server: str, port: int, tls: bool = True,
                 connect_timeout: float = 15.0):
        self.server = server
        self.port = port
        self.tls = tls
        self.connect_timeout = connect_timeout
        self.sock: socket.socket | None = None
        self._buf = b''
        self._closed = False
        self.nick = ''

    def connect(self, *, nick: str, user: str = 'velour',
                realname: str = 'Velour h4kslnk bot',
                password: str | None = None,
                wait_for_welcome: float = 15.0) -> list[IrcLine]:
        """TCP[+TLS] connect, send NICK/USER, wait for RPL_WELCOME (001)
        or fail.  Returns the lines read during registration so the
        caller can log motd-ish things."""
        self.nick = nick
        raw = socket.create_connection(
            (self.server, self.port), timeout=self.connect_timeout)
        if self.tls:
            ctx = ssl.create_default_context()
            self.sock = ctx.wrap_socket(raw, server_hostname=self.server)
        else:
            self.sock = raw
        self.sock.settimeout(self.connect_timeout)

        if password:
            self._raw_send(f'PASS {password}')
        self._raw_send(f'NICK {nick}')
        self._raw_send(f'USER {user} 0 * :{realname}')

        deadline = time.monotonic() + wait_for_welcome
        registration_log: list[IrcLine] = []
        while time.monotonic() < deadline:
            line = self._read_one(timeout=deadline - time.monotonic())
            if line is None:
                continue
            registration_log.append(line)
            if line.command == 'PING':
                self._raw_send(f'PONG :{line.trailing or line.params[0]}')
            elif line.command == '001':           # RPL_WELCOME
                self.sock.settimeout(0.5)         # short for read_lines polling
                return registration_log
            elif line.command in ('433', '432', '436'):
                raise RuntimeError(
                    f'nick error {line.command}: {line.trailing or line.raw}')
            elif line.command in ('464', '465'):
                raise RuntimeError(
                    f'auth/connection refused {line.command}: '
                    f'{line.trailing or line.raw}')
        raise RuntimeError(
            f'no RPL_WELCOME within {wait_for_welcome}s — server probably '
            f'rejected us silently or expects extra capability negotiation')

    def join(self, channel: str) -> None:
        self._raw_send(f'JOIN {channel}')

    def privmsg(self, target: str, body: str) -> None:
        """Send one PRIVMSG.  IRC line cap is ~510 bytes wire including
        ``:nick!user@host PRIVMSG target :``, so we split the body at
        a conservative 400 chars."""
        for chunk in _chunks(body, 400):
            self._raw_send(f'PRIVMSG {target} :{chunk}')

    def quit(self, reason: str = 'bye') -> None:
        if self.sock and not self._closed:
            try:
                self._raw_send(f'QUIT :{reason}')
            except Exception:
                pass
        self.close()

    def close(self) -> None:
        self._closed = True
        if self.sock:
            try: self.sock.close()
            except Exception: pass
            self.sock = None

    # ── internal ──────────────────────────────────────────────

    def _raw_send(self, line: str) -> None:
        if not self.sock:
            raise RuntimeError('not connected')
        if '\r' in line or '\n' in line:
            raise ValueError('IRC line cannot contain CR or LF')
        self.sock.sendall((line + '\r\n').encode('utf-8', 'replace'))

    def _read_one(self, timeout: float | None = None) -> IrcLine | None:
        """Read one CRLF-terminated line, or None on timeout."""
        if not self.sock:
            return None
        if timeout is not None:
            self.sock.settimeout(max(0.05, timeout))
        try:
            while b'\r\n' not in self._buf:
                chunk = self.sock.recv(4096)
                if not chunk:
                    self._closed = True
                    return None
                self._buf += chunk
        except (socket.timeout, ssl.SSLWantReadError):
            return None
        line, _, self._buf = self._buf.partition(b'\r\n')
        return parse_line(line.decode('utf-8', 'replace'))

    def read_lines(self, timeout: float = 0.5,
                   max_lines: int = 50) -> list[IrcLine]:
        """Drain whatever's available within ``timeout``.  Auto-PONGs
        any PING.  Returns the rest for the caller to dispatch."""
        out: list[IrcLine] = []
        deadline = time.monotonic() + timeout
        for _ in range(max_lines):
            remaining = max(0, deadline - time.monotonic())
            line = self._read_one(timeout=remaining)
            if line is None:
                break
            if line.command == 'PING':
                self._raw_send(f'PONG :{line.trailing or (line.params[0] if line.params else "")}')
                continue
            out.append(line)
        return out


def _chunks(s: str, n: int):
    for i in range(0, max(1, len(s)), n):
        yield s[i:i + n]


def relay(client: IrcClient, target: str, on_inbound: Callable[[IrcLine], None],
          stop_event: threading.Event, poll_interval: float = 0.5):
    """Background thread body: poll for inbound lines, hand off any
    PRIVMSG aimed at us.  Caller signals stop via ``stop_event``."""
    while not stop_event.is_set() and not client._closed:
        for line in client.read_lines(timeout=poll_interval):
            if line.command in ('PRIVMSG', 'NOTICE', 'JOIN', 'PART',
                                'KICK', 'QUIT', 'NICK', 'TOPIC',
                                '353', '366'):
                on_inbound(line)
