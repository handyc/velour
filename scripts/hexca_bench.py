#!/usr/bin/env python3
"""hexca_bench.py — bench helper for the esp32_s3_xcc supermini fork.

A friendly wrapper around the device's HTTP endpoints so the bench
operator doesn't have to memorise curl invocations. Pairs with the
firmware in isolation/artifacts/hex_ca_class4/esp32_s3_xcc/.

Common flows:

  ./hexca_bench.py info                          # GET /info → pretty print
  ./hexca_bench.py compile-push step.c step      # xcc700 + push + slot
  ./hexca_bench.py push winner.elf step          # already-compiled ELF
  ./hexca_bench.py reset                         # /reset-slots
  ./hexca_bench.py rehunt                        # /rehunt (blocks 10-30 s)
  ./hexca_bench.py wifi-provision SSID PASS      # /wifi
  ./hexca_bench.py watch                         # poll /info every 2 s

Default device URL is http://hexca.local; override with --device URL
or VELOUR_HEXCA_URL.

Compile-push uses the vendored xcc700 directly (no Velour roundtrip),
so it works whether or not Velour is running.
"""
from __future__ import annotations

import argparse
import json
import os
import shutil
import subprocess
import sys
import tempfile
import time
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
XCC700 = REPO_ROOT / 'isolation' / 'artifacts' / 'xcc700' / 'xcc700'
DEFAULT_DEVICE = os.environ.get('VELOUR_HEXCA_URL', 'http://hexca.local')


def _http(method: str, url: str, *, data: bytes | None = None,
          headers: dict | None = None, timeout: float = 8.0) -> tuple[int, str]:
    req = urllib.request.Request(
        url, data=data, method=method, headers=headers or {},
    )
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            return resp.status, resp.read().decode('utf-8', errors='replace')
    except urllib.error.HTTPError as e:
        return e.code, e.read().decode('utf-8', errors='replace')
    except (urllib.error.URLError, TimeoutError, OSError) as e:
        return 0, f'{type(e).__name__}: {e}'


def cmd_info(args) -> int:
    status, body = _http('GET', f'{args.device}/info')
    if status != 200:
        print(f'error {status}: {body}', file=sys.stderr)
        return 1
    try:
        info = json.loads(body)
    except Exception:
        print(body)
        return 0
    print(f"uptime    {info['uptime_s']} s")
    print(f"free heap {info['free_heap']} B")
    print(f"WiFi      {info['wifi_mode']} · {info.get('ssid', '—')} · {info.get('ip', '—')}")
    le = info.get('last_elf')
    if le:
        print(f"last ELF  {le['bytes']} B  entry=0x{le['entry']:x}  recv +{le['recv_at_ms']/1000:.1f}s")
    else:
        print('last ELF  (none uploaded)')
    slots = info.get('slots') or {}
    for s in ('step', 'render', 'gpio', 'fitness'):
        print(f"slot:{s:<8s} {slots.get(s, '?')}")
    return 0


def cmd_push(args) -> int:
    blob = Path(args.elf).read_bytes()
    if blob[:4] != b'\x7fELF':
        print(f'{args.elf}: not an ELF', file=sys.stderr)
        return 1
    status, body = _http(
        'POST', f'{args.device}/load-elf',
        data=blob, headers={'Content-Type': 'application/octet-stream'},
    )
    print(f'/load-elf {status}: {body}', end='')
    if status != 200:
        return 2

    if args.slot:
        slot_data = f'slot={args.slot}'.encode()
        s2, b2 = _http(
            'POST', f'{args.device}/run-elf',
            data=slot_data,
            headers={'Content-Type': 'application/x-www-form-urlencoded'},
        )
        print(f'/run-elf  {s2}: {b2}', end='')
        if s2 != 200:
            return 3
    return 0


