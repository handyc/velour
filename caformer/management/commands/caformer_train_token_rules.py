"""Phase 2: train one K=4 rule per token so firing produces the
token's own name as the first N output cells.

  manage.py caformer_train_token_rules
  manage.py caformer_train_token_rules --kind verbs --iters 3000
  manage.py caformer_train_token_rules --kind all --out-dir .artifacts/token_rules_v2

Kinds:
  verbs     — all VERB_ROOTS (Sanskrit dhātus, 128 today)
  preverbs  — all PREVERBS (upasargas, 20)
  suffixes  — all KRIT_SUFFIXES (16)
  all       — verbs + preverbs + suffixes (IDs offset so no collision)
"""
from __future__ import annotations

import sys
import time
from pathlib import Path

import numpy as np

from django.conf import settings
from django.core.management.base import BaseCommand


# ID offsets — distinguish verb/preverb/suffix in the same token_id
# space so a single token_rules artifact dir can hold them all.
ID_OFFSET_VERB    = 0          # verb_id 1..1999
ID_OFFSET_PREVERB = 10000      # preverb_id 10001..10031
ID_OFFSET_SUFFIX  = 20000      # suffix_id 20001..20031


def _collect_tokens(kind: str) -> list[tuple[int, str]]:
    """Return list of (token_id_with_offset, romanised_form) for the
    requested kind."""
    from caformer.concept_system import (VERB_ROOTS, PREVERBS, KRIT_SUFFIXES)
    out: list[tuple[int, str]] = []
    if kind in ('verbs', 'all'):
        for v in VERB_ROOTS:
            out.append((ID_OFFSET_VERB + v.id, v.root))
    if kind in ('preverbs', 'all'):
        for p in PREVERBS:
            out.append((ID_OFFSET_PREVERB + p.id, p.form))
    if kind in ('suffixes', 'all'):
        for s in KRIT_SUFFIXES:
            # Strip leading hyphen for clean encoding ('a' not '-a').
            out.append((ID_OFFSET_SUFFIX + s.id, s.form.lstrip('-')))
    return out


class Command(BaseCommand):
    help = ('Train one K=4 rule per Sanskrit token so firing the '
            'rule reproduces the token\'s romanised name in the '
            'first cells of the output grid.')

    def add_arguments(self, parser):
        parser.add_argument('--kind',
            choices=['verbs', 'preverbs', 'suffixes', 'all'],
            default='all')
        parser.add_argument('--iters', type=int, default=2000,
                              help='per-token GA iterations')
        parser.add_argument('--n-ticks', type=int, default=4)
        parser.add_argument('--flips-min', type=int, default=4)
        parser.add_argument('--flips-max', type=int, default=200)
        parser.add_argument('--out-dir', type=str,
                              default='.artifacts/token_rules_v1')
        parser.add_argument('--seed-base', type=int, default=0xCA4CA4)

    def handle(self, *, kind, iters, n_ticks, flips_min, flips_max,
                 out_dir, seed_base, **opts):
        def log(msg):
            sys.stdout.write(str(msg) + '\n'); sys.stdout.flush()

        from caformer.concept_system.token_rules import (
            train_rule_for_token, save_rules)

        out = Path(settings.BASE_DIR) / out_dir
        tokens = _collect_tokens(kind)
        log(f'=== token-rule training ({kind}) ===')
        log(f'  tokens:   {len(tokens)}')
        log(f'  iters:    {iters} per token')
        log(f'  n_ticks:  {n_ticks}')
        log(f'  out_dir:  {out}')

        rules: dict[int, np.ndarray] = {}
        names: dict[int, str] = {}
        fits:  dict[int, tuple[int, int]] = {}
        t0 = time.time()
        for i, (tid, name) in enumerate(tokens):
            best_rule, best_fit, n_target = train_rule_for_token(
                name,
                iters=iters,
                flips_min=flips_min,
                flips_max=flips_max,
                n_ticks=n_ticks,
                seed=seed_base ^ tid)
            rules[tid] = best_rule
            names[tid] = name
            fits[tid]  = (best_fit, n_target)
            if (i + 1) % 16 == 0 or i + 1 == len(tokens):
                elapsed = time.time() - t0
                rate = (i + 1) / max(elapsed, 1e-6)
                remaining = (len(tokens) - i - 1) / max(rate, 1e-6)
                log(f'  [{i+1:>3}/{len(tokens)}]  last token={name!r:>8} '
                    f'fit={best_fit}/{n_target}  '
                    f'{rate:.1f} tok/s  ETA {remaining:.0f}s')

        wall = time.time() - t0
        # Summary.
        perfect = sum(1 for f, t in fits.values() if t > 0 and f == t)
        good    = sum(1 for f, t in fits.values()
                       if t > 0 and f >= max(1, int(t * 0.75)))
        log('')
        log(f'  trained {len(rules)} rules in {wall:.0f}s')
        log(f'  perfect (fit == n_target):   {perfect}/{len(rules)}')
        log(f'  ≥ 75% match:                  {good}/{len(rules)}')

        # Persist.
        save_rules(rules, names, fits, out)
        log(f'  saved to {out}')

        # Sample readback.
        from caformer.concept_system.token_rules import (
            fire, cells_to_string)
        log('')
        log('  readback samples:')
        for tid, name in tokens[:5]:
            state = fire(rules[tid], n_ticks=n_ticks)
            n_bytes = len(name.encode('utf-8'))
            got = cells_to_string(state.flatten(), n_bytes)
            log(f'    target={name!r:>8}  got={got!r}')
