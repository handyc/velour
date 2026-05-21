"""Phase-1 experiment: does token-per-CA-ruleset pan out?

Generates one K=4 LUT per Sanskrit verb root (using verb_id as the
seed) and reports four findings:

  (1) Distinctness  — does each token produce a unique fingerprint
                      when fired in isolation?  Or do collisions
                      mean the alphabet of meaning collapses?
  (2) Non-commutativity — does (A → B) differ from (B → A) for
                      most pairs?  If yes, ordering matters and the
                      cascade encodes sequence.
  (3) Decodability — given a final state from an N-rule cascade,
                      can we recover which rules were used?
  (4) Cascade richness — how many distinct fingerprints do all 2-
                      and 3-step cascades produce?

  manage.py caformer_token_rules_experiment
  manage.py caformer_token_rules_experiment --n-verbs 32 --n-ticks 4
"""
from __future__ import annotations

import sys
import time
from collections import Counter
from itertools import combinations, permutations

import numpy as np

from django.core.management.base import BaseCommand


class Command(BaseCommand):
    help = ('Phase-1 experiment: assign one K=4 LUT per Sanskrit verb '
            'root, measure fingerprint distinctness, composition '
            'non-commutativity, and decodability.')

    def add_arguments(self, parser):
        parser.add_argument('--n-verbs', type=int, default=32,
                              help='how many verb roots to use')
        parser.add_argument('--n-ticks', type=int, default=4,
                              help='CA ticks per fire')
        parser.add_argument('--n-cascade-samples', type=int, default=200,
                              help='how many random 3-step cascades to '
                                     'sample for richness measurement')
        parser.add_argument('--seed-base', type=int, default=0xCAFEBA8E)

    def handle(self, *, n_verbs, n_ticks, n_cascade_samples, seed_base,
                 **opts):
        def log(msg):
            sys.stdout.write(str(msg) + '\n'); sys.stdout.flush()

        from caformer.concept_system import VERB_ROOTS
        from caformer.concept_system.token_rules import (
            generate_rule, fire, cascade, fingerprint)

        n = min(n_verbs, len(VERB_ROOTS))
        verbs = list(VERB_ROOTS[:n])
        log(f'=== token-per-CA-rule experiment ===')
        log(f'  verbs:   {n}')
        log(f'  ticks:   {n_ticks}')
        log(f'  seed:    {hex(seed_base)}')

        # Generate one rule per verb.
        t0 = time.time()
        rules: dict[int, np.ndarray] = {}
        for v in verbs:
            rules[v.id] = generate_rule(seed_base ^ v.id)
        log(f'  rules generated in {time.time()-t0:.2f}s '
            f'({n} × {rules[verbs[0].id].size}-entry K=4 LUTs)')

        # ── 1. Distinctness ────────────────────────────────────
        log('')
        log('-- 1. Distinctness (fire in isolation, fingerprint) --')
        prints: dict[int, tuple] = {}
        keys_seen: Counter[tuple] = Counter()
        for v in verbs:
            fp = fingerprint(fire(rules[v.id], n_ticks=n_ticks))
            prints[v.id] = fp.key()
            keys_seen[fp.key()] += 1
        unique_count = sum(1 for c in keys_seen.values() if c == 1)
        collisions = sum(c for c in keys_seen.values() if c > 1)
        log(f'  unique fingerprints:   {unique_count}/{n} '
            f'({100*unique_count/n:.0f}%)')
        log(f'  colliding fingerprints: {collisions} '
            f'(across {sum(1 for c in keys_seen.values() if c > 1)} buckets)')
        log(f'  sample (first 5):')
        for v in verbs[:5]:
            hist = prints[v.id][:4]
            corners = prints[v.id][4:]
            log(f'    {v.root:>6} (id={v.id:3d})  hist={hist} corners={corners}')

        # ── 2. Non-commutativity ───────────────────────────────
        log('')
        log('-- 2. Non-commutativity (A→B vs B→A) --')
        from random import Random
        rng = Random(seed_base)
        # Sample 200 random ordered pairs; check A→B fingerprint vs B→A.
        n_pairs = min(200, n * (n - 1))
        pairs = []
        seen_pairs = set()
        while len(pairs) < n_pairs:
            a = rng.choice(verbs).id
            b = rng.choice(verbs).id
            if a == b or (a, b) in seen_pairs:
                continue
            seen_pairs.add((a, b))
            pairs.append((a, b))
        n_distinct_order = 0
        n_same = 0
        for a, b in pairs:
            ab = fingerprint(cascade(
                [rules[a], rules[b]], n_ticks_per=n_ticks)).key()
            ba = fingerprint(cascade(
                [rules[b], rules[a]], n_ticks_per=n_ticks)).key()
            if ab == ba:
                n_same += 1
            else:
                n_distinct_order += 1
        log(f'  pairs tested:        {n_pairs}')
        log(f'  order-distinguishable: {n_distinct_order} '
            f'({100*n_distinct_order/n_pairs:.0f}%)')
        log(f'  commuting:            {n_same} '
            f'({100*n_same/n_pairs:.0f}%)')

        # ── 3. Decodability (rough) ─────────────────────────────
        log('')
        log('-- 3. Decodability (1-rule cascade: can we recover which rule fired?) --')
        # For each verb, fire it from base state; ask: among all
        # single-rule fires, does its fingerprint match?
        target_to_verb: dict[tuple, list[int]] = {}
        for v in verbs:
            fp = fingerprint(fire(rules[v.id], n_ticks=n_ticks)).key()
            target_to_verb.setdefault(fp, []).append(v.id)
        n_recoverable = sum(1 for verb_ids in target_to_verb.values()
                             if len(verb_ids) == 1)
        log(f'  fingerprints that uniquely identify their verb: '
            f'{n_recoverable}/{n}')

        # ── 4. Cascade richness ────────────────────────────────
        log('')
        log('-- 4. Cascade richness (sample random 3-rule cascades) --')
        rng2 = Random(seed_base ^ 0xBEEF)
        cascade_prints: Counter[tuple] = Counter()
        for _ in range(n_cascade_samples):
            triple = [rng2.choice(verbs).id for _ in range(3)]
            fp = fingerprint(cascade(
                [rules[t] for t in triple],
                n_ticks_per=n_ticks)).key()
            cascade_prints[fp] += 1
        n_unique = sum(1 for c in cascade_prints.values() if c == 1)
        log(f'  sampled 3-step cascades: {n_cascade_samples}')
        log(f'  distinct fingerprints:   {len(cascade_prints)}')
        log(f'  unique (count==1):       {n_unique}')
        log(f'  most common bucket:      {cascade_prints.most_common(1)[0][1]} hits')

        # ── Verdict ────────────────────────────────────────────
        log('')
        log('-- Verdict --')
        d_pct = 100 * unique_count / n
        o_pct = 100 * n_distinct_order / max(1, n_pairs)
        r_pct = 100 * n_recoverable / n
        if d_pct >= 80 and o_pct >= 70 and r_pct >= 60:
            log('  ✓ Pans out: distinct fingerprints, non-commutative, '
                'decodable.  Composition algebra is viable.')
        elif d_pct >= 60:
            log('  ~ Partially: rules are distinct enough but '
                'composition / decodability is noisy.  Needs trained '
                'rules (not random) to be useful.')
        else:
            log("  × Doesn't pan out (random rules collide too much). "
                "Would need either bigger LUT (cell8?), more ticks, "
                "or per-token training to spread them out.")
