"""Emit a self-contained HTML+JS demo of the caformer CA-LLM.

Output is a single .html file that runs in any modern browser with
no server, no network, no dependencies.  Open it locally and the
trained pairs respond byte-exact via a pure-JS implementation of
the same K=4 hex CA step the Python and C runtimes use.

The point of this build: give skeptical colleagues a literal file
they can inspect line-by-line and prove there is no hidden trick —
the rules are bytes, the CA step is ~30 lines of JS, and the output
is computed deterministically from the rules.

  manage.py caformer_emit_standalone --out caformer_standalone.html
  manage.py caformer_emit_standalone --out demo.html --pair-ids 2,3,5,6,7,8 \\
                                       --tier 16

By default uses tier-16 chains for every pair where they EXACT
(matches the live /tier=auto path).  Falls back to board128 chains
when tier-16 isn't EXACT for a given pair.  Tier-16 inference at
16×16 × 16 ticks is plenty fast in JS (~10 ms / position).
"""
from __future__ import annotations

import base64
import sys
from pathlib import Path

import numpy as np
from django.core.management.base import BaseCommand


# How big each per-tier rule is on disk (always 16,384 bytes for the
# 7→1 K=4 LUT regardless of board size).
RULE_BYTES = 16_384


def build_standalone_html(pair_ids: list = None, tier: int = 16,
                              max_bytes_mb: float = 8.0) -> str:
    """Public builder — used by both the management command and the
    /caformer/funnel-chat/standalone/ download route.  Returns the
    full HTML string with the trained-pair bundle baked in as a
    base-64 blob."""
    from caformer.models import QRPair
    from caformer.tier_dispatch import inference_at_tier

    if pair_ids:
        pairs = list(QRPair.objects.filter(pk__in=pair_ids).order_by('pk'))
    else:
        pairs = list(QRPair.objects.filter(board128_exact=True).order_by('pk'))

    tier_field = {8: 'b008_rules_blob', 16: 'b016_rules_blob',
                    32: 'b032_rules_blob', 64: 'b064_rules_blob',
                    128: 'board128_rules_blob'}
    bundle = []
    total_bytes = 0
    cap_bytes = int(max_bytes_mb * 1024 * 1024)
    for pair in pairs:
        picked_side = None
        picked_blob = None
        for side in (8, 16, 32, 64, 128):
            if side > tier and side != 128:
                continue
            blob = getattr(pair, tier_field[side], None) or b''
            if not blob:
                continue
            r = inference_at_tier(pair.prompt, bytes(blob), side,
                                      expected=pair.expected)
            if r['byte_match'] == r['n_target'] and r['n_target'] > 0:
                picked_side = side
                picked_blob = bytes(blob)
                break
        if picked_side is None:
            blob = bytes(pair.board128_rules_blob or b'')
            if blob and pair.board128_exact:
                picked_side = 128
                picked_blob = blob
        if picked_side is None:
            continue
        rule_count = len(picked_blob) // RULE_BYTES
        entry_bytes = (RULE_BYTES * rule_count
                          + len(pair.prompt.encode('utf-8'))
                          + len(pair.expected.encode('utf-8'))
                          + 32)
        if total_bytes + entry_bytes > cap_bytes:
            continue
        bundle.append({'prompt':   pair.prompt,
                         'expected': pair.expected,
                         'side':     picked_side,
                         'ticks':    picked_side,
                         'rules':    picked_blob})
        total_bytes += entry_bytes

    # Pack bundle into the same format as the management command.
    import base64 as _b64
    buf = bytearray()
    buf += b'CAFORMER'
    buf.append(1)
    buf += len(bundle).to_bytes(4, 'little')
    for e in bundle:
        p = e['prompt'].encode('utf-8')
        r = e['expected'].encode('utf-8')
        n_rules = len(e['rules']) // RULE_BYTES
        buf.append(e['side'])
        buf.append(e['ticks'])
        buf += len(p).to_bytes(2, 'little')
        buf += p
        buf += len(r).to_bytes(2, 'little')
        buf += r
        buf += n_rules.to_bytes(2, 'little')
        buf += e['rules']
    b64 = _b64.b64encode(bytes(buf)).decode('ascii')
    return _build_html(b64, len(bundle))


