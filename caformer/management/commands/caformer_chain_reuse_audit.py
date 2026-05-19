"""Brute-force chain reuse audit.

For every trained QRPair X and every other trained QRPair Y, run X's
chain (base genome + per-position output rules, teacher-forced on Y's
expected response prefix) on Y's prompt and see how many bytes of Y's
expected output X's chain reproduces at argmax.

Two reuse signals:

  full   — chain X reproduces ALL of Y.expected.  Pair Y doesn't need
            its own training; dispatcher can route Y → X's slug.
  prefix — chain X reproduces the first N bytes of Y.expected.  Useful
            as GA warm-start: train Y from X's chain instead of random
            init.  Reports the longest prefix len.

Also tallies per-(position, byte) shared logits — if many trained
positions emit byte 'e' at pos 1 of the response, we have a "universal
byte-e-at-pos-1" candidate chain.

Outputs:
  .artifacts/chain_reuse_graph.json  — machine-readable
  .artifacts/chain_reuse_report.md   — human-readable summary
"""
from __future__ import annotations

import json
import time
from collections import defaultdict
from pathlib import Path

import numpy as np
from django.conf import settings
from django.core.management.base import BaseCommand


class Command(BaseCommand):
    help = ('Cross-test every trained chain against every other trained '
            'pair to discover reuse opportunities.')

    def add_arguments(self, parser):
        parser.add_argument('--out-dir', type=str, default='.artifacts',
                              help='where to write the graph + report')
        parser.add_argument('--include-untrained', action='store_true',
                              help='also test against pairs with '
                                     'best_exact=False (slower; useful for '
                                     'pre-flight warm-start discovery)')

    def handle(self, *, out_dir, include_untrained, **opts):
        from caformer.models import QRPair
        from caformer.transformer import ca_forward_qkv

        out = Path(settings.BASE_DIR) / out_dir
        out.mkdir(parents=True, exist_ok=True)

        # Collect trained chains (sources).
        sources = list(QRPair.objects
                         .filter(best_exact=True)
                         .exclude(positional_output_blob__isnull=True))
        sources = [p for p in sources if p.is_positional()]

        # Collect target pairs to test against.
        if include_untrained:
            targets = list(QRPair.objects.all())
        else:
            targets = list(sources)

        self.stdout.write(f'sources: {len(sources)} trained chains')
        self.stdout.write(f'targets: {len(targets)} pairs to test against')
        self.stdout.write(f'cross-tests: {len(sources) * len(targets)} '
                          f'(skipping self-tests)\n')

        # Cache (base, out_rules) per source so we don't rebuild each call.
        src_cache = []
        for p in sources:
            base = p.best_genome()
            out_rules = p.positional_output_rules()
            if base is None or not out_rules:
                continue
            src_cache.append({
                'pair': p,
                'base': base,
                'out_rules': out_rules,
                'expected_bytes': p.expected.encode('utf-8'),
            })

        def run_chain(base, out_rules, ctx_bytes, n_positions):
            """Teacher-force ctx_bytes as prompt, then auto-regress
            for n_positions ticks using out_rules[i] at position i.
            Returns the produced bytes (n_positions of them)."""
            seq = list(ctx_bytes)
            block = {k: base[k] for k in
                     ('q', 'k', 'v', 'score', 'mix', 'merge', 'mlp')}
            block_rules = [block]    # n_blocks=1 — all trained pairs use this
            out = []
            for i in range(n_positions):
                if i >= len(out_rules):
                    break
                logits = ca_forward_qkv(
                    seq, n_blocks=1,
                    embed_rule=base['embed'], block_rules=block_rules,
                    norm_rule=base['norm'],
                    output_rule=out_rules[i], vocab_size=256)
                nxt = int(np.argmax(logits))
                out.append(nxt)
                seq.append(nxt)
            return bytes(out)

        # Cross-test loop.
        t0 = time.time()
        edges = []
        per_position_tally = defaultdict(lambda: defaultdict(list))
            # per_position_tally[pos][byte] = [(source_pair_id, source_label), …]
        n_done = 0
        for s in src_cache:
            src_p = s['pair']
            for t in targets:
                if t.pk == src_p.pk:
                    continue
                tgt_bytes = t.expected.encode('utf-8')
                if not tgt_bytes:
                    continue
                # Use SAME context length as source training: prompt only.
                ctx = list(t.prompt.encode('utf-8'))
                produced = run_chain(s['base'], s['out_rules'],
                                       ctx, len(tgt_bytes))
                # Position-level matches.
                prefix_len = 0
                for i, (a, b) in enumerate(zip(produced, tgt_bytes)):
                    if a == b:
                        prefix_len = i + 1
                        per_position_tally[i][b].append(
                            (src_p.pk, src_p.prompt))
                    else:
                        break
                full = (produced == tgt_bytes)
                if full or prefix_len > 0:
                    edges.append({
                        'source_pk':       src_p.pk,
                        'source_prompt':   src_p.prompt,
                        'source_expected': src_p.expected,
                        'target_pk':       t.pk,
                        'target_prompt':   t.prompt,
                        'target_expected': t.expected,
                        'produced':        produced.decode(
                            'latin-1', errors='replace'),
                        'prefix_bytes':    prefix_len,
                        'target_bytes':    len(tgt_bytes),
                        'full_match':      full,
                    })
            n_done += 1
            self.stdout.write(
                f'  [{time.time()-t0:5.1f}s] {n_done}/{len(src_cache)} '
                f'sources done · edges so far: {len(edges)}')

        wall = time.time() - t0

        # Sort edges: full matches first, then by prefix length desc.
        edges.sort(key=lambda e: (-int(e['full_match']),
                                       -e['prefix_bytes']))

        full_matches = [e for e in edges if e['full_match']]
        prefix_only  = [e for e in edges if not e['full_match']]

        # Per-position consolidation: positions where a single byte
        # appears across N trained pairs.
        universals = []
        for pos in sorted(per_position_tally.keys()):
            for byte, srcs in per_position_tally[pos].items():
                if len(srcs) >= 3:
                    universals.append({
                        'pos':           pos,
                        'byte':          byte,
                        'char':          chr(byte) if 32 <= byte < 127
                                            else f'\\x{byte:02x}',
                        'n_sources':     len(srcs),
                        'source_pks':    [s[0] for s in srcs],
                        'source_prompts': [s[1] for s in srcs],
                    })
        universals.sort(key=lambda u: -u['n_sources'])

        # ───────── JSON output ─────────
        graph = {
            'generated_at_unix': time.time(),
            'wall_seconds':      wall,
            'n_sources':         len(src_cache),
            'n_targets':         len(targets),
            'n_cross_tests':     n_done * len(targets),
            'n_full_matches':    len(full_matches),
            'n_prefix_only':     len(prefix_only),
            'edges':             edges,
            'universals_top':    universals[:50],
        }
        json_path = out / 'chain_reuse_graph.json'
        json_path.write_text(json.dumps(graph, indent=2))
        self.stdout.write(self.style.SUCCESS(
            f'\nwrote {json_path}'))

        # ───────── Markdown report ─────────
        md = []
        md.append(f'# Chain reuse audit\n')
        md.append(f'_Generated 2026-05-18, {wall:.1f}s wall, '
                  f'{n_done}×{len(targets)} cross-tests._\n')
        md.append('')
        md.append('## Summary')
        md.append(f'- Trained chains tested as sources: **{len(src_cache)}**')
        md.append(f'- Pairs tested as targets:          **{len(targets)}**')
        md.append(f'- Full reuses (chain X fully reproduces pair Y): '
                  f'**{len(full_matches)}**')
        md.append(f'- Prefix-only reuses (partial overlap):           '
                  f'**{len(prefix_only)}**')
        md.append('')
        if full_matches:
            md.append('## Full reuses (consolidation candidates)')
            md.append('')
            md.append('| source_pk | source prompt → expected | target_pk | '
                      'target prompt → expected |')
            md.append('|---|---|---|---|')
            for e in full_matches:
                md.append(f'| {e["source_pk"]} | `{e["source_prompt"]}` → '
                          f'`{e["source_expected"]}` | {e["target_pk"]} | '
                          f'`{e["target_prompt"]}` → '
                          f'`{e["target_expected"]}` |')
            md.append('')
        if prefix_only:
            md.append('## Top prefix matches (GA warm-start candidates)')
            md.append('')
            md.append('| source_pk | source → expected | target_pk | '
                      'target → expected | matched bytes |')
            md.append('|---|---|---|---|---|')
            for e in prefix_only[:30]:
                md.append(f'| {e["source_pk"]} | `{e["source_prompt"]}` → '
                          f'`{e["source_expected"]}` | {e["target_pk"]} | '
                          f'`{e["target_prompt"]}` → '
                          f'`{e["target_expected"]}` | '
                          f'{e["prefix_bytes"]}/{e["target_bytes"]} |')
            md.append('')
        if universals:
            md.append('## Position-level universals')
            md.append('')
            md.append('Same `(position, byte)` produced by ≥3 trained chains '
                      '— candidate for a single shared "universal" chain.')
            md.append('')
            md.append('| pos | byte | n_chains | source prompts |')
            md.append('|---|---|---|---|')
            for u in universals[:20]:
                prompts = ', '.join(f'`{p}`' for p in u['source_prompts'][:5])
                if len(u['source_prompts']) > 5:
                    prompts += f', … (+{len(u["source_prompts"]) - 5})'
                md.append(f'| {u["pos"]} | `{u["char"]}` | '
                          f'{u["n_sources"]} | {prompts} |')
            md.append('')
        md_path = out / 'chain_reuse_report.md'
        md_path.write_text('\n'.join(md))
        self.stdout.write(self.style.SUCCESS(f'wrote {md_path}'))

        # Console summary.
        self.stdout.write('')
        self.stdout.write(self.style.SUCCESS(
            f'═══ {len(full_matches)} full reuses, '
            f'{len(prefix_only)} prefix-only, '
            f'{len(universals)} position universals ═══'))
        if full_matches:
            self.stdout.write('Top full reuses:')
            for e in full_matches[:10]:
                self.stdout.write(f'  pk={e["source_pk"]} '
                                    f'{e["source_prompt"]!r}→{e["source_expected"]!r}'
                                    f' covers pk={e["target_pk"]} '
                                    f'{e["target_prompt"]!r}→{e["target_expected"]!r}')
