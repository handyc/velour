"""Per-token origin GA — the actual optimisation that matters.

After diagnosing that base co-evolution stalls because the BASE is at
a local max under random chains (chains are the bottleneck), this
command does the opposite: fix the base, evolve each token's 4096-byte
packed origin via smart-mutation + lp fitness to maximise corpus log-
likelihood for that token's positions.

Each token's GA is independent → embarrassingly parallel.  Storage
stays at 4096 packed bytes per token (the origin) — chain regenerated
at inference.

Usage::

    venv/bin/python manage.py caformer_evolve_origins --pairs 2
    venv/bin/python manage.py caformer_evolve_origins --pairs 2,11 --gens 16 --pop 12
"""
from __future__ import annotations

import sys
from typing import Dict, List, Tuple

from django.core.management.base import BaseCommand, CommandError

from caformer.per_token_chain import (
    BASE_RULE_NAMES, build_base_rules, chain_levels, corpus_argmax_matches,
    evolve_origin, load_l0_quine_pool, _position_logprob, _pretty,
)


class Command(BaseCommand):
    help = 'Per-token origin GA with smart mutation against corpus log-likelihood.'

    def add_arguments(self, parser):
        parser.add_argument('--pairs', type=str, required=True,
                              help='comma-separated QRPair pks')
        parser.add_argument('--depth', type=int, default=12)
        parser.add_argument('--ticks', type=int, default=6)
        parser.add_argument('--select-n', type=int, default=32,
                              help='pool candidates to seed each token')
        parser.add_argument('--pop', type=int, default=8,
                              help='GA pop size per token (μ+λ)')
        parser.add_argument('--gens', type=int, default=12,
                              help='GA generations per token')
        parser.add_argument('--mut-min', type=int, default=4,
                              help='min byte flips per mutation')
        parser.add_argument('--mut-max', type=int, default=64,
                              help='max byte flips per mutation')
        parser.add_argument('--no-smart-mutation', action='store_true',
                              help='disable origin fire-mask restricted mutation')
        parser.add_argument('--base-seed', type=int, default=0xBA5E_C0DE)
        parser.add_argument('--seed', type=int, default=0xC1A1_C1A1)

    def handle(self, *args, pairs, depth, ticks, select_n, pop, gens,
                 mut_min, mut_max, no_smart_mutation, base_seed, seed, **opts):
        from caformer.models import QRPair
        try:
            pair_ids = [int(x) for x in pairs.split(',')]
        except ValueError:
            raise CommandError(f'--pairs must be comma-separated ints, got {pairs!r}')

        def _log(msg):
            sys.stdout.write(str(msg) + '\n')
            sys.stdout.flush()

        pairs_obj = [QRPair.objects.get(pk=pk) for pk in pair_ids]
        _log(f'corpus: {len(pairs_obj)} QRPairs')
        for p in pairs_obj:
            _log(f'  #{p.pk}: {p.prompt!r} → {p.expected!r}  '
                 f'(n_blocks={p.n_blocks})')

        # Build per-token contexts across the corpus.
        pair_targets: Dict[int, List[int]] = {}
        pair_prompts: Dict[int, List[int]] = {}
        n_blocks_by_pair: Dict[int, int] = {}
        for p in pairs_obj:
            pair_targets[p.pk] = list(p.expected.encode('utf-8'))
            pair_prompts[p.pk] = list(p.prompt.encode('utf-8'))
            n_blocks_by_pair[p.pk] = p.n_blocks
        all_tokens = sorted({tb for tgs in pair_targets.values() for tb in tgs})
        # Per-token contexts: list of (ctx_bytes, n_blocks).  No pair_id
        # needed inside the GA because per-token isolation means all
        # contexts for a given token can be evaluated against a single base.
        ctx_by_token: Dict[int, List[Tuple[List[int], int]]] = {}
        for pk, targets in pair_targets.items():
            for pos, tb in enumerate(targets):
                ctx = pair_prompts[pk] + targets[:pos]
                ctx_by_token.setdefault(tb, []).append(
                    (ctx, n_blocks_by_pair[pk]))

        _log(f'unique tokens across corpus: {len(all_tokens)}')

        base = build_base_rules(base_seed)
        pool = load_l0_quine_pool()
        _log(f'L0 quine pool: {len(pool)}')

        # Phase 1: select best-of-K origin per token under the fixed base.
        _log(f'\n=== Phase 1: select origin per token (top {select_n} of pool) ===')
        # Need a per-n_blocks block_rules_template for the lp scorer.
        block_tmpls = {}
        for nb in set(n_blocks_by_pair.values()):
            block_tmpls[nb] = [{k: base[k] for k in
                                  ('q', 'k', 'v', 'score', 'mix', 'merge', 'mlp')}
                                  ] * nb
        token_origins: Dict[int, bytes] = {}
        token_origin_pks: Dict[int, int] = {}
        for tb in all_tokens:
            items = ctx_by_token[tb]
            best_score = float('-inf')
            best_pk, best_origin = -1, b''
            for pk_c, origin in pool[:select_n]:
                chain = chain_levels(origin, depth=depth,
                                      ticks_per_level=ticks,
                                      mode='ca_evolution')
                agg = 0.0
                for ctx, nb in items:
                    pos_best = float('-inf')
                    for rule in chain:
                        fit, _ = _position_logprob(
                            ctx, nb, base, block_tmpls[nb], rule, tb, 0.0)
                        if fit > pos_best:
                            pos_best = fit
                    agg += pos_best
                if agg > best_score:
                    best_score = agg
                    best_pk, best_origin = pk_c, origin
            token_origins[tb] = best_origin
            token_origin_pks[tb] = best_pk
            _log(f'  token {_pretty(tb)} (×{len(items)}) ← quine #{best_pk}  '
                 f'agg={best_score:+.3f}')

        # Initial corpus lp under selected origins.
        chains = {tb: chain_levels(o, depth=depth, ticks_per_level=ticks,
                                     mode='ca_evolution')
                  for tb, o in token_origins.items()}
        contexts_by_token_pid = {tb: [(ctx, list(n_blocks_by_pair.keys())[0])
                                       for ctx, _ in items]
                                  for tb, items in ctx_by_token.items()}
        # Need to thread the right pair_id; rebuild faithfully
        ctx_by_token_pid: Dict[int, List[Tuple[List[int], int]]] = {}
        for pk, targets in pair_targets.items():
            for pos, tb in enumerate(targets):
                ctx = pair_prompts[pk] + targets[:pos]
                ctx_by_token_pid.setdefault(tb, []).append((ctx, pk))
        init_m, init_lp = corpus_argmax_matches(
            base, chains, ctx_by_token_pid, n_blocks_by_pair,
            fitness_mode='lp')
        total_pos = sum(len(items) for items in ctx_by_token.values())
        _log(f'\nAFTER selection: matches {init_m}/{total_pos}  lp {init_lp:+.3f}')

        # Phase 2: evolve each token's origin.
        _log(f'\n=== Phase 2: per-token origin GA ===')
        _log(f'  pop={pop} gens={gens} mut={mut_min}-{mut_max} '
             f'smart={"on" if not no_smart_mutation else "off"}')
        for tb in all_tokens:
            items = ctx_by_token[tb]
            # evolve_origin's contexts arg is list of ctx bytes; n_blocks
            # comes from the first item's pair (we assume tokens within
            # a pair share n_blocks — true for shakespeare-tiny).
            nb_first = items[0][1]
            ctx_list = [ctx for ctx, _ in items]
            _log(f'\n  evolving token {_pretty(tb)} '
                 f'(start pk={token_origin_pks[tb]}, {len(items)} contexts)')
            evolved, sc = evolve_origin(
                token_origins[tb], ctx_list, tb, nb_first,
                base, block_tmpls[nb_first],
                chain_depth=depth, ticks_per_level=ticks,
                chain_mode='ca_evolution', argmax_bonus=0.0,
                mu=max(2, pop // 3), lam=pop, generations=gens,
                mutation_min=mut_min, mutation_max=mut_max,
                smart_mutation=not no_smart_mutation,
                rng_seed=seed ^ (tb * 99991),
                log=_log)
            token_origins[tb] = evolved
            _log(f'    → final score={sc:+.3f}')

        # Recompute chains + final corpus lp.
        chains = {tb: chain_levels(o, depth=depth, ticks_per_level=ticks,
                                     mode='ca_evolution')
                  for tb, o in token_origins.items()}
        final_m, final_lp = corpus_argmax_matches(
            base, chains, ctx_by_token_pid, n_blocks_by_pair,
            fitness_mode='lp')

        self.stdout.write('')
        self.stdout.write(self.style.NOTICE('=== summary ==='))
        self.stdout.write(
            f'corpus positions  : {total_pos}\n'
            f'initial matches   : {init_m}/{total_pos}  (lp {init_lp:+.3f})\n'
            f'final matches     : {final_m}/{total_pos}  (lp {final_lp:+.3f})\n'
            f'Δ matches         : {final_m - init_m:+d}\n'
            f'Δ lp              : {final_lp - init_lp:+.3f}\n'
        )