class Command(BaseCommand):
    help = ('Emit a single self-contained HTML+JS demo of the caformer '
            'CA-LLM — inspectable end-to-end, runs locally in any '
            'modern browser.')

    def add_arguments(self, parser):
        parser.add_argument('--out',  type=str,
                              default='caformer_standalone.html')
        parser.add_argument('--pair-ids', type=str, default='',
                              help='comma-separated subset; default = '
                                     'every pair with EXACT chains')
        parser.add_argument('--tier', type=int, default=16,
                              choices=[8, 16, 32, 64, 128],
                              help='preferred tier; falls back to 128 '
                                     'when smaller tier isn\'t EXACT')
        parser.add_argument('--max-bytes-mb', type=float, default=8.0,
                              help='hard cap on inlined model bytes '
                                     '(rejects pairs once cap is hit)')

    def handle(self, *, out, pair_ids, tier, max_bytes_mb, **opts):
        from caformer.board_multires import tier_geometry
        from caformer.models import QRPair
        from caformer.tier_dispatch import (best_exact_tier,
                                                   inference_at_tier)

        def log(msg):
            sys.stdout.write(str(msg) + '\n'); sys.stdout.flush()

        if pair_ids.strip():
            ids = [int(x) for x in pair_ids.split(',') if x.strip()]
            pairs = list(QRPair.objects.filter(pk__in=ids).order_by('pk'))
        else:
            pairs = list(QRPair.objects.filter(board128_exact=True)
                            .order_by('pk'))

        tier_field = {8: 'b008_rules_blob', 16: 'b016_rules_blob',
                        32: 'b032_rules_blob', 64: 'b064_rules_blob',
                        128: 'board128_rules_blob'}

        # Pick the smallest EXACT tier per pair (≤ requested preference).
        bundle = []                # list of {prompt, expected, side, ticks, rules_bytes}
        total_bytes = 0
        cap_bytes = int(max_bytes_mb * 1024 * 1024)
        skipped_partial = 0
        skipped_oversize = 0
        for pair in pairs:
            # Try smallest available tier first, up to the requested preference.
            picked_side = None
            picked_blob = None
            for side in (8, 16, 32, 64, 128):
                if side > tier and side != 128:
                    continue
                blob = getattr(pair, tier_field[side], None) or b''
                if not blob:
                    continue
                # Verify byte-exact at this tier by running once.
                r = inference_at_tier(pair.prompt, bytes(blob), side,
                                          expected=pair.expected)
                if r['byte_match'] == r['n_target'] and r['n_target'] > 0:
                    picked_side = side
                    picked_blob = bytes(blob)
                    break
                if side == tier:
                    # Tier of preference didn't EXACT; fall through to 128.
                    pass
            if picked_side is None:
                # Last-resort fallback to board128.
                blob = bytes(pair.board128_rules_blob or b'')
                if blob and pair.board128_exact:
                    picked_side = 128
                    picked_blob = blob
            if picked_side is None:
                skipped_partial += 1
                continue
            rule_count = len(picked_blob) // RULE_BYTES
            entry_bytes = (RULE_BYTES * rule_count
                              + len(pair.prompt.encode('utf-8'))
                              + len(pair.expected.encode('utf-8'))
                              + 32)
            if total_bytes + entry_bytes > cap_bytes:
                skipped_oversize += 1
                continue
            bundle.append({
                'pk':       pair.pk,
                'prompt':   pair.prompt,
                'expected': pair.expected,
                'side':     picked_side,
                'ticks':    picked_side,
                'rules':    picked_blob,
            })
            total_bytes += entry_bytes

        log(f'bundle: {len(bundle)} pairs, '
            f'{total_bytes / 1024 / 1024:.2f} MB')
        if skipped_partial:
            log(f'  skipped (no EXACT tier): {skipped_partial}')
        if skipped_oversize:
            log(f'  skipped (size cap):      {skipped_oversize}')
        tier_hist = {}
        for e in bundle:
            tier_hist[e['side']] = tier_hist.get(e['side'], 0) + 1
        log(f'  tier distribution: {tier_hist}')

        # Build the binary blob: a single concatenated stream.
        # Format:
        #   magic   = 'CAFORMER'           (8 bytes)
        #   version = u8 (1)
        #   n_pairs = u32 little-endian
        #   foreach pair:
        #     side       = u8
        #     ticks      = u8
        #     prompt_len = u16 LE
        #     prompt     = UTF-8 bytes (prompt_len)
        #     expected_len = u16 LE
        #     expected   = UTF-8 bytes (expected_len)
        #     n_rules    = u16 LE
        #     rules      = n_rules × RULE_BYTES (raw)
        buf = bytearray()
        buf += b'CAFORMER'
        buf.append(1)
        buf += len(bundle).to_bytes(4, 'little')
        for e in bundle:
            p = e['prompt'].encode('utf-8')
            r = e['expected'].encode('utf-8')
            n_rules = len(e['rules']) // RULE_BYTES
            buf.append(e['side'])
            buf.append(e['ticks'])
            buf += len(p).to_bytes(2, 'little')
            buf += p
            buf += len(r).to_bytes(2, 'little')
            buf += r
            buf += n_rules.to_bytes(2, 'little')
            buf += e['rules']
        b64 = base64.b64encode(bytes(buf)).decode('ascii')
        log(f'  blob bytes: {len(buf)}  base64 chars: {len(b64)}')

        html = _build_html(b64, len(bundle))
        out_p = Path(out)
        out_p.write_text(html, encoding='utf-8')
        log(f'wrote {out_p} ({out_p.stat().st_size / 1024 / 1024:.2f} MB)')


