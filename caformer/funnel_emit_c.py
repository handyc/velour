"""Emit a standalone C source for the word_binder_v2 pipeline.

Packages:
- the hex K=4 step (with row-parity pointy-top neighbours, toroidal)
- all per-(slot, pos, cell) LUTs as static const arrays
- the vocab table as a C string array
- a main() that takes the prompt on argv and prints the response

No external dependencies beyond libc.  Output is bit-for-bit
identical to the Python word_binder_v2 because the CA dynamics are
deterministic and the LUTs are the same bytes.
"""
from __future__ import annotations

import io
import json
import textwrap
from pathlib import Path


C_HEADER = r"""/*  funnel-cli — auto-generated standalone CA-LLM (word_binder_v2)
 *
 *  Generated from a trained caformer.word_binder_v2 model.  No external
 *  dependencies beyond libc.  Pipeline:
 *
 *    argv[1..]  → tokenize on whitespace
 *    for each prompt word (up to MAX_SLOTS):
 *        embed word → SIDE×SIDE K=4 board (4 base-4 digits per byte)
 *        for each output position (up to MAX_OUT):
 *            for each decoder cell c in 0..K_CELLS-1:
 *                run hex_step TICKS times on the embedded board
 *                using LUT[slot, pos, cell] → read cell (0, 0)
 *            assemble base-4 digits → word ID
 *            if word ID == STOP_ID: break
 *            else: print vocab[word ID] (with leading space if not first)
 *        endfor
 *    endfor
 *
 *  Build:   cc -O2 -o funnel-cli funnel-cli.c
 *  Run:     ./funnel-cli "look up cats"
 *
 *  This file is a literal repackage of the live web demo's pipeline —
 *  same LUT bytes, same CA dynamics, same vocab.  The chains were
 *  evolved by per-cell GAs; this binary just *runs* them.
 *
 *  LUTs are stored *packed* — 4 cells/byte (2 bits each) — so each LUT
 *  costs 4096 bytes of static data instead of 16384.  unpack_lut()
 *  inflates them into RAM at startup.  4× smaller binary, identical
 *  runtime behaviour.
 */
#include <stdio.h>
#include <string.h>
#include <stdlib.h>

#define SIDE             8
#define N_CELLS          (SIDE * SIDE)
#define LUT_SIZE         16384       /* 4^7 */
#define PACKED_LUT_SIZE  4096        /* 4 cells per byte */
#define STOP_ID          0
#define UNK_ID           1
"""


C_HEX_STEP = r"""
typedef unsigned char u8;

static u8 board[N_CELLS], next_board[N_CELLS];

/* hex_ca_step: K=4 pointy-top hex with row-parity neighbourhood,
 * toroidal boundary.  Identical key encoding to Python's
 * caformer.primitives.hex_ca_step:
 *   key = self<<12 | NW<<10 | NE<<8 | R<<6 | SE<<4 | SW<<2 | L      */
static void hex_step(u8 *state, const u8 *lut) {
    for (int r = 0; r < SIDE; r++) {
        int r_up = (r - 1 + SIDE) % SIDE;
        int r_dn = (r + 1) % SIDE;
        int even = (r & 1) == 0;
        for (int c = 0; c < SIDE; c++) {
            int c_l = (c - 1 + SIDE) % SIDE;
            int c_r = (c + 1) % SIDE;
            u8 self  = state[r    * SIDE + c];
            u8 n_l   = state[r    * SIDE + c_l];
            u8 n_r   = state[r    * SIDE + c_r];
            u8 n_nw  = even ? state[r_up * SIDE + c_l] : state[r_up * SIDE + c];
            u8 n_ne  = even ? state[r_up * SIDE + c]   : state[r_up * SIDE + c_r];
            u8 n_sw  = even ? state[r_dn * SIDE + c_l] : state[r_dn * SIDE + c];
            u8 n_se  = even ? state[r_dn * SIDE + c]   : state[r_dn * SIDE + c_r];
            unsigned key = ((unsigned)self << 12)
                         | ((unsigned)n_nw << 10)
                         | ((unsigned)n_ne << 8)
                         | ((unsigned)n_r  << 6)
                         | ((unsigned)n_se << 4)
                         | ((unsigned)n_sw << 2)
                         | (unsigned)n_l;
            next_board[r * SIDE + c] = lut[key];
        }
    }
    memcpy(state, next_board, N_CELLS);
}

static void run_ticks(const u8 *lut, int ticks) {
    for (int t = 0; t < ticks; t++) hex_step(board, lut);
}

/* embed_word: 4 base-4 digits per byte, top-left layout.  Matches
 * Python's _embed_word exactly. */
static void embed_word(const char *word) {
    memset(board, 0, N_CELLS);
    int max_bytes = N_CELLS / 4;
    int n = (int)strlen(word);
    if (n > max_bytes) n = max_bytes;
    for (int i = 0; i < n; i++) {
        unsigned b = (unsigned char)word[i];
        board[i * 4 + 0] = (b >> 6) & 3;
        board[i * 4 + 1] = (b >> 4) & 3;
        board[i * 4 + 2] = (b >> 2) & 3;
        board[i * 4 + 3] =  b       & 3;
    }
}

/* Unpack a 4096-byte packed LUT into 16384 cells (2 bits per cell).
 * Same convention as spoeqi.metachain.pack_k4_stream. */
static void unpack_lut(const u8 *packed, u8 *out) {
    for (int i = 0; i < PACKED_LUT_SIZE; i++) {
        u8 b = packed[i];
        out[4*i+0] = (b >> 6) & 3;
        out[4*i+1] = (b >> 4) & 3;
        out[4*i+2] = (b >> 2) & 3;
        out[4*i+3] =  b       & 3;
    }
}
"""


