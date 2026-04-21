"""evolution evolve_lut — headless port of engine.mjs's LUT gene handler.

Mirrors the JS `lutRandom`/`lutMutate`/`lutWork` from
evolution/static/evolution/engine.mjs so a run from the CLI or cron
produces the same scoring landscape as the /casting/<slug>/ LUT
evolution lab page. Useful for batch sweeps, reproducibility (--seed)
and ALICE/HPC dispatch.

Gene shape: {n, h, bits} — tiny n→h→1 MLP, ±1 weights, sign activation,
LSB-first bitstring. Compatible with byte_model_runtime.

Usage:
    manage.py evolve_lut                          # sweep all canonical targets
    manage.py evolve_lut --target 3-MAJ           # single target
    manage.py evolve_lut --name custom --n 4 --tt 0xe880
    manage.py evolve_lut --seed 42 --pop 48 --gens 600
    manage.py evolve_lut --save pool.json         # dump solvers in casting-pool-v1 shape
"""

from __future__ import annotations

import json
import random
from datetime import datetime, timezone

from django.core.management.base import BaseCommand, CommandError


# ── Canonical targets (match byte_model_evolution.js TARGETS) ────────
CANONICAL_TARGETS = [
    {'name': '2-AND',  'n': 2, 'tt': 0x8},
    {'name': '2-OR',   'n': 2, 'tt': 0xe},
    {'name': '2-XOR',  'n': 2, 'tt': 0x6},
    {'name': '3-AND',  'n': 3, 'tt': 0x80},
    {'name': '3-OR',   'n': 3, 'tt': 0xfe},
    {'name': '3-MAJ',  'n': 3, 'tt': 0xe8},
    {'name': '3-MUX',  'n': 3, 'tt': 0xca},
    {'name': '3-XOR',  'n': 3, 'tt': 0x69},
    {'name': '4-OR',   'n': 4, 'tt': 0xfffe},
    {'name': '4-AND',  'n': 4, 'tt': 0x8000},
    {'name': '4-MAJ',  'n': 4, 'tt': 0xe880},
    {'name': '4-thr2', 'n': 4, 'tt': 0xfee8},
    {'name': '4-XOR',  'n': 4, 'tt': 0x6996},
]

LUT_MAX_H = 4


# ── Architecture helpers (mirror engine.mjs) ─────────────────────────
def lut_total_bits(n: int, h: int) -> int:
    return h * (n + 2) + 1 if h > 0 else (n + 1)


def _wb(bits: int, k: int) -> int:
    return 1 if ((bits >> k) & 1) else -1


def lut_forward(bits: int, n: int, h: int, row: int) -> int:
    xi = [(1 if ((row >> (n - 1 - i)) & 1) else -1) for i in range(n)]
    idx = 0
    if h == 0:
        s = 0
        for i in range(n):
            s += _wb(bits, idx) * xi[i]
            idx += 1
        b = _wb(bits, idx); idx += 1
        return 1 if (s + b) >= 0 else -1
    hid = [0] * h
    for j in range(h):
        s = 0
        for i in range(n):
            s += _wb(bits, idx) * xi[i]
            idx += 1
        b = _wb(bits, idx); idx += 1
        hid[j] = 1 if (s + b) >= 0 else -1
    s = 0
    for j in range(h):
        s += _wb(bits, idx) * hid[j]
        idx += 1
    b = _wb(bits, idx)
    return 1 if (s + b) >= 0 else -1


def lut_truth_table(gene: dict) -> int:
    n, h, bits = int(gene['n']), int(gene['h']), int(gene['bits']) & 0xffffffff
    N = 1 << n
    tt = 0
    for row in range(N):
        if lut_forward(bits, n, h, row) > 0:
            tt |= (1 << row)
    return tt & 0xffffffff


def _popcount(x: int) -> int:
    return bin(x & 0xffffffff).count('1')


# ── Gene operators (mirror engine.mjs lutRandom / lutMutate) ─────────
def lut_random(n: int) -> dict:
    h = random.randint(0, LUT_MAX_H)
    W = lut_total_bits(n, h)
    bits = 0
    for i in range(W):
        if random.random() < 0.5:
            bits |= (1 << i)
    return {'n': n, 'h': h, 'bits': bits & 0xffffffff}


