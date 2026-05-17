"""manage.py assemble_from_champions <slug>

Build a TrainedModel from the best ComponentChampion for each rule
slot.  Goal: produce a model whose 10 rule LUTs are genuinely
distinct (and individually optimised against per-component fitness),
instead of relying on a whole-stack GA that often collapses several
slots to byte-identical LUTs.

Strategy: for each of the 10 named rules (q, k, v, score, mix, merge,
mlp, norm, output, embed), pick the best champion whose bundle
contains that rule, preferring single-rule (focused) champions when
available.  Falls back to multi-rule bundles for slots only covered
by composite champions.
"""
from django.core.management.base import BaseCommand, CommandError


# Per-rule preference list — first slug in each list with at least
# one champion wins.  Most specific first.
_RULE_TO_SLUGS = {
    'q':      ('q_proj', 'projection', 'self_attention', 'transformer'),
    'k':      ('k_proj', 'self_attention', 'transformer'),
    'v':      ('v_proj', 'self_attention', 'transformer'),
    'score':  ('score_solo', 'self_attention', 'transformer'),
    'mix':    ('mix_solo', 'self_attention', 'transformer'),
    'merge':  ('merge_solo', 'transformer'),
    'mlp':    ('mlp', 'transformer'),
    'norm':   ('layer_norm',),
    'output': ('output', 'softmax'),
    'embed':  ('embedding',),
}


class Command(BaseCommand):
    help = 'Assemble a TrainedModel by picking the best champion for each rule slot.'

    def add_arguments(self, parser):
        parser.add_argument('slug',
                              help='Slug to give the assembled TrainedModel.')
        parser.add_argument('--name', default=None,
                              help='Display name (default: "assembled-<slug>").')
        parser.add_argument('--n-blocks', type=int, default=2,
                              help='Inference block count baked into the model row.')
        parser.add_argument('--notes', default='',
                              help='Optional notes saved on the row.')

    def handle(self, *args, **opts):
        from caformer.models import ComponentChampion, TrainedModel

        provenance = {}
        rule_bytes = {}
        for rule, slug_pref in _RULE_TO_SLUGS.items():
            champ = None
            chosen_slug = None
            for s in slug_pref:
                cand = (ComponentChampion.objects
                                            .filter(component_slug=s)
                                            .order_by('-fitness', '-created_at')
                                            .first())
                if cand is not None:
                    try:
                        rule_bytes[rule] = cand.rule_table(rule)
                    except KeyError:
                        # Bundle doesn't actually contain this rule
                        # (mis-registered champion).  Skip and try next.
                        continue
                    champ = cand
                    chosen_slug = s
                    break
            if champ is None:
                raise CommandError(
                    f'no champion bundle covers rule {rule!r} — none of '
                    f'{slug_pref!r} have a champion with this rule.')
            provenance[rule] = {
                'champion_id':   champ.pk,
                'component_slug': chosen_slug,
                'fitness':       champ.fitness,
                'generation':    champ.generation,
            }
            self.stdout.write(
                f'  {rule:<6s} ← {chosen_slug:<16s} '
                f'(champion #{champ.pk}, fitness={champ.fitness:.4f})')

        name = opts['name'] or f'assembled-{opts["slug"]}'
        obj, _ = TrainedModel.objects.update_or_create(
            slug=opts['slug'],
            defaults=dict(
                name=name,
                notes=opts['notes'] + (
                    '\n\nAssembled from ComponentChampions: ' +
                    ', '.join(f'{r}=#{p["champion_id"]}@{p["component_slug"]}'
                                for r, p in provenance.items())),
                rule_q     =bytes(rule_bytes['q']),
                rule_k     =bytes(rule_bytes['k']),
                rule_v     =bytes(rule_bytes['v']),
                rule_score =bytes(rule_bytes['score']),
                rule_mix   =bytes(rule_bytes['mix']),
                rule_merge =bytes(rule_bytes['merge']),
                rule_mlp   =bytes(rule_bytes['mlp']),
                rule_norm  =bytes(rule_bytes['norm']),
                rule_output=bytes(rule_bytes['output']),
                rule_embed =bytes(rule_bytes['embed']),
                vocab_size=256,
                n_blocks=opts['n_blocks'],
                pop_size=0, generations=0,
                final_fitness=sum(p['fitness'] for p in provenance.values())
                                / max(1, len(provenance)),
                history_json=[],
            ),
        )

        d = obj.rule_diversity()
        self.stdout.write(
            f'\nAssembled {obj.slug!r}: {d["distinct_count"]}/10 distinct LUTs, '
            f'mean pairwise match {d["mean_pairwise_match"]:.4f}')
