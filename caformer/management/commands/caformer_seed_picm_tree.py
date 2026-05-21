"""Seed a starter PICM tree.

The tree is up to 4 levels deep × 4 children per level (max 256
leaves).  This seed populates:

  - Top 4 nodes (depth 0): personality / information / command / meta
  - Information's 4 children (depth 1): who / what / where / when
  - Information.who's 4 grandchildren (depth 2): living / historical /
    fictional / institutional — as leaves connecting out to
    QRPair labels + template tags

Other top-level branches get 1-level scaffolding to be filled in
later via admin or by re-editing this command.

Re-runnable: upserts by tree_path.
"""
from __future__ import annotations

from django.core.management.base import BaseCommand

from caformer.models import PICMNode


# (tree_path, label, relevance_tokens, is_leaf, qrpair_label, template_tag, notes)
NODES = [
    # ── Depth 0: top-level routing (mirrors boardstack4 colours) ──
    ('0', 'personality',
        ['hi', 'hey', 'hello', 'yo', 'sup', 'bye', 'thx', 'ty',
         'ok', 'yes', 'no', 'nope', 'cool', 'wow', 'lol', 'omg'],
        False, '', '',
        'social / register surface'),

    ('1', 'information',
        ['how', 'what', 'when', 'who', 'why', 'where',
         'look', 'wiki', 'find', 'fact', 'info', 'is', 'are',
         'was', 'will'],
        False, '', '',
        'factual + lookup queries'),

    ('2', 'command',
        ['run', 'exec', 'make', 'write', 'fix', 'show',
         'list', 'open', 'save', 'ls', 'cd', 'cat', 'grep',
         'find', 'int', 'void', 'main'],
        False, '', '',
        'imperative / agent layer'),

    ('3', 'meta',
        ['self', 'why', 'how', 'reflect', 'consider',
         'think', 'mean', 'know', 'unsure', 'maybe'],
        False, '', '',
        'introspection / ambiguous / multi-step'),

    # ── Depth 1: Personality sub-routes (user request 2026-05-21) ──
    # The personality umbrella covers four distinct conversational
    # registers — each picks up different relevance tokens and would
    # eventually route to a tailored persona response.
    ('0.0', 'informative',
        ['fact', 'note', 'know', 'fyi', 'btw', 'also',
         'cool', 'wow', 'nice', 'huh', 'oh', 'ah'],
        True, '', '',
        'informative personality — sharing observations, '
        'reactions, light facts in a personal register'),

    ('0.1', 'social',
        ['hi', 'hey', 'hello', 'yo', 'sup', 'bye', 'thx',
         'ty', 'np', 'lol', 'omg', 'cheers', 'welcome',
         'pleas', 'sorry'],
        True, '', '',
        'social personality — greetings, farewells, '
        'phatic exchange, courtesy'),

    ('0.2', 'practical',
        ['help', 'fix', 'try', 'go', 'do', 'ok', 'yes', 'no',
         'sure', 'maybe', 'plan', 'idea', 'next'],
        True, '', '',
        'practical personality — getting-things-done in a '
        'conversational register, soft directives'),

    ('0.3', 'persuasive',
        ['should', 'must', 'could', 'would', 'maybe',
         'best', 'better', 'try', 'urge', 'reco',
         'sugg', 'opin', 'feel'],
        True, '', '',
        'persuasive personality — recommendations, opinions, '
        'encouragement, gentle persuasion'),

    # ── Depth 1: Information's 5W children (who/what/where/when) ──
    ('1.0', 'who-queries',
        ['who', 'whose', 'whom'],
        False, '', '',
        'who is X — person/entity identity'),

    ('1.1', 'what-queries',
        ['what', 'which', 'whatever'],
        False, '', '',
        'what is X — definition/description'),

    ('1.2', 'where-queries',
        ['where', 'wherever', 'located', 'place'],
        False, '', '',
        'where is X — location'),

    ('1.3', 'when-queries',
        ['when', 'date', 'year', 'time', 'era', 'age'],
        False, '', '',
        'when was X — time'),

    # ── Depth 2: under who-queries, 4 sub-types as LEAVES ──
    ('1.0.0', 'who-living',
        ['is', 'now', 'today', 'current', 'lives', 'alive'],
        True, 'who-living', 'who-living',
        'living person — current-day identity lookup'),

    ('1.0.1', 'who-historical',
        ['was', 'were', 'lived', 'old', 'ancient', 'past',
         'history', 'died'],
        True, 'who-historical', 'who-historical',
        'historical person — past-tense identity lookup'),

    ('1.0.2', 'who-fictional',
        ['book', 'novel', 'story', 'film', 'movie',
         'char', 'show', 'play'],
        True, 'who-fictional', 'who-fictional',
        'fictional character — book/film/show'),

    ('1.0.3', 'who-institutional',
        ['ceo', 'pres', 'lead', 'head', 'chair', 'board',
         'org', 'gov'],
        True, 'who-institutional', 'who-institutional',
        'institutional role — CEO/president/etc.'),

    # ── Depth 2: under what-queries, 4 sub-types as LEAVES ──
    ('1.1.0', 'what-definition',
        ['is', 'means', 'mean', 'defined', 'def'],
        True, 'what-definition', 'what-definition',
        'definition of X — "what is X?"'),

    ('1.1.1', 'what-description',
        ['look', 'like', 'looks', 'looked', 'feel', 'sound'],
        True, 'what-description', 'what-description',
        'description of X — "what does X look like?"'),

    ('1.1.2', 'what-comparison',
        ['diff', 'vs', 'or', 'than', 'better', 'worse',
         'more', 'less'],
        True, 'what-comparison', 'what-comparison',
        'comparison — "what is the difference between X and Y?"'),

    ('1.1.3', 'what-enumeration',
        ['types', 'kinds', 'list', 'all', 'each', 'every',
         'most', 'best'],
        True, 'what-enumeration', 'what-enumeration',
        'enumeration — "what are the types of X?"'),
]


class Command(BaseCommand):
    help = 'Seed the PICM tree (PICMNode rows).'

    def add_arguments(self, parser):
        parser.add_argument('--wipe', action='store_true',
                              help='delete all existing rows before seed.')

    def handle(self, *, wipe, **opts):
        if wipe:
            n = PICMNode.objects.all().delete()[0]
            self.stdout.write(f'wiped {n} existing PICMNode rows')

        n_new, n_upd = 0, 0
        for (path, label, tokens, is_leaf,
             qrpair_label, template_tag, notes) in NODES:
            row, created = PICMNode.objects.update_or_create(
                tree_path=path,
                defaults={
                    'label':            label,
                    'relevance_tokens': list(tokens),
                    'is_leaf':          is_leaf,
                    'qrpair_label':     qrpair_label,
                    'template_tag':     template_tag,
                    'notes':            notes,
                    'confidence':       0.7,
                },
            )
            if created: n_new += 1
            else:       n_upd += 1
            mark = 'L' if is_leaf else '·'
            self.stdout.write(
                f'  {"+" if created else "·"} {mark} {path:<8} '
                f'{label:<20} ({len(tokens):>2} tokens)')

        self.stdout.write(self.style.SUCCESS(
            f'Seeded {len(NODES)} PICMNode rows ({n_new} new, {n_upd} updated).'))
