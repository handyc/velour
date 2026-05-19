"""Per-pair gated ensemble — context-conditioning prototype.

Tests the hypothesis that multi-pair contention is fixed by
compartmentalization: each shared token gets K candidate origins
(one per pair), and a hard pair-id gate routes inference to the
right candidate.

This is the parallel/stacked (2) composition pattern that's
underutilised in the current CA-LLM stack — equivalent to mixture-
of-experts gating in transformers.

Pipeline::

    Phase 1   Select best-of-pool origin per (token, pair) — independent
              selections, so pair 2's 'h' starts from a different L0
              quine than pair 7's 'h' if their contexts prefer different
              ones.

    Phase 2   Per-(token, pair) origin GA on that pair's contexts only.
              Each (token, pair) candidate is evolved independently —
              no contention with other pairs.

    Phase 3   Evaluate with a hard pair-id gate.  At inference for pair
              P's position i, look up token = pair_targets[P][i] and
              fetch origin[(token, P)].  Run that origin's chain.

Reports::

    per-pair argmax/lp before and after.  Compares to single-pair
    baseline ("if this works, multi-pair contention is solved by
    routing").  Storage cost = K × per_token × N_shared_tokens vs the
    contended single-origin case.

Usage::

    manage.py caformer_pair_gate --pairs 2,7,10
    manage.py caformer_pair_gate --pairs 2,7,10 --pop 8 --gens 12
    manage.py caformer_pair_gate --pairs 2,7,10 --skip-uncontended
"""
from __future__ import annotations

import sys
import time
from typing import Dict, List, Tuple

from django.core.management.base import BaseCommand, CommandError

from caformer.per_token_chain import (
    build_base_rules, chain_levels,
    evolve_origin, load_l0_quine_pool, _position_logprob, _pretty,
    corpus_argmax_matches,
)


def _evaluate_pair_lp(pair_id: int, pair_targets: dict, pair_prompts: dict,
                         n_blocks_by_pair: dict, base, block_tmpls,
                         chains_by_token_pair: dict) -> tuple[int, float]:
    """Score a single pair under a per-(token, pair) gating scheme.

    chains_by_token_pair[(token_byte, pair_id)] = chain levels list.
    For each position in the pair, look up the right chain by gating
    on pair_id.
    """
    targets = pair_targets[pair_id]
    nb = n_blocks_by_pair[pair_id]
    n_match = 0
    total_lp = 0.0
    for pos, tb in enumerate(targets):
        ctx = pair_prompts[pair_id] + targets[:pos]
        chain = chains_by_token_pair.get((tb, pair_id))
        if chain is None:
            # No gated chain for this (token, pair) — should not happen
            continue
        # Pick the best level of the chain (same convention as evolve_origin).
        best_lp = float('-inf')
        best_argmax = -1
        for rule in chain:
            fit, argmax = _position_logprob(ctx, nb, base, block_tmpls[nb],
                                                 rule, tb, 0.0)
            if fit > best_lp:
                best_lp = fit
                best_argmax = argmax
        total_lp += best_lp
        n_match += 1 if best_argmax == tb else 0
    return n_match, total_lp


