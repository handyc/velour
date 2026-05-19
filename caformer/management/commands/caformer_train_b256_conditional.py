"""Phase 3 — train one cell8 rule + K context LUTs jointly so that
each context produces a DIFFERENT target byte at the same position.

This is the research-grade variant.  Risk: GA may plateau if K
contexts that produce K different outputs from the same trained
rule don't exist in tractable search distance.

  manage.py caformer_train_b256_conditional \\
      --prompt hi --position 0 \\
      --targets h,X \\
      --max-seconds 900 \\
      --seed-contexts-from .artifacts/loupe_rules

If --seed-contexts-from is given, the first K class-4 LUTs from
that directory are used as starting contexts (perturbed during
training).  Otherwise K random K=4 contexts are seeded.

Targets are comma-separated single characters or \\x?? escapes;
length determines K.  E.g. --targets h,X gives K=2 with target
bytes 0x68 and 0x58.
"""
from __future__ import annotations

import sys
import time
from pathlib import Path

from django.core.management.base import BaseCommand, CommandError


def parse_targets(spec: str):
    """'h,X,!' or 'h,\\x41,X' → [0x68, 0x58, 0x21] or similar."""
    out = []
    for t in spec.split(','):
        t = t.strip()
        if not t:
            continue
        if t.startswith('\\x') and len(t) == 4:
            out.append(int(t[2:], 16))
        elif len(t) == 1:
            out.append(ord(t))
        else:
            raise CommandError(f'bad target {t!r} (use a single char or \\xHH)')
    if len(out) < 2:
        raise CommandError('need at least 2 targets (K >= 2)')
    return out


class Command(BaseCommand):
    help = ('Phase 3: train cell8+256 rule + K contexts s.t. each '
            'context produces a different target byte.')

    def add_arguments(self, parser):
        parser.add_argument('--prompt', type=str, required=True)
        parser.add_argument('--position', type=int, default=0)
        parser.add_argument('--targets', type=str, required=True,
                              help='comma-separated K target bytes, e.g. h,X')
        parser.add_argument('--max-seconds', type=float, default=900.0)
        parser.add_argument('--n-ticks', type=int, default=256)
        parser.add_argument('--seed-contexts-from', type=str, default='',
                              help='dir of .lut files used as initial contexts')
        parser.add_argument('--seed-rule-from-pk', type=int, default=0,
                              help='warm-start rule from this QRPair pk\'s '
                                     'board128 position-0 rule')
        parser.add_argument('--seed', type=int, default=0xC02DC01)
        parser.add_argument('--out', type=str, default='',
                              help='optional output dir for rule + contexts')

    def handle(self, *, prompt, position, targets, max_seconds, n_ticks,
                 seed_contexts_from, seed_rule_from_pk, seed, out, **opts):
        from caformer.board256 import (train_position_b256_conditional,
                                              forward_byte_with_context,
                                              CONTEXT_LEN_256)

        def log(msg):
            sys.stdout.write(str(msg) + '\n'); sys.stdout.flush()

        target_bytes = parse_targets(targets)
        K = len(target_bytes)
        target_chars = [chr(b) if 32<=b<127 else f'\\x{b:02x}'
                          for b in target_bytes]

        # Seed contexts.
        seed_ctxs = None
        if seed_contexts_from:
            pd = Path(seed_contexts_from)
            if not pd.is_dir():
                raise CommandError(f'no dir: {seed_contexts_from}')
            luts = sorted(pd.glob('*.lut'))
            seed_ctxs = []
            for p in luts[:K]:
                blob = p.read_bytes()
                if len(blob) >= CONTEXT_LEN_256:
                    seed_ctxs.append(blob[:CONTEXT_LEN_256])
            if len(seed_ctxs) < K:
                raise CommandError(
                    f'need K={K} usable .lut files in {seed_contexts_from}, '
                    f'got {len(seed_ctxs)}')

        # Seed rule.
        seed_rule = None
        if seed_rule_from_pk:
            from caformer.models import QRPair
            pair = QRPair.objects.filter(pk=seed_rule_from_pk).first()
            if pair is None or not pair.board128_rules_blob:
                raise CommandError(
                    f'pair pk={seed_rule_from_pk} has no board128 rules')
            seed_rule = bytes(pair.board128_rules_blob[:16384])
            log(f'  warm-start rule: pk={seed_rule_from_pk} position-0 board128 rule')

        log(f'=== caformer_train_b256_conditional (Phase 3 research) ===')
        log(f'  prompt:       {prompt!r}')
        log(f'  position:     {position}')
        log(f'  K={K} targets: {target_chars} = {[hex(b) for b in target_bytes]}')
        log(f'  budget:       {max_seconds:.0f}s   n_ticks={n_ticks}')
        log(f'  seed contexts: {"from " + seed_contexts_from if seed_ctxs else "random"}')
        log()

        def on_event(k, p):
            keep = ('init', 'improved')
            if k in keep:
                el = p.get('elapsed_s', 0)
                bf = p.get('best_fit', '?')
                am = p.get('all_matched', '?')
                log(f'  [{el:7.1f}s] {k:10s} fit={bf}  all_matched={am}')

        t0 = time.time()
        r = train_position_b256_conditional(
            prompt, target_bytes, position,
            seed_contexts=seed_ctxs,
            n_ticks=n_ticks,
            max_seconds=max_seconds,
            seed_rule=seed_rule,
            seed=seed,
            on_event=on_event)
        wall = time.time() - t0

        log(f'\n=== result ({wall:.1f}s) ===')
        log(f'  phase: {r["phase"]}')
        log(f'  all matched: {r["all_matched"]}')
        for k in range(K):
            actual = forward_byte_with_context(
                prompt, r['rule_table'], r['contexts'][k], position,
                n_ticks=n_ticks)
            tag = '✓' if actual == target_bytes[k] else '✗'
            ac = chr(actual) if 32<=actual<127 else f'\\x{actual:02x}'
            log(f'  {tag} context k={k}: target={target_chars[k]!r} ({hex(target_bytes[k])})'
                f'  →  actual={ac!r} ({hex(actual)})')

        if out:
            out_p = Path(out)
            out_p.mkdir(parents=True, exist_ok=True)
            (out_p / 'rule.bin').write_bytes(bytes(r['rule_table']))
            for k, c in enumerate(r['contexts']):
                (out_p / f'context_{k:02d}.bin').write_bytes(c)
            log(f'\n  saved → {out_p}/  '
                f'(rule + {K} contexts, '
                f'{(65536 + K*16384)/1024:.0f} KB)')
