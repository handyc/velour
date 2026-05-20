"""Smoke test: build a random stack genome, run it through the
test set, report fitness.  Phase 0 — no GA, just baseline."""
from __future__ import annotations

import sys
import time

from django.core.management.base import BaseCommand


class Command(BaseCommand):
    help = ('Run a single random stack genome against a test set, '
            'report the baseline fitness.')

    def add_arguments(self, parser):
        parser.add_argument('--seed', type=int, default=42)
        parser.add_argument('--n-boards', type=int, default=16)
        parser.add_argument('--board-side', type=int, default=64)
        parser.add_argument('--stack-ticks', type=int, default=4)
        parser.add_argument('--test-set', type=str, default='v1',
                              choices=['v1', 'incr', 'echo'])
        parser.add_argument('--personality', type=int, default=0,
                              choices=[0, 1, 2, 3])
        parser.add_argument('--persist', action='store_true',
                              help='save the genome to the StackGenome table')

    def handle(self, *, seed, n_boards, board_side, stack_ticks,
                 test_set, personality, persist, **opts):
        from boardstack.population import pool_size
        from boardstack.genome import random_genome
        from boardstack.fitness import evaluate
        from boardstack.models import StackGenome
        import json

        def log(m): self.stdout.write(m + '\n')

        ps = pool_size()
        if ps == 0:
            self.stderr.write('No LUTs in pool; run mandelhunt first.\n')
            return
        log(f'=== boardstack_smoke ===')
        log(f'  pool size:   {ps} class-4 LUTs')
        log(f'  n_boards:    {n_boards}')
        log(f'  board_side:  {board_side}')
        log(f'  stack_ticks: {stack_ticks}')
        log(f'  test_set:    {test_set}')
        log(f'  personality: {personality}')
        log(f'  seed:        0x{seed:08x}\n')

        g = random_genome(n_boards=n_boards, board_side=board_side,
                              pool_size=ps, stack_ticks=stack_ticks,
                              seed=seed)
        log(f'  gene rule_idx: {g["rule_idx"][:8]}{"..." if len(g["rule_idx"]) > 8 else ""}')
        log(f'  gene ticks:    {g["ticks"]}')
        log(f'  output_cell:   {g["output_cell"]}\n')

        t0 = time.time()
        r = evaluate(g, test_set_id=test_set, personality=personality)
        wall = time.time() - t0

        log(f'=== results ({wall:.2f}s) ===')
        log(f'  byte_match:  {r["byte_match"]}/{r["n_pairs"]} '
            f'({r["byte_match_rate"]*100:.1f}%)')
        log(f'  bit_match:   {r["bit_match"]}/{8*r["n_pairs"]} '
            f'({r["bit_match_rate"]*100:.1f}%)  (random baseline ≈ 50%)')
        log(f'  fitness:     {r["fitness"]:.4f}')
        log('')
        log(f'  per-pair (p → q → out):')
        for x in r['results']:
            tag = '✓' if x['match'] else f'{x["bits_match"]}/8'
            p = chr(x['p']) if 32 <= x['p'] < 127 else f'\\x{x["p"]:02x}'
            q = chr(x['q']) if 32 <= x['q'] < 127 else f'\\x{x["q"]:02x}'
            o = chr(x['out']) if 32 <= x['out'] < 127 else f'\\x{x["out"]:02x}'
            log(f'    {p!r} → target {q!r}, produced {o!r}  {tag}')

        if persist:
            slug = f'smoke-seed{seed:08x}-{test_set}-{n_boards}x{board_side}'[:80]
            obj, created = StackGenome.objects.update_or_create(
                slug=slug, defaults={
                    'n_boards': n_boards, 'board_side': board_side,
                    'gene_json': json.loads(json.dumps(g, default=list)),
                    'fitness':  r['fitness'],
                    'test_set_id': test_set,
                    'notes': f'random gene seed={hex(seed)}',
                })
            log(f'\n  saved StackGenome slug={slug} (created={created})')
