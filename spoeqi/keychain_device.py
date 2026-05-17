"""ESP32-S3 keychain device protocol.

Wire format (host ↔ device over USB-CDC at 115200 baud or higher):

  Device → Host (on boot, unprompted):
    "VELOUR-KEYCHAIN v1 sha=<hex64>\n"

  Host → Device:                       Device → Host:
    "HELLO\n"                          "OK sha=<hex64> size=16384\n" + 16384 raw bytes
    "PING\n"                           "PONG\n"
    "SHA\n"                            "OK sha=<hex64>\n"
    "BYE\n"                            "OK\n"

The protocol is intentionally trivial — text-prefixed framing plus one
raw blob. No CRC: USB-CDC already has its own framing/error checking,
and we verify the seed sha256 host-side after the transfer regardless.

This module is small enough to dependency-inject into the management
command, which lets the same `sync` codepath be exercised against:

  - a real ESP32-S3 device (production path)
  - a local seed.bin file       (testing without hardware)
  - a recorded transcript       (regression tests)

Each backend implements ``read_seed() -> (seed_bytes, sha_str)``.
"""
from __future__ import annotations

import hashlib
import time
from pathlib import Path
from typing import Optional, Protocol

from .keychain import SEED_SIZE, compute_seed_sha


class DeviceError(RuntimeError):
    pass


class SeedSource(Protocol):
    def read_seed(self) -> tuple[bytes, str]:
        """Return ``(seed_bytes, sha256_reported_by_device)``."""
        ...

    def description(self) -> str:
        ...


# ─── File-backed source (tests / no-hardware development) ────────────

class FileSeedSource:
    """Pretend a local file is the device.  Useful for hooking the
    sync command up to a saved seed.bin without an ESP32 attached."""

    def __init__(self, path: Path):
        self.path = Path(path)
        if not self.path.exists():
            raise DeviceError(f'seed file not found: {self.path}')

    def read_seed(self) -> tuple[bytes, str]:
        seed = self.path.read_bytes()
        if len(seed) != SEED_SIZE:
            raise DeviceError(
                f'seed file is {len(seed)} bytes; expected {SEED_SIZE}')
        return seed, compute_seed_sha(seed)

    def description(self) -> str:
        return f'file://{self.path}'


# ─── Serial source — the real device ─────────────────────────────────

class SerialSeedSource:
    """Talk to a real ESP32-S3 over USB-CDC."""

    DEFAULT_BAUD     = 115200
    READ_TIMEOUT_S   = 5.0           # generous: the device might be booting
    SEED_TIMEOUT_S   = 10.0
    BOOT_QUIET_S     = 0.4           # let the device print its boot banner
    MAX_BANNER_BYTES = 4096

    def __init__(self, port: str,
                    baud: int = DEFAULT_BAUD,
                    timeout: float = READ_TIMEOUT_S):
        import serial                                 # local: only on path
        self.port = port
        self.baud = baud
        self._serial = serial.Serial(
            port=port, baudrate=baud, timeout=timeout,
            write_timeout=timeout,
        )
        # Drain whatever the device emitted on boot before we got here.
        time.sleep(self.BOOT_QUIET_S)
        self._serial.reset_input_buffer()

    def description(self) -> str:
        return f'serial://{self.port}@{self.baud}'

    # ─── low-level helpers ────────────────────────────────────────

    def _writeline(self, s: str) -> None:
        self._serial.write((s + '\n').encode('ascii'))
        self._serial.flush()

    def _readline(self, deadline: float) -> str:
        """Read until '\\n' or deadline.  Returns the line without
        trailing whitespace.  Raises DeviceError on timeout."""
        buf = bytearray()
        while time.time() < deadline:
            chunk = self._serial.read(1)
            if not chunk:
                continue
            if chunk == b'\n':
                return buf.decode('ascii', errors='replace').rstrip()
            buf.extend(chunk)
            if len(buf) > self.MAX_BANNER_BYTES:
                raise DeviceError('runaway line from device')
        raise DeviceError(f'timeout reading line (got {bytes(buf)!r})')

    def _readbytes(self, n: int, deadline: float) -> bytes:
        out = bytearray()
        while len(out) < n and time.time() < deadline:
            chunk = self._serial.read(min(4096, n - len(out)))
            if chunk:
                out.extend(chunk)
        if len(out) != n:
            raise DeviceError(
                f'short read: got {len(out)} bytes of {n} expected')
        return bytes(out)

    # ─── protocol ─────────────────────────────────────────────────

    def ping(self) -> bool:
        self._writeline('PING')
        line = self._readline(time.time() + 1.5)
        return line.strip().upper() == 'PONG'

    def read_seed(self) -> tuple[bytes, str]:
        self._writeline('HELLO')
        deadline = time.time() + self.SEED_TIMEOUT_S
        # Skip any lines until we see "OK sha=..." — tolerates the
        # device's boot banner showing up after our HELLO.
        header: Optional[str] = None
        while time.time() < deadline:
            line = self._readline(deadline)
            if line.startswith('OK ') and 'sha=' in line:
                header = line
                break
        if header is None:
            raise DeviceError('no OK header from device')

        # Parse "OK sha=<hex64> size=16384"
        parts = dict(p.split('=', 1) for p in header.split()[1:] if '=' in p)
        sha_reported = parts.get('sha', '')
        size = int(parts.get('size', '0'))
        if len(sha_reported) != 64:
            raise DeviceError(f'bad sha in header: {sha_reported!r}')
        if size != SEED_SIZE:
            raise DeviceError(f'bad seed size in header: {size}')

        seed = self._readbytes(SEED_SIZE, deadline)
        sha_local = compute_seed_sha(seed)
        if sha_local != sha_reported:
            raise DeviceError(
                f'sha mismatch: device said {sha_reported[:12]}…, '
                f'computed {sha_local[:12]}…')
        return seed, sha_local

    def close(self) -> None:
        try:
            self._writeline('BYE')
        except Exception:
            pass
        self._serial.close()


# ─── Auto-detect ──────────────────────────────────────────────────────

ESP32_S3_USB_IDS = {
    # (VID, PID) tuples known to belong to ESP32-S3 chips.  USB-Serial-
    # JTAG built-in is Espressif's own VID; if you use a CP210x bridge
    # you'd add that pair here.
    (0x303A, 0x1001),   # ESP32-S3 USB-Serial-JTAG (built-in)
    (0x303A, 0x0002),   # ESP32-S3 USB-CDC (when configured as TinyUSB)
    (0x303A, 0x4001),   # ESP32-S3 SuperMini variants seen in the wild
    (0x10C4, 0xEA60),   # CP210x — common USB-UART bridge
    (0x1A86, 0x7523),   # CH340 — cheap USB-UART bridge
}


def detect_devices() -> list[dict]:
    """Return one dict per attached serial port matching a known
    ESP32 / USB-UART VID:PID.  Caller picks one (or the first)."""
    import serial.tools.list_ports as lp
    out = []
    for info in lp.comports():
        vid_pid = (info.vid or 0, info.pid or 0)
        if vid_pid in ESP32_S3_USB_IDS or (info.manufacturer or '').lower().startswith(
                ('espressif', 'silicon labs', 'wch')):
            out.append({
                'device':       info.device,
                'description':  info.description,
                'manufacturer': info.manufacturer or '',
                'product':      info.product or '',
                'vid':          info.vid or 0,
                'pid':          info.pid or 0,
                'serial':       info.serial_number or '',
            })
    return out