def cmd_compile_push(args) -> int:
    if not XCC700.is_file():
        print(f'xcc700 binary missing at {XCC700}; run its build.sh',
              file=sys.stderr)
        return 1
    workdir = Path(tempfile.mkdtemp(prefix='hexca-bench-'))
    try:
        src_path = workdir / 'src.c'
        elf_path = workdir / 'src.elf'
        src_path.write_bytes(Path(args.source).read_bytes())
        try:
            proc = subprocess.run(
                [str(XCC700), str(src_path), '-o', str(elf_path)],
                cwd=workdir, capture_output=True, timeout=10.0,
            )
        except subprocess.TimeoutExpired:
            print('xcc700 timed out', file=sys.stderr)
            return 1
        sys.stdout.write(proc.stdout.decode('utf-8', errors='replace'))
        if proc.returncode != 0 or not elf_path.is_file():
            sys.stderr.write(proc.stderr.decode('utf-8', errors='replace'))
            return 2

        # Re-use the push code path.
        args.elf = str(elf_path)
        return cmd_push(args)
    finally:
        shutil.rmtree(workdir, ignore_errors=True)


def cmd_reset(args) -> int:
    status, body = _http('POST', f'{args.device}/reset-slots',
                         data=b'', headers={})
    print(f'/reset-slots {status}: {body}', end='')
    return 0 if status == 200 else 2


def cmd_rehunt(args) -> int:
    print(f'/rehunt — blocking 10-30 s while the GA runs …')
    status, body = _http('POST', f'{args.device}/rehunt',
                         data=b'', timeout=60.0)
    print(f'/rehunt {status}: {body}', end='')
    return 0 if status == 200 else 2


def cmd_wifi_provision(args) -> int:
    body = urllib.parse.urlencode({'ssid': args.ssid,
                                   'password': args.password}).encode()
    status, resp = _http(
        'POST', f'{args.device}/wifi',
        data=body,
        headers={'Content-Type': 'application/x-www-form-urlencoded'},
    )
    print(f'/wifi {status}: {resp}', end='')
    return 0 if status == 200 else 2


def cmd_watch(args) -> int:
    while True:
        status, body = _http('GET', f'{args.device}/info', timeout=3.0)
        ts = time.strftime('%H:%M:%S')
        if status == 200:
            try:
                info = json.loads(body)
                slots = info.get('slots') or {}
                slot_str = ' '.join(
                    f'{s}={slots.get(s, "?")[0]}'
                    for s in ('step', 'render', 'gpio', 'fitness')
                )
                print(f'{ts}  uptime={info["uptime_s"]}s  '
                      f'heap={info["free_heap"]}B  {slot_str}')
            except Exception:
                print(f'{ts}  {body[:80]}')
        else:
            print(f'{ts}  unreachable ({status})')
        time.sleep(args.interval)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog='hexca_bench',
                                     description=__doc__,
                                     formatter_class=argparse.RawTextHelpFormatter)
    parser.add_argument('--device', default=DEFAULT_DEVICE,
                        help=f'base URL (default {DEFAULT_DEVICE})')
    sub = parser.add_subparsers(dest='cmd', required=True)

    sub.add_parser('info', help='pretty-print GET /info')

    p_push = sub.add_parser('push', help='POST a precompiled ELF')
    p_push.add_argument('elf')
    p_push.add_argument('slot', nargs='?', default='',
                        choices=['', 'step', 'render', 'gpio', 'fitness'])

    p_cp = sub.add_parser('compile-push',
                          help='compile C with xcc700 + push, optionally to slot')
    p_cp.add_argument('source')
    p_cp.add_argument('slot', nargs='?', default='',
                      choices=['', 'step', 'render', 'gpio', 'fitness'])

    sub.add_parser('reset', help='POST /reset-slots')
    sub.add_parser('rehunt', help='POST /rehunt (blocks 10-30 s)')

    p_wifi = sub.add_parser('wifi-provision', help='POST /wifi')
    p_wifi.add_argument('ssid')
    p_wifi.add_argument('password')

    p_watch = sub.add_parser('watch', help='poll /info on a loop')
    p_watch.add_argument('--interval', type=float, default=2.0)

    args = parser.parse_args(argv)
    args.device = args.device.rstrip('/')
    handler = {
        'info': cmd_info, 'push': cmd_push, 'compile-push': cmd_compile_push,
        'reset': cmd_reset, 'rehunt': cmd_rehunt,
        'wifi-provision': cmd_wifi_provision, 'watch': cmd_watch,
    }[args.cmd]
    return handler(args)


if __name__ == '__main__':
    raise SystemExit(main())
