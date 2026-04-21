"""Konso — syntactic trees for African languages.

The app was born as a Konso-only showcase (Konso is Cushitic,
Lowland East, spoken by ~250k people in SW Ethiopia; canonical SOV
example in the typology literature) and has since expanded to cover
African languages broadly: Afroasiatic (Semitic, Cushitic, Chadic,
Berber, Omotic), Niger-Congo (Mande, Atlantic, Kwa, Volta-Niger,
Bantu), Nilo-Saharan, Khoe-Kwadi/Khoisan, Austronesian (Malagasy),
Indo-European (Afrikaans), and pidgins/creoles.

Each ``Sentence`` is attached to a ``Language`` carrying family,
subgroup, region, ISO 639-3, approximate speaker counts, and basic
word-order typology. The vast majority of seed sentences are flagged
``illustrative`` — author-reconstructed to demonstrate a grammatical
feature using morphology from the published literature — and a
reader with access to the relevant grammar should upgrade the
``source`` field to ``literature`` with a proper page citation.

Key references for the Konso seed: Ongaye Oda Orkaydo, *A Grammar of
Konso* (PhD thesis, LOT / Leiden University, 2013); Sabine
Hellenthal, *A Grammar of Konso* (MA thesis, Leiden, 2004). For
other languages see each seed row's ``citation`` field.

Trees are stored in Chomsky-style labelled-bracket notation:

    [S [NP nama] [VP [NP tika] [V gupe]]]

The parser in ``konso.tree`` walks that string into a lightweight
Node tree and the SVG renderer does a Reingold-Tilford style tidy
layout. Trees render in-page as inline SVG so no extra assets are
needed.
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


FAMILY_CHOICES = [
    ('afroasiatic',      'Afroasiatic'),
    ('niger-congo',      'Atlantic-Congo (Niger-Congo)'),
    ('nilo-saharan',     'Nilo-Saharan'),
    ('khoe-kwadi',       'Khoe-Kwadi / "Khoisan"'),
    ('austronesian',     'Austronesian'),
    ('austroasiatic',    'Austroasiatic'),
    ('tai-kadai',        'Tai-Kadai'),
    ('sino-tibetan',     'Sino-Tibetan'),
    ('japonic',          'Japonic'),
    ('koreanic',         'Koreanic'),
    ('dravidian',        'Dravidian'),
    ('turkic',           'Turkic'),
    ('uralic',           'Uralic'),
    ('mongolic',         'Mongolic'),
    ('indo-european',    'Indo-European'),
    ('trans-new-guinea', 'Nuclear Trans-New-Guinea'),
    ('pama-nyungan',     'Pama-Nyungan'),
    ('otomanguean',      'Otomanguean'),
    ('na-dene',          'Na-Dene'),
    ('algic',            'Algic'),
    ('iroquoian',        'Iroquoian'),
    ('uto-aztecan',      'Uto-Aztecan'),
    ('mayan',            'Mayan'),
    ('eskimo-aleut',     'Eskimo-Aleut'),
    ('quechuan',         'Quechuan'),
    ('aymaran',          'Aymaran'),
    ('arawakan',         'Arawakan'),
    ('tupian',           'Tupian'),
    ('kartvelian',       'Kartvelian'),
    ('sign-language',    'Sign Language'),
    ('pidgin',           'Pidgin'),
    ('creole',           'Creole'),
    ('constructed',      'Constructed'),
    ('isolate',          'Language isolate'),
    ('other',            'Other / unclassified'),
]

# Glottolog top-family names → our slug. Things we don't recognise
# land in "other"; an empty family_name in Glottolog means isolate.
GLOTTOLOG_FAMILY_SLUG = {
    'Afro-Asiatic':              'afroasiatic',
    'Atlantic-Congo':            'niger-congo',
    'Nilotic':                   'nilo-saharan',
    'Central Sudanic':           'nilo-saharan',
    'Eastern Sudanic':           'nilo-saharan',
    'Songhay':                   'nilo-saharan',
    'Saharan':                   'nilo-saharan',
    'Khoe-Kwadi':                'khoe-kwadi',
    'Tuu':                       'khoe-kwadi',
    'Kxa':                       'khoe-kwadi',
    'Austronesian':              'austronesian',
    'Austroasiatic':             'austroasiatic',
    'Tai-Kadai':                 'tai-kadai',
    'Sino-Tibetan':              'sino-tibetan',
    'Japonic':                   'japonic',
    'Koreanic':                  'koreanic',
    'Dravidian':                 'dravidian',
    'Turkic':                    'turkic',
    'Uralic':                    'uralic',
    'Mongolic-Khitan':           'mongolic',
    'Mongolic':                  'mongolic',
    'Indo-European':             'indo-european',
    'Nuclear Trans New Guinea':  'trans-new-guinea',
    'Pama-Nyungan':              'pama-nyungan',
    'Otomanguean':               'otomanguean',
    'Athabaskan-Eyak-Tlingit':   'na-dene',
    'Algic':                     'algic',
    'Iroquoian':                 'iroquoian',
    'Uto-Aztecan':               'uto-aztecan',
    'Mayan':                     'mayan',
    'Eskimo-Aleut':              'eskimo-aleut',
    'Quechuan':                  'quechuan',
    'Aymaran':                   'aymaran',
    'Arawakan':                  'arawakan',
    'Tupian':                    'tupian',
    'Kartvelian':                'kartvelian',
    'Sign Language':             'sign-language',
    'Pidgin':                    'pidgin',
    'Mixed Language':            'creole',
    'Artificial Language':       'constructed',
    '':                          'isolate',
}

WORD_ORDER_CHOICES = [
    ('sov', 'SOV'),
    ('svo', 'SVO'),
    ('vso', 'VSO'),
    ('vos', 'VOS'),
    ('osv', 'OSV'),
    ('ovs', 'OVS'),
    ('free', 'Free / pragmatic'),
    ('mixed', 'Mixed / context-dependent'),
    ('unknown', 'Unknown / disputed'),
]


class Language(models.Model):
    """One African language (plus a few non-African ones spoken in
    Africa: Afrikaans, Nigerian Pidgin, etc.).

    `name` is the autoglottonym — what speakers call the language in
    their own orthography (e.g. ``Kiswahili``, ``isiZulu``,
    ``Af Xonso``). ``english_name`` is the name used in English
    linguistic literature (e.g. Swahili, Zulu, Konso).
    """

    slug = models.SlugField(unique=True, max_length=80)
    glottocode = models.CharField(max_length=10, blank=True, db_index=True,
        help_text='Glottolog 8-char glottocode (e.g. stan1293 for Standard '
                  'English). Blank for rows that predate Glottolog import.')
    name = models.CharField(max_length=120,
        help_text='Autoglottonym — what speakers call the language.')
    english_name = models.CharField(max_length=120,
        help_text='Name used in English linguistic literature.')
    family = models.CharField(max_length=30, choices=FAMILY_CHOICES,
                              default='other')
    family_name = models.CharField(max_length=80, blank=True,
        help_text='Glottolog top-family display name, e.g. "Indo-European", '
                  '"Sino-Tibetan". Kept alongside the slug for readability.')
    subgroup = models.CharField(max_length=80, blank=True,
        help_text='Branch within the family (e.g. Bantu, Cushitic, Kwa).')
    region = models.CharField(max_length=120, blank=True,
        help_text='Primary geographic region (country or area).')
    macroarea = models.CharField(max_length=30, blank=True,
        help_text='Glottolog macroarea: Africa, Eurasia, Papunesia, Australia, '
                  'North America, South America.')
    iso639_3 = models.CharField(max_length=3, blank=True,
        help_text='ISO 639-3 three-letter code if assigned.')
    speakers = models.PositiveIntegerField(default=0,
        help_text='Approximate number of speakers. 0 = unknown.')
    word_order = models.CharField(max_length=8, choices=WORD_ORDER_CHOICES,
                                  default='unknown')
    script = models.CharField(max_length=60, blank=True,
        help_text='Primary writing system (Devanagari, Latin, Chinese, '
                  'Hieroglyphs, Tibetan, Hebrew, etc.).')
    extinct = models.BooleanField(default=False,
        help_text='No living native speakers (Latin, Hittite, Ancient Egyptian, '
                  'etc.). Remains True for liturgical / classical languages.')
    latitude = models.FloatField(null=True, blank=True)
    longitude = models.FloatField(null=True, blank=True)
    notes = models.TextField(blank=True,
        help_text='Typological highlights, notable features, '
                  'orthographic quirks.')

    class Meta:
        ordering = ['family', 'english_name']

    def __str__(self):
        return f'{self.english_name} ({self.name})'

    @property
    def sentence_count(self):
        return self.sentences.count()

    @property
    def group_label(self):
        """Display label for family grouping. Prefers the Glottolog
        family_name if set; falls back to the choices-backed slug display."""
        return self.family_name or self.get_family_display()


class Sentence(models.Model):
    """One Konso sentence with its syntactic tree."""

    slug = models.SlugField(unique=True, max_length=80)
    language = models.ForeignKey(
        Language, on_delete=models.PROTECT, related_name='sentences',
        null=True, blank=True,
        help_text='Which language this sentence is in. Left blank only '
                  'for legacy / pre-expansion rows.')
    konso = models.CharField(
        max_length=240,
        help_text='The sentence in the language\'s own orthography. '
                  'Field name kept as `konso` for historical compat; '
                  'the text can be any language.')
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