def _pack_lut(raw: bytes) -> bytes:
    """Pack 16,384-byte LUT (values 0..3) into 4,096 bytes, 4 cells/byte.
    Same convention as spoeqi.metachain.pack_k4_stream."""
    if len(raw) != 16384:
        raise ValueError(f'expected 16384 bytes, got {len(raw)}')
    out = bytearray(4096)
    for i in range(4096):
        out[i] = (((raw[4*i+0] & 3) << 6)
                | ((raw[4*i+1] & 3) << 4)
                | ((raw[4*i+2] & 3) << 2)
                |  (raw[4*i+3] & 3))
    return bytes(out)


def _emit_packed_lut_array(name: str, raw_data: bytes) -> str:
    """Emit `static const u8 packed_name[PACKED_LUT_SIZE] = {...};`.
    Source line carries 32 bytes for readability."""
    packed = _pack_lut(raw_data)
    out = [f'static const u8 packed_{name}[PACKED_LUT_SIZE] = {{']
    for i in range(0, len(packed), 32):
        chunk = packed[i:i+32]
        out.append('    ' + ','.join(str(b) for b in chunk) + ',')
    out.append('};')
    return '\n'.join(out)


def _c_string_literal(s: str) -> str:
    """C-quote a string with proper escaping for control chars and quotes."""
    parts = ['"']
    for b in s.encode('utf-8'):
        if b == ord('"'):
            parts.append('\\"')
        elif b == ord('\\'):
            parts.append('\\\\')
        elif b == 0x0A:
            parts.append('\\n')
        elif b == 0x0D:
            parts.append('\\r')
        elif b == 0x09:
            parts.append('\\t')
        elif 32 <= b < 127:
            parts.append(chr(b))
        else:
            parts.append(f'\\x{b:02x}')
    parts.append('"')
    return ''.join(parts)


