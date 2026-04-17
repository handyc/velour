"""evolution speciate — automatic Grammar×Evolution loop.

Each round:
  1. Pick a random Grammar Engine Language (one that has ≥1 grammar variant).
  2. Pick a random variant, expand it → goal_string.
  3. Run a Python-side L0 L-system GA (same gene shape as evolution/static/
     evolution/engine.mjs) against that goal.
  4. Export the best agent as a new derived Language.

This is the "automatic" part of the evolve-new-languages-from-random-goals
workflow. The browser engine still drives interactive runs; this command is
for background batch speciation from the shell or a cron.

Kept separate from the browser engine to avoid a headless-browser dep;
the GA here mirrors engine.mjs's lsystem handler in a small Python port.
"""

import random
import secrets

from django.core.management.base import BaseCommand
from django.db import transaction

from evolution.models import Agent as AgentModel, EvolutionRun


LSYS_ALPHABET = 'F+-[]X'
SCORE_CAP_LEN = 256
MAX_EXPAND_LEN = 4000


# ── L-system expansion + scoring ─────────────────────────────────────
def expand_lsystem(axiom, rules, iterations, max_len=MAX_EXPAND_LEN):
    s = axiom or ''
    iters = max(0, min(8, int(iterations or 0)))
    for _ in range(iters):
        out = []
        total = 0
        for ch in s:
            r = rules.get(ch, ch) if rules else ch
            out.append(r)
            total += len(r)
            if total > max_len:
                break
        s = ''.join(out)[:max_len]
    return s


def levenshtein(a, b):
    if a == b:
        return 0
    if not a:
        return len(b)
    if not b:
        return len(a)
    prev = list(range(len(b) + 1))
    for i, ca in enumerate(a, 1):
        curr = [i] + [0] * len(b)
        for j, cb in enumerate(b, 1):
            cost = 0 if ca == cb else 1
            curr[j] = min(prev[j] + 1, curr[j - 1] + 1, prev[j - 1] + cost)
        prev = curr
    return prev[-1]


def score_string(output, goal):
    a = (output or '')[:SCORE_CAP_LEN]
    b = (goal or '')[:SCORE_CAP_LEN]
    if not a and not b:
        return 1.0
    d = levenshtein(a, b)
    denom = max(len(a), len(b), 1)
    return max(0.0, 1.0 - d / denom)


# ── Gene helpers (mirror engine.mjs lsystem handler) ─────────────────
def balance_brackets(s):
    depth = 0
    out = []
    for ch in s:
        if ch == '[':
            depth += 1
            out.append(ch)
        elif ch == ']':
            if depth > 0:
                depth -= 1
                out.append(ch)
        else:
            out.append(ch)
    out.extend([']'] * depth)
    return ''.join(out)


def random_rule_body():
    n = random.randint(3, 10)
    return balance_brackets(''.join(random.choice(LSYS_ALPHABET) for _ in range(n)))


def random_gene():
    n_rules = random.randint(1, 3)
    rules = {}
    for _ in range(n_rules):
        k = random.choice(['F', 'X'])
        rules[k] = random_rule_body()
    return {
        'axiom': random.choice(['F', 'X', 'F+F', 'FX']),
        'rules': rules,
        'iterations': random.randint(2, 4),
    }


def mutate_rule_body(s):
    if not s:
        return random.choice(LSYS_ALPHABET)
    op = random.randint(0, 2)
    if op == 0 and len(s) < 24:
        i = random.randint(0, len(s))
        return balance_brackets(s[:i] + random.choice(LSYS_ALPHABET) + s[i:])
    if op == 1 and len(s) > 1:
        i = random.randrange(len(s))
        return balance_brackets(s[:i] + s[i + 1:])
    i = random.randrange(len(s))
    return balance_brackets(s[:i] + random.choice(LSYS_ALPHABET) + s[i + 1:])


def mutate_gene(gene, rate):
    nxt = {
        'axiom': gene.get('axiom', 'F'),
        'rules': dict(gene.get('rules') or {}),
        'iterations': int(gene.get('iterations') or 2),
    }
    for k in list(nxt['rules'].keys()):
        if random.random() < rate:
            nxt['rules'][k] = mutate_rule_body(nxt['rules'][k])
    if random.random() < rate * 0.5:
        k = random.choice(['F', 'X'])
        if k not in nxt['rules']:
            nxt['rules'][k] = random_rule_body()
    if random.random() < rate * 0.4:
        d = -1 if random.random() < 0.5 else 1
        nxt['iterations'] = max(1, min(6, nxt['iterations'] + d))
    if random.random() < rate * 0.2:
        nxt['axiom'] = mutate_rule_body(nxt.get('axiom') or 'F')
    return nxt


def evaluate(gene, goal):
    s = expand_lsystem(gene['axiom'], gene.get('rules') or {}, gene.get('iterations') or 2)
    return score_string(s, goal), s


def run_ga(goal, generations=80, population=24, mutation_rate=0.25, tournament_k=3):
    pop = []
    for _ in range(population):
        g = random_gene()
        sc, out = evaluate(g, goal)
        pop.append({'gene': g, 'score': sc, 'output': out})
    best = max(pop, key=lambda a: a['score'])
    for _ in range(generations):
        pop.sort(key=lambda a: a['score'], reverse=True)
        elite = pop[0]
        if elite['score'] > best['score']:
            best = elite
        nxt = [elite]
        while len(nxt) < population:
            winner = max(
                (pop[random.randrange(len(pop))] for _ in range(tournament_k)),
                key=lambda a: a['score'],
            )
            child_gene = mutate_gene(winner['gene'], mutation_rate)
            sc, out = evaluate(child_gene, goal)
            nxt.append({'gene': child_gene, 'score': sc, 'output': out})
        pop = nxt
    return best


