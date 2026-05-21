"""Seed PersonalityModule rows.

Each module owns its own 4-way subroute taxonomy.  Once seeded, a
HarnessProfile can point to one via personality_module_slug and the
harness will use that module's subroute tokens when descending under
the personality root.

  manage.py caformer_seed_personality_modules
"""
from __future__ import annotations

from django.core.management.base import BaseCommand


# Each entry: (slug, name, description, subroutes)
# Each subroute: (label, tokens, notes)
MODULES = [
    ('velour', 'Velour',
     'The default Velour conversational register — gentle, '
     'observational, helpful.',
     [
         ('Informative',
          ['fact', 'note', 'know', 'fyi', 'btw', 'also',
           'cool', 'wow', 'nice', 'huh', 'oh', 'ah'],
          'Sharing observations and reactions in a personal voice.'),
         ('Social',
          ['hi', 'hey', 'hello', 'yo', 'sup', 'bye', 'thx',
           'ty', 'np', 'lol', 'omg', 'chrs', 'wlcm', 'sry'],
          'Greetings, farewells, phatic exchange, courtesy.'),
         ('Practical',
          ['help', 'fix', 'try', 'go', 'do', 'ok', 'yes',
           'no', 'sure', 'plan', 'idea', 'next', 'todo'],
          'Conversational get-it-done — soft directives.'),
         ('Persuasive',
          ['shld', 'must', 'cld', 'wld', 'best', 'btr',
           'urge', 'reco', 'sugg', 'opin', 'feel'],
          'Recommendations, opinions, encouragement.'),
     ]),

    ('david-angel', 'David Angel',
     'Performance-of-discourse personality — leans into the '
     'rhetorical mode the conversation has called for.',
     [
         ('Dialogue',
          ['said', 'asked', 'told', 'ans', 'reply',
           'right', 'okay', 'sure', 'so', 'and', 'but'],
          'Back-and-forth exchange — turn-taking, contained.'),
         ('Discourse',
          ['thus', 'hence', 'since', 'whrs', 'thrby',
           'whole', 'long', 'span', 'arc', 'narr'],
          'Extended structured analysis — connectives, narrative.'),
         ('Debate',
          ['no', 'wrong', 'butt', 'actl', 'how', 'arg',
           'pnt', 'view', 'rebut', 'flaw'],
          'Argumentation — claims, counter-claims, reasoning.'),
         ('Diatribe',
          ['damn', 'nvr', 'alws', 'evry', 'stpd', 'awfl',
           'rant', 'sick', 'fed', 'rage'],
          'Sustained intense critique — rhetorical heat, escalation.'),
     ]),

    ('coaching', 'Coaching',
     'Relational-depth personality — moves between casual surface '
     'and emotional centre.',
     [
         ('Small Talk',
          ['hi', 'hey', 'sup', 'tdy', 'wthr', 'wknd',
           'busy', 'tird', 'oof', 'mood'],
          'Casual surface chat — opening register.'),
         ('Fact Sharing',
          ['fact', 'did', 'know', 'true', 'real', 'data',
           'shws', 'evid', 'src', 'cite'],
          'Information exchange — propositional content.'),
         ('Opinions / Viewpoints',
          ['thnk', 'view', 'opin', 'rckn', 'gues', 'imho',
           'stnd', 'mean', 'see'],
          'Personal stances — soft markers + evaluation.'),
         ('Feelings / Intimacy',
          ['love', 'fear', 'sad', 'hapy', 'hurt',
           'lone', 'clse', 'trst', 'safe', 'cry', 'warm'],
          'Emotional depth — affective register, vulnerability.'),
     ]),

    ('schulz-von-thun', 'Schulz von Thun',
     "Schulz von Thun's classic Communication Square (4 sides of "
     'every message): every utterance simultaneously transmits a fact, '
     'reveals the speaker, defines the relationship, and makes an appeal.',
     [
         ('Fact',
          ['is', 'are', 'has', 'was', 'data', 'fact',
           'true', 'real', 'evid', 'amnt'],
          'Sachebene — propositional / factual content of the message.'),
         ('Self-revealing',
          ['i', 'me', 'my', 'feel', 'thnk', 'see',
           'fear', 'hope', 'belv', 'want', 'hate'],
          'Selbstoffenbarung — what the message says about the sender.'),
         ('Relationship',
          ['you', 'we', 'us', 'frnd', 'love', 'trst',
           'btw', 'tgth', 'undr', 'mate', 'dear'],
          'Beziehungsseite — how sender positions themselves '
          'relative to the receiver.'),
         ('Appeal',
          ['plse', 'do', 'try', 'must', 'shld', 'help',
           'cld', 'wld', 'wnt', 'lets'],
          'Appellseite — the call to action or desired response.'),
     ]),

    ('isaacs-four-fields', 'Isaacs · Four Fields of Dialogue',
     "William Isaacs' four fields (Dialogue and the Art of Thinking "
     "Together, 1999) — conversations occupy one of four basins, "
     'moving deeper as defences drop.',
     [
         ('Politeness',
          ['nice', 'plse', 'thx', 'ok', 'sure', 'agre',
           'yes', 'good', 'fine', 'cool'],
          'Field I — conventional surface, agreement-by-default, '
          "everyone's getting along."),
         ('Breakdown / Debate',
          ['no', 'wrng', 'but', 'actl', 'disg', 'flse',
           'arg', 'why', 'rebut', 'flaw'],
          'Field II — defensive disagreement, position-defending, '
          'debate-as-combat.'),
         ('Inquiry / Dialogue',
          ['wndr', 'cur', 'mby', 'open', 'ques', 'tell',
           'lstn', 'thnk', 'expl', 'hmm'],
          'Field III — suspended judgment, genuine questioning, '
          'listening into difference.'),
         ('Flow',
          ['and', 'yes!', 'oh!', 'we', 'thru', 'see',
           'wow', 'tgth', 'with', 'emr'],
          'Field IV — creative emergence, group thinking together, '
          'distinctions dissolving.'),
     ]),

    ('dansembourg-intentions', "d'Ansembourg · Four Conversational Intentions",
     "Thomas d'Ansembourg's NVC-rooted framework — every utterance "
     'has one of four underlying intentions, often unconscious.',
     [
         ('To Discharge',
          ['vent', 'urgh', 'whew', 'frus', 'tird',
           'sigh', 'rant', 'pent', 'oof', 'gah'],
          'Décharger — release pent-up feeling, no agenda for the other.'),
         ('To Inform',
          ['fyi', 'note', 'so', 'thus', 'data',
           'fact', 'info', 'cite', 'tell', 'btw'],
          'Informer — transmit content, expect comprehension.'),
         ('To Control',
          ['do', 'must', 'shld', 'now', 'plse',
           'urge', 'agnd', 'ordr', 'fix', 'cmd'],
          'Contrôler — direct behaviour, persuade toward action.'),
         ('To Connect',
          ['feel', 'with', 'hear', 'undr', 'tgth',
           'meet', 'real', 'open', 'sft', 'safe'],
          'Relier — deepen contact, mutual presence, empathy.'),
     ]),

    ('grice-maxims', 'Grice · Cooperative Maxims',
     "Paul Grice's Cooperative Principle (1975) — every cooperative "
     'speaker is presumed to obey four maxims; violation is itself '
     'a kind of speech act (implicature).',
     [
         ('Quantity',
          ['bref', 'long', 'enuf', 'more', 'less',
           'qty', 'amnt', 'how', 'cmpr', 'much'],
          'Be as informative as required — no more, no less.'),
         ('Quality',
          ['true', 'real', 'evid', 'fact', 'sure',
           'fals', 'mby', 'pf', 'iirc', 'guess'],
          'Be truthful — say only what you believe + can justify.'),
         ('Relation',
          ['rel', 'rgrd', 'topc', 'pnt', 'sub',
           'abt', 'on', 'wrt', 'tang', 'ot'],
          'Be relevant — stay on the topic at hand.'),
         ('Manner',
          ['clr', 'plain', 'ambg', 'brf', 'ordr',
           'simp', 'styl', 'concs', 'opaq', 'jargn'],
          'Be perspicuous — clear, brief, orderly, unambiguous.'),
     ]),

    ('techbro', 'Techbro',
     'Product/growth voice — every conversation is positioned '
     'against a metric.',
     [
         ('Utility',
          ['use', 'feat', 'tool', 'fn', 'wkfl',
           'prod', 'ship', 'mvp', 'task'],
          'Functional value — what does it do, who uses it.'),
         ('Authentication',
          ['auth', 'oath', 'tokn', 'sso', 'mfa',
           'vrfy', 'cred', 'jwt', 'key'],
          'Identity & access — gating and proving who you are.'),
         ('Marketing',
          ['grwt', 'lnch', 'pmf', 'mrr', 'arr',
           'scal', 'ptch', 'roi', 'kpi', 'cac'],
          'Positioning, narrative, metric talk.'),
         ('Service',
          ['sla', 'api', 'rest', 'gql', 'whk',
           'tier', 'supp', 'docs', 'sdk'],
          'Customer-facing surface — contracts and obligations.'),
     ]),
]