def lut_mutate(gene: dict, rate: float) -> dict:
    nxt = {'n': gene['n'], 'h': gene['h'], 'bits': int(gene['bits']) & 0xffffffff}
    W = lut_total_bits(nxt['n'], nxt['h'])
    for i in range(W):
        if random.random() < rate:
            nxt['bits'] ^= (1 << i)
    nxt['bits'] &= 0xffffffff
    if random.random() < rate * 0.15:
        d = -1 if random.random() < 0.5 else 1
        new_h = max(0, min(LUT_MAX_H, nxt['h'] + d))
        if new_h != nxt['h']:
            new_W = lut_total_bits(nxt['n'], new_h)
            if new_W < W:
                nxt['bits'] &= (1 << new_W) - 1
            else:
                for i in range(W, new_W):
                    if random.random() < 0.5:
                        nxt['bits'] |= (1 << i)
                nxt['bits'] &= 0xffffffff
            nxt['h'] = new_h
    return nxt


def lut_score(gene: dict, target_tt: int, n: int) -> tuple[float, int]:
    """(score, tt). Matches lutWork: right/N, with -0.0001*W tiebreak on perfect."""
    tt = lut_truth_table(gene)
    N = 1 << n
    mask = 0xffffffff if N >= 32 else ((1 << N) - 1)
    wrong = _popcount((tt ^ (target_tt & 0xffffffff)) & mask)
    right = N - wrong
    W = lut_total_bits(gene['n'], gene['h'])
    s = right / N
    if s >= 1 - 1e-9:
        s = 1.0 - 0.0001 * W
    return s, tt


# ── GA loop ──────────────────────────────────────────────────────────
def run_ga(target_name: str, n: int, target_tt: int, *,
           population: int = 48, generations: int = 600,
           mutation_rate: float = 0.08, tournament_k: int = 3,
           progress_every: int = 100, stdout=None):
    pop = []
    for _ in range(population):
        g = lut_random(n)
        sc, tt = lut_score(g, target_tt, n)
        pop.append({'gene': g, 'score': sc, 'tt': tt})
    best = max(pop, key=lambda a: a['score'])
    for gen in range(generations):
        pop.sort(key=lambda a: a['score'], reverse=True)
        if pop[0]['score'] > best['score']:
            best = pop[0]
        if stdout is not None and progress_every and (gen + 1) % progress_every == 0:
            stdout.write(f'    gen {gen + 1}/{generations}  best={best["score"]:.5f}')
        # perfect solver? keep polishing for a few gens then stop
        if best['score'] >= 0.9999 and gen >= 10:
            # Already at W-tiebreak regime; keep full budget for further
            # compaction, but allow early exit if no progress in last 50 gens.
            pass
        nxt = [pop[0]]   # elitism
        while len(nxt) < population:
            winner = max(
                (pop[random.randrange(len(pop))] for _ in range(tournament_k)),
                key=lambda a: a['score'],
            )
            child_gene = lut_mutate(winner['gene'], mutation_rate)
            sc, tt = lut_score(child_gene, target_tt, n)
            nxt.append({'gene': child_gene, 'score': sc, 'tt': tt})
        pop = nxt
    return best