# ── Language export (mirrors evolution.views.agent_export_grammar) ──
def export_as_language(gene, score_val, source_language, source_variant,
                       goal_preview):
    from grammar_engine.models import Language

    src_stub = source_language.slug
    # Avoid "evo-evo-evo-..." chains as we speciate speciated languages.
    if src_stub.startswith('evo-'):
        src_stub = src_stub[4:]
    src_stub = src_stub[:40]
    var_stub = source_variant.split('/')[-1][:20]
    base = f'evo-{src_stub}-{var_stub}'
    name = base
    n = 2
    while Language.objects.filter(name=name).exists():
        name = f'{base}-{n}'
        n += 1

    rules = {k: v for k, v in (gene.get('rules') or {}).items()
             if isinstance(v, str)}
    spec = {
        'grammars': {
            'evolved': {
                'note': (f'Bred from goal "{source_variant}" of '
                         f'"{source_language.name}" (score {score_val:.3f}).'),
                'axiom': gene.get('axiom') or 'F',
                'iterations': int(gene.get('iterations') or 4),
                'variants': {
                    'primary': rules,
                },
            },
        },
    }
    return Language.objects.create(
        name=name,
        seed=secrets.randbits(31),
        spec=spec,
        notes=(f'Speciated from "{source_language.name}" / '
               f'variant "{source_variant}".\n'
               f'Goal preview: {goal_preview[:160]}'),
    )


# ── Command ──────────────────────────────────────────────────────────
class Command(BaseCommand):
    help = ('Run N rounds of "random goal → evolve → save as new Language". '
            'Each round picks a random source Language + variant, treats '
            'its expansion as the evolution goal, runs a short L0 L-system '
            'GA, and saves the best agent as a derived Language.')

    def add_arguments(self, parser):
        parser.add_argument('--rounds', type=int, default=3)
        parser.add_argument('--generations', type=int, default=80)
        parser.add_argument('--population', type=int, default=24)
        parser.add_argument('--mutation-rate', type=float, default=0.25)
        parser.add_argument('--seed', type=int, default=None,
                            help='Optional RNG seed for reproducibility.')
        parser.add_argument('--save-run', action='store_true',
                            help='Also create an EvolutionRun row for each '
                                 'round as a paper trail.')

    def handle(self, *args, **options):
        from grammar_engine.models import Language

        if options['seed'] is not None:
            random.seed(options['seed'])

        candidates = list(Language.objects.all())
        with_variants = [L for L in candidates if L.first_variant() is not None]
        if not with_variants:
            self.stdout.write(self.style.ERROR(
                'No Grammar Engine Languages with grammar variants found. '
                'Create/seed at least one first (grammar_engine admin).'
            ))
            return

        rounds = options['rounds']
        gens   = options['generations']
        pop    = options['population']
        rate   = options['mutation_rate']

        self.stdout.write(
            f'speciating {rounds} round(s); pop={pop} gens={gens} '
            f'rate={rate} sources={len(with_variants)}'
        )
        total_created = 0
        for r in range(rounds):
            src = random.choice(with_variants)
            first = src.first_variant()
            cat_name, var_name, axiom, iters, rules = first
            # Pick any variant at random, not just the first
            variants_list = list(src.variants())
            if variants_list:
                cat_name, var_name, axiom, iters, rules = random.choice(variants_list)
            goal = expand_lsystem(axiom, rules, iters)
            goal_preview = goal[:80] + ('…' if len(goal) > 80 else '')
            self.stdout.write(
                f'[{r + 1}/{rounds}] src="{src.name}" '
                f'variant="{cat_name}/{var_name}" '
                f'goal_len={len(goal)} preview="{goal_preview}"'
            )

            best = run_ga(goal, generations=gens, population=pop,
                          mutation_rate=rate)

            with transaction.atomic():
                new_lang = export_as_language(
                    best['gene'], best['score'], src,
                    f'{cat_name}/{var_name}', goal_preview,
                )
                run_obj = None
                if options['save_run']:
                    run_obj = EvolutionRun.objects.create(
                        name=f'speciate-{new_lang.slug}',
                        level=0,
                        goal_string=goal[:2000],
                        goal_language=src,
                        goal_variant=f'{cat_name}/{var_name}',
                        population_size=pop,
                        generations_target=gens,
                        target_score=1.0,
                        params={'mutation_rate': rate, 'tournament_k': 3,
                                'via': 'speciate-command'},
                        status='finished',
                        generation=gens,
                        best_score=best['score'],
                        notes=(f'Auto-speciated. Produced Language '
                               f'"{new_lang.name}".'),
                    )
                    AgentModel.objects.create(
                        name=f'speciate-best-{new_lang.slug}',
                        level=0,
                        gene=best['gene'],
                        seed_string='',
                        score=best['score'],
                        source_run=run_obj,
                        notes=(f'Best agent from speciate round {r + 1}. '
                               f'Exported as Language "{new_lang.name}".'),
                    )
            total_created += 1
            self.stdout.write(self.style.SUCCESS(
                f'    → Language "{new_lang.name}" (score {best["score"]:.3f})'
            ))

        self.stdout.write(self.style.SUCCESS(
            f'done. created {total_created} derived language(s).'
        ))