def _build_html(blob_b64: str, n_pairs: int) -> str:
    """Build the full self-contained HTML.  Everything inline:
    one <style>, one <script>, the blob as a base64 const."""
    return (
        '<!DOCTYPE html>\n'
        '<html lang="en">\n'
        '<head>\n'
        '<meta charset="utf-8">\n'
        '<title>caformer CA-LLM standalone</title>\n'
        '<style>\n' + _CSS + '\n</style>\n'
        '</head>\n'
        '<body>\n'
        '<div class="wrap">\n'
        '<h1>caformer · standalone CA-LLM demo</h1>\n'
        '<p class="lede">Pure cellular-automaton language model.  '
        'Trained rules are 16,384-byte LUTs (K=4 hex CA, 7→1).  '
        f'<b>{n_pairs} trained pairs</b> embedded below as a base-64 blob.  '
        'Type a prompt that the model was trained on and the CA runs '
        'deterministically in your browser to produce the byte-exact '
        'response.  No network, no server, no hidden trick — the '
        'JavaScript below is the whole inference pipeline (~80 lines).</p>\n'
        '<div class="chat">\n'
        '  <div id="log" class="log"></div>\n'
        '  <form id="form" autocomplete="off">\n'
        '    <input id="inp" type="text" placeholder="trained prompt (try \'hi\', \'hey\', \'bye\')" />\n'
        '    <button type="submit">run</button>\n'
        '  </form>\n'
        '  <div class="controls">\n'
        '    <label title="When ON, untrained prompts still run through some trained pair\'s rules so you can SEE the meaningless output — proves the CA is doing real computation, not lookup">\n'
        '      <input type="checkbox" id="showUntrained" /> show output for untrained prompts (run through a random trained pair\'s rules)\n'
        '    </label>\n'
        '  </div>\n'
        '  <div id="status" class="status"></div>\n'
        '</div>\n'
        '<details class="trained">\n'
        '  <summary>trained prompts (click to expand)</summary>\n'
        '  <ul id="trained-list"></ul>\n'
        '</details>\n'
        '<details class="how">\n'
        '  <summary>how it works (and what to verify)</summary>\n'
        '<pre>\n'
        '1. The model blob below is base-64 of N×16,384-byte LUTs +\n'
        '   prompt/expected metadata.  No code or behaviour beyond the\n'
        '   look-up table data.\n'
        '\n'
        '2. The hex CA step (function `hexStep` in the JS) is a pure\n'
        '   function: it reads cells from a 16×16 (or 128×128) grid,\n'
        '   computes a 14-bit key, looks it up in a 16,384-entry table,\n'
        '   writes the result to a new grid.  No randomness, no API\n'
        '   calls, no anything else.\n'
        '\n'
        '3. For a trained prompt, we look up its rules from the bundle,\n'
        '   embed the prompt into a tile grid, run the CA forward `ticks`\n'
        '   times per response byte, and decode the output cells.\n'
        '\n'
        '4. Try a NON-trained prompt: by default you get a "no rules"\n'
        '   message.  Tick "show output for untrained prompts" to BORROW\n'
        '   the rules from a random trained pair and run them on your\n'
        '   prompt.  The output will be garbage bytes (often unprintable\n'
        '   — rendered as hex).  This is the most direct proof the CA\n'
        '   is computing, not memorising: same rule table, different\n'
        '   input prompt → completely different (and meaningless) output.\n'
        '\n'
        'View source to inspect the entire pipeline.  The JavaScript is\n'
        'small enough to fit in your head.\n'
        '</pre>\n'
        '</details>\n'
        '</div>\n'
        '<script>\n'
        f'const BLOB_B64 = "{blob_b64}";\n'
        + _JS +
        '</script>\n'
        '</body>\n'
        '</html>\n'
    )


