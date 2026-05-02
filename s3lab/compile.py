"""xcc700 subprocess wrapper.

Phase 1 of the on-device-compile arc: compile a C source string to a
relocatable Xtensa LX7 ELF via the vendored xcc700 binary at
``isolation/artifacts/xcc700/xcc700``.

Constraints enforced before invocation:
  * source must be valid UTF-8
  * source ≤ 64 KiB (the parser is single-pass; longer files are
    almost certainly accidents)
  * runtime ≤ 5 s wall clock (xcc700 self-host completes in <1 s; if
    it stalls, something's wrong)

The compiler runs in a private temp dir; the ELF is read back into
memory and the dir wiped. No file leaves the temp dir.

Returns a ``CompileResult`` dataclass so the view can render either
the build log (success) or the diagnostic line (failure) without
guessing.
"""
from __future__ import annotations

import dataclasses
import shutil
import subprocess
import tempfile
from pathlib import Path

from django.conf import settings


XCC700_DIR = settings.BASE_DIR / 'isolation' / 'artifacts' / 'xcc700'
XCC700_BIN = XCC700_DIR / 'xcc700'

MAX_SOURCE_BYTES = 64 * 1024
COMPILE_TIMEOUT_S = 5.0


@dataclasses.dataclass
class CompileResult:
    ok: bool
    elf: bytes | None
    build_log: str
    error: str
    source_bytes: int
    elf_bytes: int
    elapsed_ms: int


def compile_c(source: str) -> CompileResult:
    """Compile ``source`` (C99 subset) to Xtensa LX7 ELF."""
    if not XCC700_BIN.is_file():
        return CompileResult(
            ok=False, elf=None,
            build_log='',
            error=f'xcc700 binary missing at {XCC700_BIN}. '
                  f'Run isolation/artifacts/xcc700/build.sh first.',
            source_bytes=0, elf_bytes=0, elapsed_ms=0,
        )

    src_bytes = source.encode('utf-8', errors='replace')
    if len(src_bytes) > MAX_SOURCE_BYTES:
        return CompileResult(
            ok=False, elf=None,
            build_log='',
            error=f'source is {len(src_bytes)} bytes; '
                  f'max is {MAX_SOURCE_BYTES} bytes',
            source_bytes=len(src_bytes), elf_bytes=0, elapsed_ms=0,
        )

    workdir = Path(tempfile.mkdtemp(prefix='xcc700-'))
    src_path = workdir / 'src.c'
    elf_path = workdir / 'src.elf'
    try:
        src_path.write_bytes(src_bytes)
        try:
            proc = subprocess.run(
                [str(XCC700_BIN), str(src_path), '-o', str(elf_path)],
                cwd=workdir,
                capture_output=True,
                timeout=COMPILE_TIMEOUT_S,
                check=False,
            )
        except subprocess.TimeoutExpired:
            return CompileResult(
                ok=False, elf=None,
                build_log='',
                error=f'xcc700 timed out after {COMPILE_TIMEOUT_S}s',
                source_bytes=len(src_bytes), elf_bytes=0,
                elapsed_ms=int(COMPILE_TIMEOUT_S * 1000),
            )

        stdout = proc.stdout.decode('utf-8', errors='replace')
        stderr = proc.stderr.decode('utf-8', errors='replace')
        # xcc700 prints its build summary on stdout and any error on
        # stderr. Try to parse elapsed_ms from the stdout footer
        # (looks like: "[ 18 ms ] >> 277 Lines/sec <<").
        elapsed_ms = 0
        for line in stdout.splitlines():
            line = line.strip()
            if line.startswith('[') and 'ms' in line and ']' in line:
                try:
                    elapsed_ms = int(line.split('[')[1].split('ms')[0].strip())
                except (IndexError, ValueError):
                    pass
                break

        if proc.returncode != 0 or not elf_path.is_file():
            err = (stderr.strip() or stdout.strip() or
                   f'xcc700 returned {proc.returncode}')
            return CompileResult(
                ok=False, elf=None,
                build_log=stdout,
                error=err,
                source_bytes=len(src_bytes), elf_bytes=0,
                elapsed_ms=elapsed_ms,
            )

        elf = elf_path.read_bytes()
        # Sanity: the ELF magic should be \x7fELF and the machine type
        # should be Tensilica Xtensa (e_machine = 0x5e, little-endian).
        if len(elf) < 20 or elf[:4] != b'\x7fELF':
            return CompileResult(
                ok=False, elf=None,
                build_log=stdout,
                error='xcc700 produced a file without ELF magic',
                source_bytes=len(src_bytes), elf_bytes=len(elf),
                elapsed_ms=elapsed_ms,
            )
        # e_machine is at offset 18 (uint16 LE).
        e_machine = elf[18] | (elf[19] << 8)
        if e_machine != 0x5e:
            return CompileResult(
                ok=False, elf=None,
                build_log=stdout,
                error=f'unexpected e_machine 0x{e_machine:04x} '
                      f'(expected 0x005e Tensilica Xtensa)',
                source_bytes=len(src_bytes), elf_bytes=len(elf),
                elapsed_ms=elapsed_ms,
            )

        return CompileResult(
            ok=True, elf=elf,
            build_log=stdout,
            error='',
            source_bytes=len(src_bytes), elf_bytes=len(elf),
            elapsed_ms=elapsed_ms,
        )
    finally:
        shutil.rmtree(workdir, ignore_errors=True)


