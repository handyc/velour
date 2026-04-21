"""Konso — syntactic trees for the Konso language.

Konso (autonym Af Xonso) is a Lowland East Cushitic language of the
Cushitic branch of Afroasiatic, spoken by ~250,000 people in
southwest Ethiopia. Word order is SOV; postpositional; relative
clauses follow the head noun; subordinate clauses precede the main
clause. Orthography is Latin-based with four implosives written
`b d j q` (= /ɓ ɗ ʄ ʛ/), long vowels written as doubled vowels
(VV), digraphs `ny` and `sh`, and a glottal stop `'`. Verbs inflect
for person (2sg/3sg prefix `y-`, 1pl prefix `n-`) and tense (`-e`
past, `-a` present); the focus clitic `i-` appears on the verb in
declarative main clauses. Case clitics (e.g. dative `-'e`,
instrument/contrast `-nne`) attach to NPs.

Key references: Ongaye Oda Orkaydo, *A Grammar of Konso* (PhD
thesis, LOT / Leiden University, 2013); Sabine Hellenthal, *A
Grammar of Konso* (MA thesis, Leiden, 2004). See the `source` field
on Sentence to flag whether each example comes from the literature
or is an illustrative reconstruction the operator should verify.

Trees are stored in Chomsky-style labelled-bracket notation:

    [S [NP nama] [VP [NP tika] [V gupe]]]

The parser in `konso.tree` walks that string into a lightweight Node
tree and the SVG renderer in the same module does a Reingold-Tilford
style tidy layout. Trees render in-page as inline SVG so no extra
assets are needed.
"""

from __future__ import annotations

from django.core.exceptions import ValidationError
from django.db import models

from .tree import parse_bracket, ParseError


SOURCE_CHOICES = [
    ('literature',   'From the literature — verify citation'),
    ('illustrative', 'Illustrative — author-reconstructed, verify'),
    ('operator',     'Operator-contributed'),
]


class Sentence(models.Model):
    """One Konso sentence with its syntactic tree."""

    slug = models.SlugField(unique=True, max_length=80)
    konso = models.CharField(
        max_length=240,
        help_text='The sentence in Konso orthography. Use doubled '
                  'vowels for length (aa, ee…), `ny` and `sh` as '
                  'digraphs, and `\'` for the glottal stop.')
    gloss = models.CharField(
        max_length=400, blank=True,
        help_text='Morpheme-by-morpheme interlinear gloss. One gloss '
                  'per space-separated Konso word; hyphens for '
                  'morpheme boundaries (e.g. `gup-e` = build-PST).')
    translation = models.CharField(
        max_length=240,
        help_text='Free English translation.')
    tree_bracket = models.TextField(
        help_text='Tree in labelled-bracket notation. '
                  'Example: [S [NP nama] [VP [NP tika] [V gupe]]]. '
                  'Node labels are non-terminals; bare tokens at the '
                  'bottom of each bracket are the Konso terminals.')
    notes = models.TextField(
        blank=True,
        help_text='What to watch for — case clitic, relative clause, '
                  'focus marker, SOV reminder, etc.')
    source = models.CharField(
        max_length=20, choices=SOURCE_CHOICES, default='illustrative')
    citation = models.CharField(
        max_length=240, blank=True,
        help_text='Author, year, page — if this sentence is taken '
                  'from the literature.')

    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ['slug']

    def __str__(self):
        return f'{self.slug} — {self.konso}'

    def clean(self):
        super().clean()
        try:
            parse_bracket(self.tree_bracket or '')
        except ParseError as e:
            raise ValidationError({'tree_bracket': str(e)})

    @property
    def tree_node(self):
        """Parsed tree, or None if it fails to parse (shouldn't happen
        for saved objects because clean() rejects bad trees)."""
        try:
            return parse_bracket(self.tree_bracket)
        except ParseError:
            return None
