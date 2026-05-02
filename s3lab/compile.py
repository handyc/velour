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
        'slug': 'slot_render_grayscale',
        'name': 'Slot: render — collapse to grayscale',
        'src': '''// Phase 3.5 RENDER slot ABI — pure data out, no symbol bridge:
//     void render(char *prev, char *cur, char *rgb565)
// rgb565 is 256*2 = 512 bytes (one RGB565 colour per cell, low byte
// first). Write 0xFF 0xFF to leave the TFT cell untouched. The
// firmware blits this buffer to the ST7735S — no tft.fillRect call
// from your code.
//
// This example collapses K=4 colours to 4 grayscale shades:
//   c=0 -> 0x0000 (black)
//   c=1 -> 0x52AA (dark grey)
//   c=2 -> 0xA554 (light grey)
//   c=3 -> 0xFFFF (white) — but 0xFFFF is the SKIP sentinel, so we
//                          use 0xFFFE for c=3 white.

void render(char *prev, char *cur, char *rgb565) {
    int i = 0;
    while (i < 256) {
        int v = cur[i] & 3;
        int c = 0;
        if (v == 1) c = 0x52AA;
        if (v == 2) c = 0xA554;
        if (v == 3) c = 0xFFFE;
        rgb565[i*2]     = c & 0xFF;
        rgb565[i*2 + 1] = (c >> 8) & 0xFF;
        i = i + 1;
    }
}
''',
    },
    {
        'slug': 'slot_render_diff_only',
        'name': 'Slot: render — diff-only (skip unchanged cells)',
        'src': '''// RENDER slot, diff-mode. Walk every cell; if it didn't change
// since the previous tick, write the SKIP sentinel (0xFF 0xFF)
// so the firmware leaves that pixel alone. For changed cells,
// emit a neon-cyan colour (RGB565 0x07FF) so updates flash.
// Useful for catching subtle motion in nearly-still patterns.

void render(char *prev, char *cur, char *rgb565) {
    int i = 0;
    while (i < 256) {
        if (prev[i] == cur[i]) {
            rgb565[i*2]     = 0xFF;
            rgb565[i*2 + 1] = 0xFF;       // SKIP
        }
        if (prev[i] != cur[i]) {
            rgb565[i*2]     = 0xFF;
            rgb565[i*2 + 1] = 0x07;       // 0x07FF cyan, low-first
        }
        i = i + 1;
    }
}
''',
    },
    {
        'slug': 'slot_gpio_xor',
        'name': 'Slot: gpio — XOR cell parity into pin levels',
        'src': '''// Phase 3.5 GPIO slot ABI — pure data out:
//     void gpio(char *grid, char *levels)
// levels is an array of HIGH (1) / LOW (0) values, one entry per
// configured output binding. The firmware reads bindings[] (a
// read-only fixed array) to know which cell maps to which pin —
// this slot just decides the level. Default is bindings[i].state_mask
// & (1 << cell_value).
//
// This example drives every output pin from the XOR-parity of the
// cells in its row, so a single pin reflects "is row N's parity 1?".
// Useful for collapsing a 16x16 grid into a quick logic vector.

void gpio(char *grid, char *levels) {
    int i = 0;
    // We can't read n_bindings from here (no symbol bridge). Drive
    // up to MAX_BINDINGS=64 entries; firmware truncates to the real
    // n_bindings when it does the digitalWrites.
    while (i < 64) {
        int row = i & 15;            // 16-row wrap; lets pins 16..63 mirror 0..15
        int p = 0;
        int x = 0;
        while (x < 16) {
            p = p ^ (grid[row * 16 + x] & 1);
            x = x + 1;
        }
        levels[i] = p;
        i = i + 1;
    }
}
''',
    },
    {
        'slug': 'slot_fitness_density',
        'name': 'Slot: fitness — reward 50/50 cell density',
        'src': '''// Phase 4 FITNESS slot ABI:
//     int fitness(char *genome, int grid_seed)
// Higher = better. xcc700 has no float, so the score is an int;
// the firmware divides by 10000 to scale to the GA's expected
// dynamic range. A typical default returns 0..50000 (= 0.0..5.0
// in the original double impl).
//
// This example rewards rules whose final grid has roughly equal
// counts of all four colours — a "balanced" CA. It runs no
// simulation; it just looks at the genome's lookup-table outputs
// and counts how often each output appears. Diverse outputs
// score higher; degenerate "always-output-0" rules score zero.

int fitness(char *genome, int grid_seed) {
    int counts0 = 0;
    int counts1 = 0;
    int counts2 = 0;
    int counts3 = 0;
    int idx = 0;
    while (idx < 16384) {
        int byte_i = idx / 4;
        int bit_i  = (idx & 3) * 2;
        int v = (genome[byte_i] >> bit_i) & 3;
        if (v == 0) counts0 = counts0 + 1;
        if (v == 1) counts1 = counts1 + 1;
        if (v == 2) counts2 = counts2 + 1;
        if (v == 3) counts3 = counts3 + 1;
        idx = idx + 1;
    }
    // Score peaks when each count is ~4096 (16384/4). Distance from
    // 4096 penalises imbalance; absolute value via if-else.
    int d0 = counts0 - 4096; if (d0 < 0) d0 = 0 - d0;
    int d1 = counts1 - 4096; if (d1 < 0) d1 = 0 - d1;
    int d2 = counts2 - 4096; if (d2 < 0) d2 = 0 - d2;
    int d3 = counts3 - 4096; if (d3 < 0) d3 = 0 - d3;
    int total = d0 + d1 + d2 + d3;
    // Max imbalance is 16384 (all one colour); zero is perfect.
    return 50000 - (total * 3);
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