# ── Examples surfaced in the editor page ──────────────────────────

EXAMPLES = [
    {
        'slug': 'minimal',
        'name': 'Minimal — return 42',
        'src': '''int main() {
    int x = 42;
    return x;
}
''',
    },
    {
        'slug': 'add',
        'name': 'Function call — add two ints',
        'src': '''int add(int a, int b) {
    return a + b;
}

int main() {
    int s = add(3, 4);
    return s;
}
''',
    },
    {
        'slug': 'while',
        'name': 'Loop — sum 1..10',
        'src': '''int main() {
    int i = 1;
    int sum = 0;
    while (i < 11) {
        sum = sum + i;
        i = i + 1;
    }
    return sum;
}
''',
    },
    {
        'slug': 'pointer',
        'name': 'Pointer — write through *p',
        'src': '''int main() {
    int x = 0;
    int* p = &x;
    *p = 99;
    return x;
}
''',
    },
    {
        'slug': 'slot_step_identity',
        'name': 'Slot: step — identity (output == input)',
        'src': '''// Phase 3 hot-swap target: STEP slot ABI.
// Device signature is:
//     void step(char *genome, char *in, char *out)
// where genome is 4096 B, in/out are GRID_W*GRID_H = 256 B each.
// This identity step copies cur to next; the CA freezes in place.
// POST this ELF to /run-elf?slot=step on the supermini fork.

void step(char *genome, char *in, char *out) {
    int i = 0;
    while (i < 256) {
        out[i] = in[i];
        i = i + 1;
    }
}
''',
    },
    {
        'slug': 'slot_step_invert',
        'name': 'Slot: step — color-invert (xor 3)',
        'src': '''// STEP slot, color-invert variant. Each cell's next
// state is its current state XOR 3, so K=4 colours flip pairwise:
// 0<->3, 1<->2. The CA loses the genome's actual rule and just
// strobes between two complementary patterns. Useful as a sanity
// check that a loaded slot is actually being called.

void step(char *genome, char *in, char *out) {
    int i = 0;
    while (i < 256) {
        out[i] = in[i] ^ 3;
        i = i + 1;
    }
}
''',
    },
    {
        'slug': 'slot_step_genome',
        'name': 'Slot: step — re-implement the canonical hex CA',
        'src': '''// STEP slot, the real thing: re-implement the same hex
// CA step the firmware ships with. Reads the K=4 genome (2 bits
// per situation, 4096 bytes), looks up (self, n0..n5), writes
// the output. xcc700 has no preprocessor + no for + no struct,
// so all constants are inline and the loops are while-form.

int neighbor(char *in, int y, int x, int dy, int dx) {
    int yy = y + dy;
    int xx = x + dx;
    if (yy < 0) return 0;
    if (yy > 15) return 0;
    if (xx < 0) return 0;
    if (xx > 15) return 0;
    return in[yy * 16 + xx];
}

void step(char *genome, char *in, char *out) {
    int y = 0;
    while (y < 16) {
        int even = ((y & 1) == 0);
        int x = 0;
        while (x < 16) {
            int self = in[y * 16 + x];
            int n0 = neighbor(in, y, x, -1, 0);
            int n3 = neighbor(in, y, x, 1, 0);
            int n1 = 0;
            int n2 = 0;
            int n4 = 0;
            int n5 = 0;
            if (even != 0) {
                n1 = neighbor(in, y, x, -1, 1);
                n2 = neighbor(in, y, x,  0, 1);
                n4 = neighbor(in, y, x,  0, -1);
                n5 = neighbor(in, y, x, -1, -1);
            }
            if (even == 0) {
                n1 = neighbor(in, y, x,  0, 1);
                n2 = neighbor(in, y, x,  1, 1);
                n4 = neighbor(in, y, x,  1, -1);
                n5 = neighbor(in, y, x,  0, -1);
            }
            int idx = self * 4096
                    + n0   * 1024
                    + n1   * 256
                    + n2   * 64
                    + n3   * 16
                    + n4   * 4
                    + n5;
            int byte_i = idx / 4;
            int bit_i  = (idx & 3) * 2;
            out[y * 16 + x] = (genome[byte_i] >> bit_i) & 3;
            x = x + 1;
        }
        y = y + 1;
    }
}
''',
    },
]
