"""Seed Konso example sentences.

Every example here is flagged `illustrative` by default, meaning the
author composed them to demonstrate a specific Konso grammatical
feature (SOV order, postpositions, case clitics, relative clauses,
focus marking) using morphology documented in the literature — but
without citing a verbatim source for the whole sentence. The
intention is that a reader with access to Ongaye Oda Orkaydo's
*A Grammar of Konso* (PhD thesis, Leiden / LOT 2013) or Hellenthal
(2004) should verify each and upgrade the `source` field to
`literature` with the correct page citation.

The canonical "nama tika gupe" sentence widely cited on Wikipedia's
SOV page is kept as the warm-up example — it's the most-travelled
Konso sentence in the typology literature, and Konso is routinely
cited as an SOV language.

Run with:  venv/bin/python manage.py seed_konso
Reset + reseed: venv/bin/python manage.py seed_konso --reset
"""

from django.core.management.base import BaseCommand
from django.utils.text import slugify

from konso.models import Sentence
from konso.tree import parse_bracket


SEEDS = [
    {
        'slug': 'nama-tika-gupe',
        'konso': 'nama tika gupe',
        'gloss': 'man  house  build-PST',
        'translation': 'A man built a house.',
        'tree_bracket': '[S [NP nama] [VP [NP tika] [V gupe]]]',
        'notes': (
            'Canonical SOV sentence — the example Konso is most often '
            'cited with in typological literature on word order. '
            'Subject precedes object precedes verb. The VP groups the '
            'object with the verb; the S node takes subject + VP.'),
        'source': 'literature',
        'citation': (
            'SOV order widely cited for Konso (e.g. Wikipedia SOV page; '
            'Ongaye 2013). Verify exact wording.'),
    },
    {
        'slug': 'nama-tika-xisa-gupe',
        'konso': 'nama tika xisa gupe',
        'gloss': 'man  house  new   build-PST',
        'translation': 'A man built a new house.',
        'tree_bracket': (
            '[S [NP nama] [VP [NP [N tika] [AP xisa]] [V gupe]]]'),
        'notes': (
            'Illustrative. Attributive adjective modifying the object — '
            'shows NP branching inside the VP. Adjective order in Konso '
            'is N-A (head-initial within NP).'),
        'source': 'illustrative',
        'citation': '',
    },
    {
        'slug': 'intane-nama-i-xale',
        'konso': 'intane nama i-xale',
        'gloss': 'child   man   FOC-see.PST',
        'translation': 'The child saw a/the man.',
        'tree_bracket': (
            '[S [NP intane] [VP [NP nama] '
            '[V [Foc i] [V xale]]]]'),
        'notes': (
            'Illustrative. Shows the focus clitic `i-` on the verb in '
            'a declarative main clause — a hallmark feature of Konso '
            '(and other East Cushitic languages). The clitic attaches '
            'at the V, hence the nested V-bar node.'),
        'source': 'illustrative',
        'citation': '',
    },
    {
        'slug': 'nama-tika-e-i-imma',
        'konso': "nama tika-'e i-imma",
        'gloss': "man  house-DAT  FOC-go.PST",
        'translation': 'A man went to the house.',
        'tree_bracket': (
            "[S [NP nama] [VP [PP [NP tika] [P 'e]] "
            "[V [Foc i] [V imma]]]]"),
        'notes': (
            'Illustrative. Dative clitic `-\'e\' attaches to the NP and '
            'projects a PP — this is why Konso is classed '
            '*postpositional*: the case/relation marker follows its '
            'complement rather than preceding it as in English.'),
        'source': 'illustrative',
        'citation': '',
    },
    {
        'slug': 'kitaab-nama-gup-e-nama-xale',
        'konso': 'kitaab nama gup-e-nama xale',
        'gloss': 'book   man   build-PST-REL  see.PST',
        'translation': 'He/she saw the book that the man wrote.',
        'tree_bracket': (
            '[S [NP [N kitaab] [CP nama gup-e-nama]] '
            '[VP [V xale]]]'),
        'notes': (
            'Illustrative. Konso relative clauses follow their head '
            'noun (head-initial), and the relativized verb takes a '
            'relative-clause marker. This is simplified — real Konso '
            'relatives interact with tense and agreement. Treat as '
            'sketch until checked against Ongaye 2013 Ch. 13.'),
        'source': 'illustrative',
        'citation': '',
    },
    {
        'slug': 'nama-malaqa-nne-tika-gupe',
        'konso': 'nama malaqa-nne tika gupe',
        'gloss': 'man  stone-INS     house  build-PST',
        'translation': 'A man built a house with stone.',
        'tree_bracket': (
            '[S [NP nama] '
            '[VP [PP [NP malaqa] [P nne]] [NP tika] [V gupe]]]'),
        'notes': (
            'Illustrative. The instrumental/contrast clitic `-nne` '
            'attaches to the NP and projects a PP adjunct inside the '
            'VP. Instruments in Konso precede the direct object in '
            'many attested examples; confirm ordering against the '
            'literature.'),
        'source': 'illustrative',
        'citation': '',
    },
    {
        'slug': 'nama-imme-paqa-tika-gupe',
        'konso': 'nama imme-paqa tika gupe',
        'gloss': 'man  go.PST-when  house  build-PST',
        'translation': 'When the man went, he built a house.',
        'tree_bracket': (
            '[S [CP nama imme-paqa] '
            '[S [NP pro] [VP [NP tika] [V gupe]]]]'),
        'notes': (
            'Illustrative. Subordinate (temporal) clause precedes the '
            'main clause — another typological signature of Konso. '
            '`pro` marks a null subject recoverable from context; '
            'remove it if you prefer not to posit empty categories.'),
        'source': 'illustrative',
        'citation': '',
    },

    # ─── 10 relative-clause showcases ──────────────────────────────
    # All illustrative. I use `-ayt` throughout as a stand-in for the
    # Konso relativized-verb suffix — a deliberate placeholder, not a
    # claim about the actual morpheme. (The earlier seed used `-nama`
    # as a placeholder, which was visually confusing because `nama`
    # is also Konso for 'man'.) Konso relative clauses are
    # *head-initial* (RC follows the head N) and can relativize
    # subjects, objects, and obliques; the gap inside the RC is
    # marked below as [NP pro] for clarity. Upgrade any of these to
    # source='literature' once checked against Ongaye 2013 ch. 13.
    {
        'slug': 'rel-subj-intrans',
        'konso': 'nama atta-ayt imme',
        'gloss': 'man  come.PST-REL  go.PST',
        'translation': 'The man who came went.',
        'tree_bracket': (
            '[S [NP [N nama] [CP [S [NP pro] [VP [V atta-ayt]]]]] '
            '[VP [V imme]]]'),
        'notes': (
            'Subject relative with an intransitive RC. The gap is '
            'the subject of atta-ayt; nothing surfaces there because '
            '`nama` is coreferential with the RC subject.'),
        'source': 'illustrative',
        'citation': '',
    },
    {
        'slug': 'rel-subj-trans',
        'konso': 'nama tika gup-e-ayt imme',
        'gloss': 'man  house  build-PST-REL  go.PST',
        'translation': 'The man who built a house went.',
        'tree_bracket': (
            '[S [NP [N nama] '
            '[CP [S [NP pro] [VP [NP tika] [V gup-e-ayt]]]]] '
            '[VP [V imme]]]'),
        'notes': (
            'Subject relative with a transitive RC: the relativized '
            'subject is `nama`; `tika` stays in situ as the RC '
            'object. Same surface tokens as rel-obj below, different '
            'tree — a minimal pair.'),
        'source': 'illustrative',
        'citation': '',
    },
    {
        'slug': 'rel-obj',
        'konso': 'tika nama gup-e-ayt i-xale',
        'gloss': 'house  man  build-PST-REL  FOC-see.PST',
        'translation': '(He) saw the house that the man built.',
        'tree_bracket': (
            '[S [NP pro] [VP [NP [N tika] '
            '[CP [S [NP nama] [VP [NP pro] [V gup-e-ayt]]]]] '
            '[V [Foc i] [V xale]]]]'),
        'notes': (
            'Object relative: the gap is inside the RC VP, '
            'coreferential with the head `tika`. Focus clitic `i-` '
            'attaches to the matrix verb.'),
        'source': 'illustrative',
        'citation': '',
    },
    {
        'slug': 'rel-locative',
        'konso': 'tika nama taal-a-ayt xisa',
        'gloss': 'house  man  live-PRS-REL  new',
        'translation': 'The house in which the man lives is new.',
        'tree_bracket': (
            '[S [NP [N tika] '
            '[CP [S [NP nama] [VP [PP [NP pro] [P sa]] '
            '[V taal-a-ayt]]]]] [AP xisa]]'),
        'notes': (
            'Locative / oblique relative. The gap is the complement '
            'of the postposition `sa` (locative) — English "in which" '
            'is split in Konso into a head NP plus a PP with an '
            'empty complement. Present-tense verb uses -a.'),
        'source': 'illustrative',
        'citation': '',
    },
    {
        'slug': 'rel-instrumental',
        'konso': 'malaqa nama tika gup-e-ayt kaskaa',
        'gloss': 'stone  man  house  build-PST-REL  heavy',
        'translation': 'The stone with which the man built the house is heavy.',
        'tree_bracket': (
            '[S [NP [N malaqa] '
            '[CP [S [NP nama] [VP [NP tika] '
            '[PP [NP pro] [P nne]] [V gup-e-ayt]]]]] '
            '[AP kaskaa]]'),
        'notes': (
            'Instrumental relative. `-nne` clitic (instrument) '
            'still projects a PP inside the RC; its NP complement '
            'is the gap coindexed with the head `malaqa`.'),
        'source': 'illustrative',
        'citation': '',
    },
    {
        'slug': 'rel-dative',
        'konso': "intane nama kitaab im-e-ayt kaxxa",
        'gloss': 'child  man  book  give.PST-REL  return.PST',
        'translation': 'The child to whom the man gave the book returned.',
        'tree_bracket': (
            "[S [NP [N intane] "
            "[CP [S [NP nama] [VP [PP [NP pro] [P 'e]] "
            "[NP kitaab] [V im-e-ayt]]]]] [VP [V kaxxa]]]"),
        'notes': (
            "Dative / goal relative. `-'e` clitic projects a PP "
            "whose complement is the gap coindexed with the head "
            "`intane`. A ditransitive inside the RC."),
        'source': 'illustrative',
        'citation': '',
    },
    {
        'slug': 'rel-temporal',
        'konso': 'ayya nama atta-ayt kaskaa',
        'gloss': 'day  man  come-REL  important',
        'translation': 'The day on which the man came was important.',
        'tree_bracket': (
            '[S [NP [N ayya] '
            '[CP [S [NP nama] [VP [PP [NP pro] [P sa]] '
            '[V atta-ayt]]]]] [AP kaskaa]]'),
        'notes': (
            "Temporal relative modelled as a locative-style RC: "
            "the gap sits inside a PP headed by `sa`, coindexed with "
            "`ayya` 'day'. Cross-linguistically typical pattern."),
        'source': 'illustrative',
        'citation': '',
    },
    {
        'slug': 'rel-headless',
        'konso': 'tika gup-e-ayt imme',
        'gloss': 'house  build-PST-REL  go.PST',
        'translation': 'Whoever built the house went.',
        'tree_bracket': (
            '[S [NP [CP [S [NP pro] [VP [NP tika] '
            '[V gup-e-ayt]]]]] [VP [V imme]]]'),
        'notes': (
            'Headless (free) relative: no overt head N, the NP '
            'dominates only the CP. Konso — like many languages — '
            'permits free relatives when the RC alone is '
            'informative.'),
        'source': 'illustrative',
        'citation': '',
    },
    {
        'slug': 'rel-adj-head',
        'konso': 'nama xumma tika gup-e-ayt atta',
        'gloss': 'man  tall  house  build-PST-REL  come.PST',
        'translation': 'The tall man who built the house came.',
        'tree_bracket': (
            '[S [NP [N nama] [AP xumma] '
            '[CP [S [NP pro] [VP [NP tika] [V gup-e-ayt]]]]] '
            '[VP [V atta]]]'),
        'notes': (
            'Head N modified by both an adjective *and* a relative '
            'clause. In Konso NP order, N precedes AP, which '
            'precedes CP (head-initial throughout) — so the RC '
            'sits after the adjective.'),
        'source': 'illustrative',
        'citation': '',
    },
    {
        'slug': 'rel-stacked',
        'konso': 'nama tika halliitti gup-e-ayt xal-e-ayt imme',
        'gloss': 'man  house  woman  build-PST-REL  see.PST-REL  go.PST',
        'translation': ('The man who saw the house that a woman '
                        'built went.'),
        'tree_bracket': (
            '[S [NP [N nama] '
            '[CP [S [NP pro] [VP [NP [N tika] '
            '[CP [S [NP halliitti] [VP [NP pro] [V gup-e-ayt]]]]] '
            '[V xal-e-ayt]]]]] [VP [V imme]]]'),
        'notes': (
            'Two relatives stacked: the outer RC relativizes the '
            'matrix subject `nama`; the inner RC (inside the object '
            'of the outer) relativizes `tika`. A stress-test for '
            'the tidy-tree layout — watch how many columns the '
            'leaves occupy.'),
        'source': 'illustrative',
        'citation': '',
    },
]


class Command(BaseCommand):
    help = 'Seed illustrative Konso sentences with labelled-bracket trees.'

    def add_arguments(self, parser):
        parser.add_argument(
            '--reset', action='store_true',
            help='Delete all existing Sentences before seeding.')

    def handle(self, *args, **opts):
        if opts['reset']:
            n = Sentence.objects.all().delete()[0]
            self.stdout.write(f'Deleted {n} existing sentences.')

        made, skipped, bad = 0, 0, 0
        for row in SEEDS:
            slug = row['slug']
            try:
                parse_bracket(row['tree_bracket'])
            except Exception as e:
                self.stderr.write(self.style.ERROR(
                    f'{slug}: tree fails to parse ({e}); skipping.'))
                bad += 1
                continue
            obj, created = Sentence.objects.update_or_create(
                slug=slug, defaults=row)
            if created:
                made += 1
            else:
                skipped += 1

        self.stdout.write(self.style.SUCCESS(
            f'Seeded {made} new · updated {skipped} existing · '
            f'{bad} bad trees skipped.'))