# ── Command ──────────────────────────────────────────────────────────
class Command(BaseCommand):
    help = ('Run the LUT gene-type GA (from evolution/engine.mjs) '
            'headless against one or more boolean targets. Sweeps the '
            'full canonical target list by default.')

    def add_arguments(self, parser):
        parser.add_argument('--target', type=str, default=None,
                            help='Canonical target name (e.g. "3-MAJ"). '
                                 'Omit to sweep all.')
        parser.add_argument('--name', type=str, default=None,
                            help='Custom target name (with --n and --tt).')
        parser.add_argument('--n', type=int, default=None,
                            help='Custom target input count (2..5).')
        parser.add_argument('--tt', type=str, default=None,
                            help='Custom target truth table (int or 0xHEX).')
        parser.add_argument('--pop', type=int, default=48)
        parser.add_argument('--gens', type=int, default=600)
        parser.add_argument('--mutation-rate', type=float, default=0.08)
        parser.add_argument('--tournament-k', type=int, default=3)
        parser.add_argument('--seed', type=int, default=None,
                            help='Optional RNG seed for reproducibility.')
        parser.add_argument('--save', type=str, default=None,
                            help='Path to write casting-pool-v1 JSON of solvers.')

    def handle(self, *args, **options):
        if options['seed'] is not None:
            random.seed(options['seed'])

        custom = options.get('name') or options.get('n') is not None or options.get('tt')
        if custom:
            if not (options.get('name') and options.get('n') is not None
                    and options.get('tt') is not None):
                raise CommandError('--name, --n, and --tt must all be given together.')
            tt_raw = options['tt']
            try:
                tt = int(tt_raw, 0)
            except (TypeError, ValueError):
                raise CommandError(f'Invalid --tt {tt_raw!r}; use int or 0xHEX.')
            n = int(options['n'])
            if not (1 <= n <= 5):
                raise CommandError(f'--n must be 1..5 (got {n}).')
            targets = [{'name': options['name'], 'n': n, 'tt': tt}]
        elif options.get('target'):
            wanted = options['target']
            found = [t for t in CANONICAL_TARGETS if t['name'] == wanted]
            if not found:
                names = ', '.join(t['name'] for t in CANONICAL_TARGETS)
                raise CommandError(
                    f'Unknown target {wanted!r}. Canonical targets: {names}')
            targets = found
        else:
            targets = list(CANONICAL_TARGETS)

        pop  = options['pop']
        gens = options['gens']
        rate = options['mutation_rate']
        k    = options['tournament_k']

        self.stdout.write(
            f'evolve_lut: {len(targets)} target(s); pop={pop} gens={gens} '
            f'rate={rate} k={k}'
        )

        solvers = []
        solved = 0
        for i, tgt in enumerate(targets, 1):
            self.stdout.write(
                f'[{i}/{len(targets)}] {tgt["name"]}  '
                f'(n={tgt["n"]}, tt=0x{tgt["tt"]:x})'
            )
            best = run_ga(
                tgt['name'], tgt['n'], tgt['tt'],
                population=pop, generations=gens,
                mutation_rate=rate, tournament_k=k,
                stdout=self.stdout,
            )
            perfect = (best['tt'] == (tgt['tt'] & 0xffffffff))
            W = lut_total_bits(best['gene']['n'], best['gene']['h'])
            tag = 'SOLVED' if perfect else 'partial'
            msg = (f'    → {tag}: score={best["score"]:.5f}  '
                   f'h={best["gene"]["h"]} W={W} '
                   f'bits=0x{best["gene"]["bits"]:x} '
                   f'got=0x{best["tt"]:x}')
            if perfect:
                self.stdout.write(self.style.SUCCESS(msg))
                solved += 1
                solvers.append({
                    'name': tgt['name'],
                    'n': tgt['n'],
                    'truth_table': tgt['tt'],
                    'h': best['gene']['h'],
                    'weight_bits': W,
                    'bits': best['gene']['bits'],
                })
            else:
                self.stdout.write(msg)

        self.stdout.write(self.style.SUCCESS(
            f'done. solved {solved}/{len(targets)}.'
        ))

        if options.get('save'):
            out = {
                'format': 'casting-pool-v1',
                'arch_family': ('MLP n→h→1, ±1 weights, sign activation, '
                                'LSB-first bitstring'),
                'note': ('Produced by evolve_lut management command. '
                         'Compatible with byte_model_runtime.'),
                'generated_at': datetime.now(timezone.utc).isoformat(),
                'pool': solvers,
            }
            path = options['save']
            with open(path, 'w', encoding='utf-8') as f:
                json.dump(out, f, indent=2)
            self.stdout.write(self.style.SUCCESS(
                f'wrote {len(solvers)} solver(s) to {path}.'
            ))