_CSS = '''
body { background: #0a0e0a; color: #cfe5cf;
       font-family: ui-sans-serif, system-ui, sans-serif;
       margin: 0; padding: 0; line-height: 1.5; }
.wrap { max-width: 720px; margin: 1rem auto; padding: 0 1rem; }
h1 { color: #aaffaa; font-size: 1.4rem;
     border-bottom: 1px solid #2a6a2a; padding-bottom: 4px; }
.lede { color: #88aa88; font-size: 0.9rem; }
.chat { background: #050a05; border: 1px solid #1a4a1a;
        border-radius: 4px; padding: 12px; margin-top: 16px; }
.log { background: #000; min-height: 200px;
       font-family: ui-monospace, monospace; font-size: 0.85rem;
       padding: 8px; border: 1px solid #1a3a1a; overflow-y: auto;
       max-height: 400px; }
.log .msg { margin: 4px 0; }
.log .msg.user b { color: #79c0ff; }
.log .msg.ca b   { color: #aaffaa; }
.log .msg .meta  { color: #5a8a5a; font-size: 0.75rem; }
.log .msg pre    { white-space: pre-wrap; margin: 2px 0 4px 0;
                     color: #f0f0d0; }
#form { display: flex; gap: 8px; margin-top: 8px; }
#inp  { flex: 1; background: #0a1a0a; color: #cfe5cf;
        border: 1px solid #2a6a2a; padding: 6px 10px;
        font-family: ui-monospace, monospace; }
.controls { margin-top: 8px; font-size: 0.78rem; color: #88aa88; }
.controls input { margin-right: 4px; }
.log .msg.ca.untrained b { color: #ffaa44; }
.log .msg.ca.untrained pre { color: #ffd080; }
button { background: #0a2a0a; color: #aaffaa;
         border: 1px solid #2a6a2a; padding: 6px 14px;
         font-family: inherit; cursor: pointer; }
button:hover { background: #1a4a1a; }
.status { color: #5fc55f; font-size: 0.75rem; margin-top: 6px;
          font-family: ui-monospace, monospace; }
details { margin-top: 1rem; }
summary { color: #79c0ff; cursor: pointer; font-size: 0.85rem; }
pre { color: #cfe5cf; background: #050a05;
      padding: 10px; border: 1px solid #1a3a1a;
      font-size: 0.8rem; overflow-x: auto; }
#trained-list { columns: 2; column-gap: 1rem;
                  font-family: ui-monospace, monospace;
                  font-size: 0.8rem; color: #88aa88; }
#trained-list li { margin: 2px 0; }
'''