class Command(BaseCommand):
    help = 'Seed PersonalityModule rows.'

    def add_arguments(self, parser):
        parser.add_argument('--wipe', action='store_true')

    def handle(self, *, wipe, **opts):
        from caformer.models import PersonalityModule
        if wipe:
            n = PersonalityModule.objects.all().delete()[0]
            self.stdout.write(f'wiped {n} existing PersonalityModule rows')

        # Which modules DEFINE an axis vs. PRESET a 4-tuple.
        # Axis-modules: their 4 subroutes ARE the 4 values of the axis.
        AXIS_MODULES = {
            'dansembourg-intentions': 'drive',
            'david-angel':            'expression',
            'coaching':               'relation',
            'schulz-von-thun':        'lens',
        }
        # Preset modules: pick a default (drive, expression, relation, lens)
        # 4-tuple that captures the module's central tendency.
        # Velour: empathic + dialogic + small-talk + relationship-lens
        # Techbro: control + discourse + fact-sharing + appeal-lens
        # Isaacs:  connect + inquiry/dialogue (=dialogic) + opinions + relation
        # Grice:   inform + discourse + fact-sharing + fact-lens
        PRESET_STATES = {
            'velour':              [3, 0, 0, 2],     # connect, dialogue, smalltalk, relationship
            'techbro':             [2, 1, 1, 3],     # control, discourse, fact-share, appeal
            'isaacs-four-fields':  [3, 0, 2, 2],     # connect, dialogue, opinions, relationship
            'grice-maxims':        [1, 1, 1, 0],     # inform, discourse, fact-share, fact
        }

        n_new = n_upd = 0
        for slug, name, description, subroutes in MODULES:
            payload = [
                {'label': lab, 'tokens': list(tok), 'notes': notes}
                for lab, tok, notes in subroutes
            ]
            kind = 'axis' if slug in AXIS_MODULES else 'preset'
            axis_slug = AXIS_MODULES.get(slug, '')
            state_vector = PRESET_STATES.get(slug, [])
            row, created = PersonalityModule.objects.update_or_create(
                slug=slug,
                defaults={
                    'name':         name,
                    'description':  description,
                    'subroutes':    payload,
                    'kind':         kind,
                    'axis_slug':    axis_slug,
                    'state_vector': state_vector,
                },
            )
            if created: n_new += 1
            else:       n_upd += 1
            tag = (f'AXIS:{axis_slug}' if kind == 'axis'
                   else f'PRESET:({",".join(str(v) for v in state_vector)})'
                        if state_vector else 'preset')
            self.stdout.write(
                f'  {"+" if created else "·"} {slug:<22} {name:<32} '
                f'{tag}')

        self.stdout.write(self.style.SUCCESS(
            f'Seeded {len(MODULES)} PersonalityModule rows '
            f'({n_new} new, {n_upd} updated).'))