class Command(BaseCommand):
    help = ('Per-pair gated ensemble: K candidate origins per shared '
              'token, hard pair-id gate.  Tests whether parallel '
              'ensembling fixes multi-pair contention.')

    def add_arguments(self, parser):
        parser.add_argument('--pairs', type=str, required=True,
                              help='comma-separated QRPair pks')
        parser.add_argument('--depth', type=int, default=12)
        parser.add_argument('--ticks', type=int, default=6)
        parser.add_argument('--select-n', type=int, default=32)
        parser.add_argument('--pop', type=int, default=8)
        parser.add_argument('--gens', type=int, default=12)
        parser.add_argument('--mut-min', type=int, default=4)
        parser.add_argument('--mut-max', type=int, default=64)
        parser.add_argument('--no-smart-mutation', action='store_true')
        parser.add_argument('--skip-uncontended', action='store_true',
            help='Skip GA for tokens that appear in only one pair '
                 '(use Phase-1 pool pick as final).  Saves time.')
        parser.add_argument('--base-seed', type=int, default=0xBA5E_C0DE)
        parser.add_argument('--seed', type=int, default=0xC1A1_C1A1)

    def handle(self, *, pairs, depth, ticks, select_n, pop, gens,
                 mut_min, mut_max, no_smart_mutation, skip_uncontended,
                 base_seed, seed, **opts):
        from caformer.models import QRPair
        try:
            pair_ids = [int(x) for x in pairs.split(',')]
        except ValueError:
            raise CommandError(f'--pairs must be comma-separated ints, got {pairs!r}')

        def _log(msg):
            sys.stdout.write(str(msg) + '\n')
            sys.stdout.flush()

        pairs_obj = [QRPair.objects.get(pk=pk) for pk in pair_ids]
        _log(f'corpus: {len(pairs_obj)} QRPairs (gated by pair_id)')
        for p in pairs_obj:
            _log(f'  #{p.pk}: {p.prompt!r} → {p.expected!r}  '
                 f'(n_blocks={p.n_blocks})')

        pair_targets: Dict[int, List[int]] = {}
        pair_prompts: Dict[int, List[int]] = {}
        n_blocks_by_pair: Dict[int, int] = {}
        for p in pairs_obj:
            pair_targets[p.pk]    = list(p.expected.encode('utf-8'))
            pair_prompts[p.pk]    = list(p.prompt.encode('utf-8'))
            n_blocks_by_pair[p.pk] = p.n_blocks

        # Build per-(token, pair) contexts: each (token, pair) is its
        # own GA target.  This is the compartmentalization.
        ctx_by_token_pair: Dict[Tuple[int, int], List[List[int]]] = {}
        for pk, targets in pair_targets.items():
            for pos, tb in enumerate(targets):
                ctx = pair_prompts[pk] + targets[:pos]
                ctx_by_token_pair.setdefault((tb, pk), []).append(ctx)

        all_token_pair = sorted(ctx_by_token_pair.keys())
        all_tokens = sorted({tp[0] for tp in all_token_pair})

        # Contention map: which tokens appear in multiple pairs?
        pairs_per_token: Dict[int, set] = {}
        for tb, pk in all_token_pair:
            pairs_per_token.setdefault(tb, set()).add(pk)
        contended_tokens = {tb for tb, pks in pairs_per_token.items()
                                if len(pks) > 1}
        uncontended_tokens = set(all_tokens) - contended_tokens
        _log(f'\nunique tokens: {len(all_tokens)} '
             f'({len(contended_tokens)} contended across pairs, '
             f'{len(uncontended_tokens)} appear in one pair only)')
        for tb in sorted(contended_tokens):
            pks = sorted(pairs_per_token[tb])
            _log(f'  contended token {_pretty(tb)}: pairs {pks}')

        base = build_base_rules(base_seed)
        pool = load_l0_quine_pool()
        _log(f'L0 quine pool: {len(pool)}')

        # Build block-rules template per n_blocks value seen.
        block_tmpls = {}
        for nb in set(n_blocks_by_pair.values()):
            block_tmpls[nb] = [{k: base[k] for k in
                                  ('q', 'k', 'v', 'score', 'mix', 'merge', 'mlp')}
                                ] * nb

        # ── Phase 1: per-(token, pair) origin selection from pool ──
        _log(f'\n=== Phase 1: select best origin per (token, pair) ===')
        token_pair_origins: Dict[Tuple[int, int], bytes] = {}
        token_pair_pk:      Dict[Tuple[int, int], int]   = {}
        for tb, pk in all_token_pair:
            nb = n_blocks_by_pair[pk]
            ctxs = ctx_by_token_pair[(tb, pk)]
            best_score = float('-inf')
            best_pk_c, best_origin = -1, b''
            for pk_c, origin in pool[:select_n]:
                chain = chain_levels(origin, depth=depth,
                                          ticks_per_level=ticks,
                                          mode='ca_evolution')
                agg = 0.0
                for ctx in ctxs:
                    pos_best = float('-inf')
                    for rule in chain:
                        fit, _ = _position_logprob(
                            ctx, nb, base, block_tmpls[nb], rule, tb, 0.0)
                        if fit > pos_best:
                            pos_best = fit
                    agg += pos_best
                if agg > best_score:
                    best_score = agg
                    best_pk_c, best_origin = pk_c, origin
            token_pair_origins[(tb, pk)] = best_origin
            token_pair_pk[(tb, pk)] = best_pk_c
            _log(f'  ({_pretty(tb)}, pair {pk}) ← #{best_pk_c}  agg={best_score:+.3f}')

        # Baseline lp + matches with Phase-1 picks
        chains_by_token_pair_baseline = {
            (tb, pk): chain_levels(o, depth=depth, ticks_per_level=ticks,
                                       mode='ca_evolution')
            for (tb, pk), o in token_pair_origins.items()
        }
        _log('\n=== After Phase 1 (per-pair gated, no GA yet) ===')
        for pk in pair_ids:
            m, lp = _evaluate_pair_lp(
                pk, pair_targets, pair_prompts, n_blocks_by_pair,
                base, block_tmpls, chains_by_token_pair_baseline)
            tot = len(pair_targets[pk])
            _log(f'  pair {pk}: matches {m}/{tot}  lp {lp:+.3f}')

        # ── Phase 2: per-(token, pair) origin GA ──
        _log(f'\n=== Phase 2: per-(token, pair) GA ===')
        _log(f'  pop={pop} gens={gens} mut={mut_min}-{mut_max}')
        skipped = 0
        for tb, pk in all_token_pair:
            ctxs = ctx_by_token_pair[(tb, pk)]
            nb = n_blocks_by_pair[pk]
            if skip_uncontended and tb in uncontended_tokens:
                skipped += 1
                continue
            t0 = time.time()
            _log(f'\n  ({_pretty(tb)}, pair {pk}) '
                 f'(start #{token_pair_pk[(tb, pk)]}, {len(ctxs)} contexts)')
            evolved, sc = evolve_origin(
                token_pair_origins[(tb, pk)], ctxs, tb, nb,
                base, block_tmpls[nb],
                chain_depth=depth, ticks_per_level=ticks,
                chain_mode='ca_evolution', argmax_bonus=5.0,
                mu=max(2, pop // 3), lam=pop, generations=gens,
                mutation_min=mut_min, mutation_max=mut_max,
                smart_mutation=not no_smart_mutation,
                rng_seed=seed ^ (tb * 99991) ^ (pk * 7),
                log=_log)
            token_pair_origins[(tb, pk)] = evolved
            _log(f'    → final score={sc:+.3f}  ({time.time()-t0:.1f}s)')

        if skipped:
            _log(f'\n  skipped {skipped} (token, pair) entries '
                 f'(uncontended, retained Phase-1 selection)')

        # ── Phase 3: evaluate per-pair with gating ──
        _log('\n=== Phase 3: per-pair gated evaluation ===')
        chains_by_token_pair_final = {
            (tb, pk): chain_levels(o, depth=depth, ticks_per_level=ticks,
                                       mode='ca_evolution')
            for (tb, pk), o in token_pair_origins.items()
        }
        grand_match = 0
        grand_lp    = 0.0
        grand_total = 0
        for pk in pair_ids:
            m, lp = _evaluate_pair_lp(
                pk, pair_targets, pair_prompts, n_blocks_by_pair,
                base, block_tmpls, chains_by_token_pair_final)
            tot = len(pair_targets[pk])
            grand_match += m; grand_lp += lp; grand_total += tot
            tag = '✓ EXACT' if m == tot else f'({m}/{tot})'
            _log(f'  pair {pk}: matches {m}/{tot}  lp {lp:+.3f}   {tag}')

        _log('')
        _log(f'=== SUMMARY ===')
        _log(f'  total positions   : {grand_total}')
        _log(f'  total matches     : {grand_match}/{grand_total}')
        _log(f'  total lp          : {grand_lp:+.3f}')
        _log(f'  storage overhead  : {len(token_pair_origins)} '
             f'(token,pair) origins × 16,384 B = '
             f'{len(token_pair_origins) * 16384 / 1024:.0f} KB')
        _log(f'                       (baseline single-origin per-token would be '
             f'{len(all_tokens)} × 16,384 B = '
             f'{len(all_tokens) * 16384 / 1024:.0f} KB)')
