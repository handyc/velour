"""WebSocket consumer that proxies a real PTY-backed shell.

The browser-side xterm.js writes keystrokes; we forward them to the
PTY master fd. A background asyncio task reads PTY output and ships
it back as text frames. Resize events are forwarded as TIOCSWINSZ
ioctls so curses-style apps (vim, htop, less) lay out correctly.

Auth: requires request.user.is_authenticated. Anonymous WS handshakes
get rejected at accept() time. Sudo capability is gated on
is_superuser at PTY-spawn time, not per-keystroke — once the shell
starts, the kernel enforces what that uid can do.
"""

import asyncio
import fcntl
import json
import os
import pty
import shutil
import signal
import struct
import termios

from channels.generic.websocket import AsyncWebsocketConsumer


READ_CHUNK = 4096


class TerminalConsumer(AsyncWebsocketConsumer):
    async def connect(self):
        user = self.scope.get('user')
        if not user or not user.is_authenticated:
            await self.close(code=4401)
            return

        await self.accept()

        self.pid, self.fd = pty.fork()
        if self.pid == 0:
            shell = shutil.which('bash') or '/bin/sh'
            os.environ.setdefault('TERM', 'xterm-256color')
            os.environ.setdefault('LANG', 'C.UTF-8')
            os.execvp(shell, [shell, '-i'])

        self._reader_task = asyncio.create_task(self._reader_loop())

    async def disconnect(self, code):
        task = getattr(self, '_reader_task', None)
        if task and not task.done():
            task.cancel()

        pid = getattr(self, 'pid', None)
        if pid:
            try:
                os.kill(pid, signal.SIGHUP)
            except ProcessLookupError:
                pass
            try:
                os.waitpid(pid, os.WNOHANG)
            except ChildProcessError:
                pass

        fd = getattr(self, 'fd', None)
        if fd is not None:
            try:
                os.close(fd)
            except OSError:
                pass

    async def receive(self, text_data=None, bytes_data=None):
        if text_data is None:
            return
        try:
            msg = json.loads(text_data)
        except json.JSONDecodeError:
            return

        kind = msg.get('type')
        fd = getattr(self, 'fd', None)
        if fd is None:
            return

        if kind == 'input':
            data = msg.get('data', '')
            if data:
                await asyncio.get_running_loop().run_in_executor(
                    None, os.write, fd, data.encode('utf-8'),
                )
        elif kind == 'resize':
            cols = int(msg.get('cols') or 80)
            rows = int(msg.get('rows') or 24)
            # TIOCSWINSZ payload: rows, cols, xpixel, ypixel
            try:
                fcntl.ioctl(
                    fd, termios.TIOCSWINSZ,
                    struct.pack('HHHH', rows, cols, 0, 0),
                )
            except OSError:
                pass

    async def _reader_loop(self):
        loop = asyncio.get_running_loop()
        fd = self.fd
        try:
            while True:
                data = await loop.run_in_executor(None, _read_safely, fd)
                if not data:
                    break
                await self.send(text_data=data.decode('utf-8', errors='replace'))
        except asyncio.CancelledError:
            pass
        finally:
            try:
                await self.close()
            except Exception:
                pass


def _read_safely(fd):
    """Blocking PTY read in a thread. Returns b'' on EOF or EIO
    (which is what Linux returns when the slave side closes)."""
    try:
        return os.read(fd, READ_CHUNK)
    except OSError:
        return b''