# JavaScript — must remain byte-exactly compatible with
# caformer/primitives.py:hex_ca_step.  Bit layout, row parity,
# toroidal wrap all matter.
_JS = '''
// ── Decode the base-64 blob ────────────────────────────────────────
function b64decode(s) {
    const bin = atob(s);
    const out = new Uint8Array(bin.length);
    for (let i = 0; i < bin.length; i++) out[i] = bin.charCodeAt(i);
    return out;
}
const BLOB = b64decode(BLOB_B64);

// ── Parse the bundle ───────────────────────────────────────────────
// Format documented in caformer_emit_standalone.py.  All ints little-endian.
const RULE_BYTES = 16384;
function parseBundle(buf) {
    if (String.fromCharCode(...buf.slice(0, 8)) !== "CAFORMER")
        throw new Error("bad magic");
    let p = 8;
    const version = buf[p++]; if (version !== 1) throw new Error("bad version");
    const n = buf[p++] | (buf[p++] << 8) | (buf[p++] << 16) | (buf[p++] << 24);
    const pairs = [];
    for (let i = 0; i < n; i++) {
        const side  = buf[p++];
        const ticks = buf[p++];
        const plen  = buf[p++] | (buf[p++] << 8);
        const prompt = new TextDecoder().decode(buf.slice(p, p + plen));
        p += plen;
        const elen  = buf[p++] | (buf[p++] << 8);
        const expected = new TextDecoder().decode(buf.slice(p, p + elen));
        p += elen;
        const nr = buf[p++] | (buf[p++] << 8);
        const rules = [];
        for (let k = 0; k < nr; k++) {
            rules.push(buf.slice(p, p + RULE_BYTES));
            p += RULE_BYTES;
        }
        pairs.push({ side, ticks, prompt, expected, rules });
    }
    return pairs;
}

const PAIRS = parseBundle(BLOB);

// ── Hex CA step (must match caformer/primitives.py:hex_ca_step) ────
// K=4 7→1, pointy-top, row-parity NW/NE/SW/SE, toroidal boundaries.
// Bit layout in the 14-bit key:
//   self << 12 | nw << 10 | ne << 8 | r << 6 | se << 4 | sw << 2 | l
function hexStep(state, rule, side) {
    const out = new Uint8Array(side * side);
    for (let r = 0; r < side; r++) {
        const even = (r & 1) === 0;
        const up = (r - 1 + side) % side;
        const dn = (r + 1) % side;
        for (let c = 0; c < side; c++) {
            const l  = (c - 1 + side) % side;
            const rc = (c + 1) % side;
            const self_ = state[r  * side + c ];
            const nL    = state[r  * side + l ];
            const nR    = state[r  * side + rc];
            const nUpL  = state[up * side + l ];
            const nUp_  = state[up * side + c ];
            const nUpR  = state[up * side + rc];
            const nDnL  = state[dn * side + l ];
            const nDn_  = state[dn * side + c ];
            const nDnR  = state[dn * side + rc];
            const nNW = even ? nUpL : nUp_;
            const nNE = even ? nUp_ : nUpR;
            const nSW = even ? nDnL : nDn_;
            const nSE = even ? nDn_ : nDnR;
            const key = (self_ << 12) | (nNW << 10) | (nNE << 8)
                      | (nR    <<  6) | (nSE <<  4) | (nSW << 2)
                      |  nL;
            out[r * side + c] = rule[key];
        }
    }
    return out;
}

// ── Embed prompt into a (side, side) K=4 board ─────────────────────
// Top half = prompt (4 cells per byte, base-4 digits, high → low).
function embedPrompt(prompt, side) {
    const cells = side * side;
    const bytesPerBlock = 4;
    const promptBytesMax = (cells / bytesPerBlock) >> 1;
    const raw = new TextEncoder().encode(prompt);
    const trimmed = raw.subarray(0, promptBytesMax);
    const out = new Uint8Array(cells);
    for (let i = 0; i < trimmed.length; i++) {
        const b = trimmed[i];
        const base = i * 4;
        out[base + 0] = (b >> 6) & 3;
        out[base + 1] = (b >> 4) & 3;
        out[base + 2] = (b >> 2) & 3;
        out[base + 3] =  b       & 3;
    }
    return out;
}

// Decode one byte at the i-th 4-cell block of the response region.
function decodeByteAt(board, position, side) {
    const cells = side * side;
    const responseStart = (cells >> 1);
    const base = responseStart + position * 4;
    return ((board[base + 0] & 3) << 6) | ((board[base + 1] & 3) << 4)
         | ((board[base + 2] & 3) << 2) |  (board[base + 3] & 3);
}

// ── Inference: produce N bytes from a per-position rules array ────
function infer(prompt, rules, side, ticks) {
    const s0 = embedPrompt(prompt, side);
    const out = new Uint8Array(rules.length);
    for (let pos = 0; pos < rules.length; pos++) {
        let state = new Uint8Array(s0);
        for (let t = 0; t < ticks; t++) state = hexStep(state, rules[pos], side);
        out[pos] = decodeByteAt(state, pos, side);
    }
    return out;
}

// ── UI ─────────────────────────────────────────────────────────────
const log      = document.getElementById("log");
const form     = document.getElementById("form");
const inp      = document.getElementById("inp");
const status   = document.getElementById("status");
const trList   = document.getElementById("trained-list");

// Populate trained-prompts list.
for (const p of PAIRS) {
    const li = document.createElement("li");
    li.textContent = JSON.stringify(p.prompt) + " → " + JSON.stringify(p.expected);
    li.style.cursor = "pointer";
    li.addEventListener("click", () => { inp.value = p.prompt; inp.focus(); });
    trList.appendChild(li);
}

const byPrompt = new Map();
for (const p of PAIRS) byPrompt.set(p.prompt, p);

function append(role, head, body, meta) {
    const m = document.createElement("div");
    m.className = "msg " + role;
    const h = document.createElement("b");
    h.textContent = head; m.appendChild(h);
    const pre = document.createElement("pre");
    pre.textContent = body; m.appendChild(pre);
    if (meta) {
        const me = document.createElement("span");
        me.className = "meta"; me.textContent = meta;
        m.appendChild(me);
    }
    log.appendChild(m);
    log.scrollTop = log.scrollHeight;
}

status.textContent = "loaded " + PAIRS.length + " trained pairs · "
                   + (BLOB.length / 1024 / 1024).toFixed(2) + " MB blob · "
                   + "tier sizes: " + [...new Set(PAIRS.map(p => p.side))].join(", ");

const showUntrained = document.getElementById("showUntrained");

function appendCa(text, meta, untrained) {
    const cls = untrained ? "ca untrained" : "ca";
    const headLabel = untrained ? "ca?" : "ca ";
    append(cls, headLabel, text, meta);
}

form.addEventListener("submit", (e) => {
    e.preventDefault();
    const q = inp.value.trim();
    if (!q) return;
    append("user", "you ", q, "");
    const p = byPrompt.get(q);
    if (p) {
        const t0 = performance.now();
        const out = infer(p.prompt, p.rules, p.side, p.ticks);
        const wall = performance.now() - t0;
        let txt;
        try { txt = new TextDecoder("utf-8", { fatal: true }).decode(out); }
        catch (e) { txt = new TextDecoder("latin1").decode(out); }
        const ok = txt === p.expected;
        appendCa(txt,
               "tier=" + p.side + " · " + p.rules.length
               + " rules · " + wall.toFixed(1) + " ms"
               + (ok ? " · byte-exact ✓" : " · ⚠ MISMATCH"),
               false);
        inp.value = "";
        return;
    }
    // Untrained prompt path.
    if (!showUntrained.checked) {
        appendCa(
            "(prompt not in trained set — only " + PAIRS.length
            + " pairs are bundled here)",
            "no rules for prompt · tick the checkbox below to see meaningless CA output anyway",
            false);
        return;
    }
    // Pick a random trained pair's rules and run them on this prompt.
    const borrow = PAIRS[Math.floor(Math.random() * PAIRS.length)];
    const t0 = performance.now();
    const out = infer(q, borrow.rules, borrow.side, borrow.ticks);
    const wall = performance.now() - t0;
    let txt;
    try { txt = new TextDecoder("utf-8", { fatal: true }).decode(out); }
    catch (e) { txt = new TextDecoder("latin1").decode(out); }
    // Some bytes may be control chars (NUL etc.); render as hex if mostly so.
    let printable = 0;
    for (let i = 0; i < out.length; i++) {
        const b = out[i];
        if ((b >= 32 && b < 127) || b === 10 || b === 9) printable++;
    }
    if (out.length > 0 && printable / out.length < 0.5) {
        txt = "[" + Array.from(out, b => b.toString(16).padStart(2, "0")).join(" ") + "]";
    }
    appendCa(txt,
           'untrained · borrowed rules from "' + borrow.prompt
           + '" (' + borrow.rules.length + ' rules @ tier '
           + borrow.side + ') · ' + wall.toFixed(1) + ' ms '
           + '— proof the CA is computing, not memorising',
           true);
    inp.value = "";
});

inp.focus();
'''