def emit_word_binder_v2_c(model_dir: Path) -> str:
    """Build the complete C source from a word_binder_v2 model directory.
    Returns the C source as a string ready to write to disk + compile."""
    model_dir = Path(model_dir)
    meta = json.loads((model_dir / 'vocab.json').read_text())
    words = meta['words']
    k_cells = meta['k_cells']
    max_slots = meta.get('max_slots', 8)
    max_out = meta.get('max_out', 6)
    ticks = meta.get('ticks', 6)

    # Discover all (s, p) chains on disk.
    chains: dict[tuple[int, int], dict[int, bytes]] = {}
    for f in sorted(model_dir.glob('chain_s*_p*_c*.lut')):
        parts = f.stem.split('_')
        s, p, c = int(parts[1][1:]), int(parts[2][1:]), int(parts[3][1:])
        chains.setdefault((s, p), {})[c] = f.read_bytes()

    out = io.StringIO()
    out.write(C_HEADER)
    out.write(f'#define K_CELLS   {k_cells}\n')
    out.write(f'#define MAX_SLOTS {max_slots}\n')
    out.write(f'#define MAX_OUT   {max_out}\n')
    out.write(f'#define TICKS     {ticks}\n')
    out.write(f'#define VOCAB_SZ  {len(words)}\n')
    out.write(C_HEX_STEP)
    out.write('\n/* ── Per-(slot, pos, cell) LUTs ─────────────────────── */\n')

    # Emit each LUT as a *packed* static const array (4× smaller).
    chain_keys = sorted(chains.keys())
    lut_names: dict[tuple[int, int, int], str] = {}
    for (s, p) in chain_keys:
        cells = chains[(s, p)]
        if any(c not in cells for c in range(k_cells)):
            raise ValueError(f'chain (slot {s}, pos {p}) missing cells')
        for c in range(k_cells):
            name = f'lut_s{s:02d}_p{p:02d}_c{c}'
            lut_names[(s, p, c)] = name
            out.write('\n')
            out.write(_emit_packed_lut_array(name, cells[c]))
            out.write('\n')

    # Pointer table to packed LUTs, plus a runtime-allocated unpacked
    # buffer so the hot path reads single-byte LUT entries.
    out.write('\n/* ── Packed-LUT pointer table (NULL = untrained) ────── */\n')
    out.write('static const u8 *packed_chain_table[MAX_SLOTS][MAX_OUT][K_CELLS] = {\n')
    for s in range(max_slots):
        out.write(f'    /* slot {s} */ {{\n')
        for p in range(max_out):
            row = '        { '
            for c in range(k_cells):
                if (s, p, c) in lut_names:
                    row += f'packed_{lut_names[(s, p, c)]}, '
                else:
                    row += 'NULL, '
            row += '},'
            out.write(row + '\n')
        out.write('    },\n')
    out.write('};\n')

    # Runtime unpacked-LUT buffers, allocated once at startup.
    out.write('\n/* Unpacked LUT buffers, populated at startup. */\n')
    out.write('static u8 unpacked_chain_storage'
              '[MAX_SLOTS][MAX_OUT][K_CELLS][LUT_SIZE];\n')
    out.write('static const u8 *chain_table[MAX_SLOTS][MAX_OUT][K_CELLS];\n')
    out.write(r'''
static void init_chain_table(void) {
    for (int s = 0; s < MAX_SLOTS; s++)
        for (int p = 0; p < MAX_OUT; p++)
            for (int c = 0; c < K_CELLS; c++) {
                const u8 *pk = packed_chain_table[s][p][c];
                if (pk) {
                    unpack_lut(pk, unpacked_chain_storage[s][p][c]);
                    chain_table[s][p][c] = unpacked_chain_storage[s][p][c];
                } else {
                    chain_table[s][p][c] = NULL;
                }
            }
}
''')

    # Vocab strings.
    out.write('\n/* ── Vocab (word IDs → strings) ─────────────────────── */\n')
    out.write(f'static const char *vocab[VOCAB_SZ] = {{\n')
    for i, w in enumerate(words):
        comment = ''
        if i == 0:
            comment = '    /* STOP */'
        elif i == 1:
            comment = '    /* UNK */'
        out.write(f'    {_c_string_literal(w)},{comment}\n')
    out.write('};\n')

    # main()
    out.write(r'''
/* ── Main: argv → prompt → tokenize → run chains → print ─────────── */

static int decode_word_id(int slot, int pos) {
    /* Run K_CELLS chains for (slot, pos), assemble base-4 word ID.
     * board[] is set to the embedded prompt word before calling. */
    int wid = 0;
    u8 saved[N_CELLS];
    memcpy(saved, board, N_CELLS);
    for (int c = 0; c < K_CELLS; c++) {
        const u8 *lut = chain_table[slot][pos][c];
        if (!lut) return STOP_ID;
        memcpy(board, saved, N_CELLS);
        run_ticks(lut, TICKS);
        wid = (wid << 2) | (board[0] & 3);
    }
    return wid;
}

int main(int argc, char **argv) {
    init_chain_table();
    if (argc < 2) {
        fprintf(stderr, "usage: %s <prompt words…>\n", argv[0]);
        return 2;
    }
    /* Join argv[1..] with spaces, then tokenize on whitespace. */
    int prompt_cap = 1;
    for (int i = 1; i < argc; i++) prompt_cap += (int)strlen(argv[i]) + 1;
    char *prompt = (char*)malloc(prompt_cap);
    prompt[0] = 0;
    for (int i = 1; i < argc; i++) {
        if (i > 1) strcat(prompt, " ");
        strcat(prompt, argv[i]);
    }

    /* Tokenize.  Replace each whitespace with NUL and collect word ptrs. */
    char *words_buf = strdup(prompt);
    char *toks[MAX_SLOTS];
    int n_toks = 0;
    char *save;
    for (char *t = strtok_r(words_buf, " \t\n", &save);
              t && n_toks < MAX_SLOTS;
              t = strtok_r(NULL, " \t\n", &save)) {
        toks[n_toks++] = t;
    }

    int printed = 0;
    for (int s = 0; s < n_toks; s++) {
        embed_word(toks[s]);
        u8 word_embed[N_CELLS];
        memcpy(word_embed, board, N_CELLS);
        for (int p = 0; p < MAX_OUT; p++) {
            if (!chain_table[s][p][0]) break;
            memcpy(board, word_embed, N_CELLS);
            int wid = decode_word_id(s, p);
            if (wid == STOP_ID) break;
            if (wid >= VOCAB_SZ) wid = UNK_ID;
            const char *tok = vocab[wid];
            if (tok && tok[0]) {
                if (printed++) fputc(' ', stdout);
                fputs(tok, stdout);
            }
        }
    }
    fputc('\n', stdout);
    free(words_buf);
    free(prompt);
    return 0;
}
''')
    return out.getvalue()
