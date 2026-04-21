"""Seed African-language coverage — Language rows + one tree each.

This seed extends Konso (already covered in ``seed_konso``) with a
representative sentence from each of ~50 African languages across
the major families: Afroasiatic (Semitic, Cushitic, Chadic, Berber,
Omotic), Niger-Congo (Mande, Atlantic, Kwa, Volta-Niger, Bantu),
Nilo-Saharan (Nilotic, Saharan, Songhay), Khoe-Kwadi / "Khoisan"
(Khoekhoe, Ju, Tuu, Sandawe), the isolate Hadza, Austronesian
(Malagasy), Indo-European (Afrikaans), and creoles/pidgins.

**Treat every sentence as provisional.** Virtually all trees are
``illustrative`` — author-composed to showcase a typologically
notable feature (word order, focus marker, noun class agreement,
clicks, verb-initial syntax, relative clauses, serial verbs)
using morphology documented in published grammars. Upgrade any
sentence to ``source='literature'`` once verified against the named
grammar. The citation field points to a grammar or descriptive work
where the serious reader can check.

This is an inventory expansion, not a typological monograph.
Coverage is breadth-first: one canonical tree per language. Depth
(more trees per language) can follow via `seed_<language>` commands
or the web UI.

The Konso language itself is created by this seed; the existing
seeded Konso sentences (from ``seed_konso``) get retroactively
attached to it.

Run:      venv/bin/python manage.py seed_african_languages
Reset:    venv/bin/python manage.py seed_african_languages --reset
"""

from django.core.management.base import BaseCommand
from django.db import transaction

from muka.models import Language, Sentence
from muka.tree import parse_bracket


# Tuple: (language_dict, [sentence_dict, ...])
# The language_dict MUST include slug, name, english_name, family,
# subgroup, region, iso639_3, speakers, word_order, notes.
# Each sentence MUST include slug, konso, gloss, translation,
# tree_bracket, notes, source, citation.
SEEDS = [

    # ═══════════════════════════════════════════════════════════════
    # AFROASIATIC — Cushitic
    # ═══════════════════════════════════════════════════════════════
    (
        {'slug': 'konso', 'name': 'Af Xonso', 'english_name': 'Konso',
         'family': 'afroasiatic', 'subgroup': 'Cushitic (Lowland East)',
         'region': 'SW Ethiopia', 'iso639_3': 'kxc',
         'speakers': 250000, 'word_order': 'sov',
         'notes': 'SOV; postpositional; focus clitic `i-` on the verb; '
                  'implosives /ɓ ɗ ʄ ʛ/ written b d j q; doubled vowels '
                  'mark length; digraphs ny, sh. Ongaye 2013.'},
        # Konso's rich sentence set lives in seed_konso; we don't
        # duplicate it here. The linking pass below attaches those.
        [],
    ),

    (
        {'slug': 'somali', 'name': 'Af-Soomaali', 'english_name': 'Somali',
         'family': 'afroasiatic', 'subgroup': 'Cushitic (Lowland East)',
         'region': 'Somalia, Ethiopia, Djibouti, Kenya',
         'iso639_3': 'som', 'speakers': 22000000, 'word_order': 'sov',
         'notes': 'SOV; rich case clitic + focus system; focus markers '
                  '`baa/ayaa/waxaa` select constituent in focus.'},
        [{
            'slug': 'som-nin-baa-guri-dhisay',
            'konso': 'ninku guri ayuu dhisay',
            'gloss': 'man.DEF  house  FOC.3SG.M  build.PST.3SG.M',
            'translation': 'The man built a house.',
            'tree_bracket': ('[S [NP [N ninku]] '
                             '[VP [NP [N guri]] '
                             '[V [Foc ayuu] [V dhisay]]]]'),
            'notes': 'Focus clitic `ayaa+uu` → ayuu fuses the focus '
                     'marker with the 3SG.M subject pronoun; hallmark '
                     'Somali construction. Saeed, *Somali Reference '
                     'Grammar* (1993/1999).',
            'source': 'illustrative',
            'citation': 'Saeed (1999), *Somali Reference Grammar*.',
        }],
    ),

    (
        {'slug': 'oromo', 'name': 'Afaan Oromoo', 'english_name': 'Oromo',
         'family': 'afroasiatic', 'subgroup': 'Cushitic (Lowland East)',
         'region': 'Ethiopia, N Kenya', 'iso639_3': 'gax',
         'speakers': 37000000, 'word_order': 'sov',
         'notes': 'SOV; postpositional; rich case (nominative -ni, '
                  'absolutive -Ø, etc.); written with Qubee (Latin).'},
        [{
            'slug': 'orm-namni-mana-ijaare',
            'konso': 'namni mana ijaare',
            'gloss': 'man.NOM  house.ABS  build.PST.3SG.M',
            'translation': 'A man built a house.',
            'tree_bracket': ('[S [NP [N namni]] '
                             '[VP [NP [N mana]] [V ijaare]]]'),
            'notes': 'Nominative `-ni` marks the subject; absolutive '
                     'object is morphologically unmarked.',
            'source': 'illustrative',
            'citation': 'Owens (1985), *A Grammar of Harar Oromo*.',
        }],
    ),

    (
        {'slug': 'afar', 'name': 'Qafaraf', 'english_name': 'Afar',
         'family': 'afroasiatic', 'subgroup': 'Cushitic (Lowland East)',
         'region': 'Eritrea, Ethiopia, Djibouti',
         'iso639_3': 'aar', 'speakers': 2000000, 'word_order': 'sov',
         'notes': 'SOV; postpositional; vowel harmony; gender agreement '
                  'on verbs.'},
        [{
            'slug': 'aar-num-buxa-bahe',
            'konso': 'num buxa bahe',
            'gloss': 'man  house  build.PST.3SG.M',
            'translation': 'The man built the house.',
            'tree_bracket': '[S [NP num] [VP [NP buxa] [V bahe]]]',
            'notes': 'Basic SOV. Gender-sensitive verb morphology.',
            'source': 'illustrative',
            'citation': 'Bliese (1981), *A Generative Grammar of Afar*.',
        }],
    ),

    (
        {'slug': 'beja', 'name': 'Bidhaawyeet', 'english_name': 'Beja',
         'family': 'afroasiatic', 'subgroup': 'Cushitic (North)',
         'region': 'Sudan, Eritrea, Egypt',
         'iso639_3': 'bej', 'speakers': 2000000, 'word_order': 'sov',
         'notes': 'SOV; only northern-Cushitic language; case marked '
                  'by tone + suffix.'},
        [{
            'slug': 'bej-oor-baab-diiya',
            'konso': "oor baab diiya",
            'gloss': 'child  door  open.PST.3SG.M',
            'translation': 'The child opened the door.',
            'tree_bracket': '[S [NP oor] [VP [NP baab] [V diiya]]]',
            'notes': 'Beja nominals are marked for case by a '
                     'combination of suffixes and tone.',
            'source': 'illustrative',
            'citation': 'Vanhove (2017), *Le bedja*.',
        }],
    ),

    # ═══════════════════════════════════════════════════════════════
    # AFROASIATIC — Semitic (Ethiosemitic, Arabic)
    # ═══════════════════════════════════════════════════════════════
    (
        {'slug': 'amharic', 'name': 'አማርኛ (Amarəñña)',
         'english_name': 'Amharic',
         'family': 'afroasiatic', 'subgroup': 'Semitic (South Ethiosemitic)',
         'region': 'Ethiopia (official)', 'iso639_3': 'amh',
         'speakers': 57000000, 'word_order': 'sov',
         'notes': 'SOV (areal from Cushitic — unusual for Semitic); '
                  'Ge\'ez (fidel) script; definite suffix -u/-wa.'},
        [{
            'slug': 'amh-liju-bet-serra',
            'konso': 'ልጁ ቤት ሠራ',
            'gloss': 'child.DEF  house  build.PST.3SG.M',
            'translation': 'The boy built a house.',
            'tree_bracket': ('[S [NP [N ልጁ]] '
                             '[VP [NP [N ቤት]] [V ሠራ]]]'),
            'notes': 'Areal SOV order — contrast with other Semitic '
                     'languages (Arabic, Hebrew) which are typically '
                     'VSO/SVO. Definite article is the suffix -ው (-u).',
            'source': 'illustrative',
            'citation': 'Leslau (1995), *Reference Grammar of Amharic*.',
        }],
    ),

    (
        {'slug': 'tigrinya', 'name': 'ትግርኛ (Təgrəñña)',
         'english_name': 'Tigrinya',
         'family': 'afroasiatic', 'subgroup': 'Semitic (North Ethiosemitic)',
         'region': 'Eritrea, N Ethiopia', 'iso639_3': 'tir',
         'speakers': 9000000, 'word_order': 'sov',
         'notes': 'SOV; Ge\'ez script; preserves more archaic Semitic '
                  'morphology than Amharic.'},
        [{
            'slug': 'tir-seb-ay-bet-serihu',
            'konso': 'እቲ ሰብኣይ ቤት ሠርሑ',
            'gloss': 'the  man   house  build.PST.3SG.M',
            'translation': 'The man built a house.',
            'tree_bracket': ('[S [NP [Det እቲ] [N ሰብኣይ]] '
                             '[VP [NP ቤት] [V ሠርሑ]]]'),
            'notes': 'Definite article `እቲ` precedes the head noun.',
            'source': 'illustrative',
            'citation': 'Kogan (1997) in Hetzron (ed.) *The Semitic '
                        'Languages*.',
        }],
    ),

    (
        {'slug': 'geez', 'name': 'ግዕዝ (Gəʿəz)', 'english_name': "Ge'ez",
         'family': 'afroasiatic', 'subgroup': 'Semitic (North Ethiosemitic)',
         'region': 'Eritrea, Ethiopia (liturgical)', 'iso639_3': 'gez',
         'speakers': 0, 'word_order': 'vso',
         'notes': 'Classical / liturgical language of the Ethiopian '
                  'Orthodox church. VSO in unmarked main clauses.'},
        [{
            'slug': 'gez-hanaṣa-bəʾəsi-beta',
            'konso': 'ሐነጸ ብእሲ ቤተ',
            'gloss': 'build.PST.3SG.M  man  house.ACC',
            'translation': 'A man built a house.',
            'tree_bracket': '[S [V ሐነጸ] [NP ብእሲ] [NP ቤተ]]',
            'notes': 'Classical Ge\'ez is verb-initial (VSO), unlike '
                     'its modern Ethiosemitic descendants (SOV, by '
                     'Cushitic contact).',
            'source': 'illustrative',
            'citation': "Lambdin (1978), *Introduction to Classical "
                        "Ethiopic*.",
        }],
    ),

    (
        {'slug': 'arabic-msa', 'name': 'العربية الفصحى (al-ʿarabiyya al-fuṣḥā)',
         'english_name': 'Modern Standard Arabic',
         'family': 'afroasiatic', 'subgroup': 'Semitic (Central)',
         'region': 'Arab world (formal); N Africa + Horn',
         'iso639_3': 'arb', 'speakers': 270000000, 'word_order': 'vso',
         'notes': 'VSO in formal prose; also SVO. Definite article `al-`. '
                  'Non-native to most speakers (used alongside colloquial '
                  'varieties).'},
        [{
            'slug': 'arb-bana-r-rajulu-baytan',
            'konso': 'بَنَى الرَجُلُ بَيْتاً',
            'gloss': 'build.PST.3SG.M  the-man.NOM  house.ACC.INDEF',
            'translation': 'The man built a house.',
            'tree_bracket': ('[S [V بَنَى] '
                             '[NP [Det الـ] [N رَجُلُ]] '
                             '[NP بَيْتاً]]'),
            'notes': 'Unmarked MSA is VSO: verb first. The definite '
                     'article `al-` cliticises to the noun; indefinite '
                     '`-an` is the accusative nunation on the object.',
            'source': 'illustrative',
            'citation': 'Ryding (2005), *A Reference Grammar of Modern '
                        'Standard Arabic*.',
        }],
    ),

    (
        {'slug': 'arabic-egyptian',
         'name': 'اللهجة المصرية (el-lahga el-maṣreyya)',
         'english_name': 'Egyptian Arabic',
         'family': 'afroasiatic', 'subgroup': 'Semitic (Central)',
         'region': 'Egypt', 'iso639_3': 'arz',
         'speakers': 100000000, 'word_order': 'svo',
         'notes': 'SVO; the most widely understood colloquial Arabic due '
                  'to Egyptian media dominance.'},
        [{
            'slug': 'arz-ir-raagil-bana-beet',
            'konso': 'الراجل بنى بيت',
            'gloss': 'the-man  build.PST.3SG.M  house',
            'translation': 'The man built a house.',
            'tree_bracket': ('[S [NP [Det الـ] [N راجل]] '
                             '[VP [V بنى] [NP بيت]]]'),
            'notes': 'SVO word order distinguishes colloquial Arabic '
                     'from MSA. No case marking on nouns.',
            'source': 'illustrative',
            'citation': 'Gary & Gamal-Eldin (1982), *Cairene Egyptian '
                        'Colloquial Arabic*.',
        }],
    ),

    # ═══════════════════════════════════════════════════════════════
    # AFROASIATIC — Chadic
    # ═══════════════════════════════════════════════════════════════
    (
        {'slug': 'hausa', 'name': 'Harshen Hausa',
         'english_name': 'Hausa',
         'family': 'afroasiatic', 'subgroup': 'Chadic (West)',
         'region': 'Nigeria, Niger, lingua franca across W Africa',
         'iso639_3': 'hau', 'speakers': 70000000, 'word_order': 'svo',
         'notes': 'SVO; tonal (high/low/falling); rich TAM system '
                  'expressed via preverbal particles.'},
        [{
            'slug': 'hau-yaron-ya-gina-gida',
            'konso': 'yaron yā gina gida',
            'gloss': 'boy.DEF  3SG.M.PFV  build  house',
            'translation': 'The boy built a house.',
            'tree_bracket': ('[S [NP [N yaron]] '
                             '[VP [Aux yā] [V gina] [NP gida]]]'),
            'notes': 'Preverbal TAM particle `yā` (3SG.M perfective) '
                     'carries the subject agreement, separate from '
                     'the lexical verb.',
            'source': 'illustrative',
            'citation': 'Newman (2000), *The Hausa Language*.',
        }],
    ),

    # ═══════════════════════════════════════════════════════════════
    # AFROASIATIC — Berber
    # ═══════════════════════════════════════════════════════════════
    (
        {'slug': 'tamazight', 'name': 'ⵜⴰⵎⴰⵣⵉⵖⵜ Tamaziɣt',
         'english_name': 'Central Atlas Tamazight',
         'family': 'afroasiatic', 'subgroup': 'Berber',
         'region': 'Morocco (Middle Atlas)', 'iso639_3': 'tzm',
         'speakers': 4600000, 'word_order': 'vso',
         'notes': 'VSO; Tifinagh or Latin script; rich verbal aspect; '
                  '"state" distinction (free vs. annexed) on nouns.'},
        [{
            'slug': 'tzm-ibna-urgaz-tigemmi',
            'konso': 'ibna urgaz tigemmi',
            'gloss': 'build.PST.3SG.M  man.ANX  house',
            'translation': 'The man built a house.',
            'tree_bracket': ('[S [V ibna] '
                             '[NP [N urgaz]] '
                             '[NP [N tigemmi]]]'),
            'notes': 'VSO; the subject `urgaz` appears in the annexed '
                     '(construct) state — a hallmark Berber feature — '
                     'when it follows the verb.',
            'source': 'illustrative',
            'citation': 'Sadiqi (1997), *Grammaire du berbère*.',
        }],
    ),

    (
        {'slug': 'tashelhit', 'name': 'ⵜⴰⵛⵍⵃⵉⵜ Taclḥiyt',
         'english_name': 'Tashelhit',
         'family': 'afroasiatic', 'subgroup': 'Berber',
         'region': 'Morocco (High Atlas, Souss)', 'iso639_3': 'shi',
         'speakers': 4400000, 'word_order': 'vso',
         'notes': 'VSO; rich consonant inventory; clitic climbing.'},
        [{
            'slug': 'shi-issker-urgaz-tigmmi',
            'konso': 'issker urgaz tigmmi',
            'gloss': 'make.PST.3SG.M  man.ANX  house',
            'translation': 'The man built a house.',
            'tree_bracket': ('[S [V issker] '
                             '[NP [N urgaz]] '
                             '[NP [N tigmmi]]]'),
            'notes': 'Close sibling to Central Atlas Tamazight; same '
                     'VSO + annexed-state pattern.',
            'source': 'illustrative',
            'citation': 'Galand (1988) in Bynon (ed.).',
        }],
    ),

    (
        {'slug': 'kabyle', 'name': 'Taqbaylit',
         'english_name': 'Kabyle',
         'family': 'afroasiatic', 'subgroup': 'Berber',
         'region': 'NE Algeria (Kabylie)', 'iso639_3': 'kab',
         'speakers': 6000000, 'word_order': 'vso',
         'notes': 'VSO (also SVO with topic-subject); Latin orthography '
                  'is standard alongside Tifinagh.'},
        [{
            'slug': 'kab-yebna-urgaz-axxam',
            'konso': 'yebna urgaz axxam',
            'gloss': 'build.PST.3SG.M  man.ANX  house',
            'translation': 'The man built a house.',
            'tree_bracket': ('[S [V yebna] '
                             '[NP [N urgaz]] '
                             '[NP [N axxam]]]'),
            'notes': 'VSO. Annexed-state subject marking survives in '
                     'Kabyle just as in Moroccan Berber.',
            'source': 'illustrative',
            'citation': 'Naït-Zerrad (2001), *Grammaire moderne du '
                        'kabyle*.',
        }],
    ),

    (
        {'slug': 'tamasheq', 'name': 'Tămašăq (Tuareg)',
         'english_name': 'Tamasheq',
         'family': 'afroasiatic', 'subgroup': 'Berber (Tuareg)',
         'region': 'Mali, Niger, Algeria, Libya, Burkina Faso',
         'iso639_3': 'taq', 'speakers': 1200000, 'word_order': 'vso',
         'notes': 'Southern Berber group (Tuareg); written in '
                  'Tifinagh natively.'},
        [{
            'slug': 'taq-ikna-argaz-ehan',
            'konso': 'ikna argaz ehan',
            'gloss': 'make.PST.3SG.M  man  house',
            'translation': 'The man built a house.',
            'tree_bracket': ('[S [V ikna] [NP [N argaz]] '
                             '[NP [N ehan]]]'),
            'notes': 'VSO. Southern Berber retains the same verb-first '
                     'main-clause word order as its Moroccan siblings.',
            'source': 'illustrative',
            'citation': 'Heath (2005), *A Grammar of Tamashek*.',
        }],
    ),

    # ═══════════════════════════════════════════════════════════════
    # AFROASIATIC — Omotic
    # ═══════════════════════════════════════════════════════════════
    (
        {'slug': 'wolaytta', 'name': 'Wolayttattó',
         'english_name': 'Wolaytta',
         'family': 'afroasiatic', 'subgroup': 'Omotic (North)',
         'region': 'SW Ethiopia', 'iso639_3': 'wal',
         'speakers': 1600000, 'word_order': 'sov',
         'notes': 'SOV; rich nominal case system; subject-verb '
                  'agreement by person+gender.'},
        [{
            'slug': 'wal-bitaneei-keettaa-keexxiis',
            'konso': 'bitaneei keettaa keexxiis',
            'gloss': 'man.NOM  house.ABS  build.PST.3SG.M',
            'translation': 'The man built the house.',
            'tree_bracket': ('[S [NP [N bitaneei]] '
                             '[VP [NP [N keettaa]] [V keexxiis]]]'),
            'notes': 'Nominative `-i`, absolutive/object `-a`.',
            'source': 'illustrative',
            'citation': 'Lamberti & Sottile (1997), *The Wolaytta '
                        'Language*.',
        }],
    ),

    # ═══════════════════════════════════════════════════════════════
    # NIGER-CONGO — Bantu
    # ═══════════════════════════════════════════════════════════════
    (
        {'slug': 'swahili', 'name': 'Kiswahili',
         'english_name': 'Swahili',
         'family': 'niger-congo', 'subgroup': 'Bantu (G)',
         'region': 'Tanzania, Kenya, Uganda, DR Congo (lingua franca)',
         'iso639_3': 'swh', 'speakers': 200000000, 'word_order': 'svo',
         'notes': 'SVO; rich noun class system (15+ classes); agglutinating '
                  'verb with subject, tense, object, stem, mood markers.'},
        [{
            'slug': 'swh-mtoto-alijenga-nyumba',
            'konso': 'mtoto alijenga nyumba',
            'gloss': 'child  1SG.SM-PST-build  house',
            'translation': 'The child built a house.',
            'tree_bracket': ('[S [NP [N mtoto]] '
                             '[VP [V [SM a] [T li] [V jenga]] '
                             '[NP [N nyumba]]]]'),
            'notes': 'Subject-verb agreement: `a-` (class 1, "he/she"). '
                     'TAM slot `-li-` marks past. This breakdown shows the '
                     'agglutinating verb template SM-T-V.',
            'source': 'illustrative',
            'citation': 'Ashton (1947), *Swahili Grammar*.',
        }],
    ),

    (
        {'slug': 'zulu', 'name': 'isiZulu',
         'english_name': 'Zulu',
         'family': 'niger-congo', 'subgroup': 'Bantu (S)',
         'region': 'South Africa', 'iso639_3': 'zul',
         'speakers': 28000000, 'word_order': 'svo',
         'notes': 'SVO; Nguni subgroup; three click phonemes (c, q, x) '
                  'borrowed from Khoe. Noun class prefixes trigger '
                  'concordial agreement throughout the NP and VP.'},
        [{
            'slug': 'zul-umfana-wakha-indlu',
            'konso': 'umfana wakha indlu',
            'gloss': 'boy  SM.PST-build  house',
            'translation': 'The boy built a house.',
            'tree_bracket': ('[S [NP [N umfana]] '
                             '[VP [V [SM wa] [V khá]] '
                             '[NP [N indlu]]]]'),
            'notes': 'Subject concord `wa-` agrees with class 1 '
                     '(`umfana`) in the remote-past tense.',
            'source': 'illustrative',
            'citation': 'Doke (1927), *Textbook of Zulu Grammar*.',
        }],
    ),

    (
        {'slug': 'xhosa', 'name': 'isiXhosa',
         'english_name': 'Xhosa',
         'family': 'niger-congo', 'subgroup': 'Bantu (S)',
         'region': 'South Africa', 'iso639_3': 'xho',
         'speakers': 19000000, 'word_order': 'svo',
         'notes': 'SVO; Nguni; 15 click phonemes (c, q, x each with '
                  '5 secondary articulations).'},
        [{
            'slug': 'xho-inkwenkwe-yakha-indlu',
            'konso': 'inkwenkwe yakha indlu',
            'gloss': 'boy  SM.PST-build  house',
            'translation': 'The boy built a house.',
            'tree_bracket': ('[S [NP [N inkwenkwe]] '
                             '[VP [V [SM ya] [V kha]] '
                             '[NP [N indlu]]]]'),
            'notes': 'Near-identical morphology to Zulu; Xhosa and '
                     'Zulu are highly mutually intelligible.',
            'source': 'illustrative',
            'citation': 'McLaren (1955), *A New Concise Xhosa '
                        'Grammar*.',
        }],
    ),

    (
        {'slug': 'shona', 'name': 'chiShona',
         'english_name': 'Shona',
         'family': 'niger-congo', 'subgroup': 'Bantu (S)',
         'region': 'Zimbabwe, Mozambique', 'iso639_3': 'sna',
         'speakers': 14200000, 'word_order': 'svo',
         'notes': 'SVO; two-tone system; concordial noun classes.'},
        [{
            'slug': 'sna-mukomana-akavaka-imba',
            'konso': 'mukomana akavaka imba',
            'gloss': 'boy  SM.PST-build  house',
            'translation': 'The boy built a house.',
            'tree_bracket': ('[S [NP [N mukomana]] '
                             '[VP [V [SM a] [T ka] [V vaka]] '
                             '[NP [N imba]]]]'),
            'notes': 'SM-T-V: `a-ka-vaka`. Past tense marker `-ka-`.',
            'source': 'illustrative',
            'citation': 'Fortune (1955), *An Analytical Grammar of Shona*.',
        }],
    ),

    (
        {'slug': 'chichewa', 'name': 'chiCheŵa / chiNyanja',
         'english_name': 'Chichewa',
         'family': 'niger-congo', 'subgroup': 'Bantu (N)',
         'region': 'Malawi, Zambia, Mozambique, Zimbabwe',
         'iso639_3': 'nya', 'speakers': 14000000, 'word_order': 'svo',
         'notes': 'SVO; national language of Malawi; extensively '
                  'studied in formal syntax (Bresnan).'},
        [{
            'slug': 'nya-mwana-anaamanga-nyumba',
            'konso': 'mwana anaamanga nyumba',
            'gloss': 'child  SM-PST-build  house',
            'translation': 'The child built a house.',
            'tree_bracket': ('[S [NP [N mwana]] '
                             '[VP [V [SM a] [T naa] [V manga]] '
                             '[NP [N nyumba]]]]'),
            'notes': 'Much-analysed in Bresnan\'s LFG work on Bantu '
                     'agreement + topic. `naa-` is recent past.',
            'source': 'illustrative',
            'citation': 'Mchombo (2004), *The Syntax of Chichewa*.',
        }],
    ),

    (
        {'slug': 'kinyarwanda', 'name': 'Ikinyarwanda',
         'english_name': 'Kinyarwanda',
         'family': 'niger-congo', 'subgroup': 'Bantu (J)',
         'region': 'Rwanda, E DR Congo', 'iso639_3': 'kin',
         'speakers': 12000000, 'word_order': 'svo',
         'notes': 'SVO; "one of the most highly inflected" Bantu '
                  'languages (Kimenyi); productive applicative.'},
        [{
            'slug': 'kin-umuhungu-yubatse-inzu',
            'konso': 'umuhungu yubatse inzu',
            'gloss': 'boy  SM-PST-build  house',
            'translation': 'The boy built a house.',
            'tree_bracket': ('[S [NP [N umuhungu]] '
                             '[VP [V [SM y] [V ubatse]] '
                             '[NP [N inzu]]]]'),
            'notes': 'Kinyarwanda allows extreme valency manipulation '
                     'via applicative and causative suffixes stacked '
                     'on the verb.',
            'source': 'illustrative',
            'citation': 'Kimenyi (1980), *A Relational Grammar of '
                        'Kinyarwanda*.',
        }],
    ),

    (
        {'slug': 'kikuyu', 'name': 'Gĩkũyũ',
         'english_name': 'Kikuyu',
         'family': 'niger-congo', 'subgroup': 'Bantu (E)',
         'region': 'Central Kenya', 'iso639_3': 'kik',
         'speakers': 8100000, 'word_order': 'svo',
         'notes': 'SVO; tonal; ATR vowel harmony.'},
        [{
            'slug': 'kik-kahii-kaakire-nyumba',
            'konso': 'kahii kaakire nyumba',
            'gloss': 'boy  SM-PST-build  house',
            'translation': 'The boy built a house.',
            'tree_bracket': ('[S [NP [N kahii]] '
                             '[VP [V kaakire] [NP [N nyumba]]]]'),
            'notes': 'The subject concord fuses tightly with the '
                     'verb stem; ATR harmony spreads across the verb '
                     'complex.',
            'source': 'illustrative',
            'citation': 'Barlow (1946), *Studies in Kikuyu Grammar*.',
        }],
    ),

    (
        {'slug': 'lingala', 'name': 'Lingála',
         'english_name': 'Lingala',
         'family': 'niger-congo', 'subgroup': 'Bantu (C)',
         'region': 'DR Congo, Republic of the Congo',
         'iso639_3': 'lin', 'speakers': 40000000, 'word_order': 'svo',
         'notes': 'SVO; simplified Bantu (reduced noun classes, '
                  'regularised morphology); urban lingua franca.'},
        [{
            'slug': 'lin-mwana-atongi-ndako',
            'konso': 'mwana atongi ndako',
            'gloss': 'child  SM-PST-build  house',
            'translation': 'The child built a house.',
            'tree_bracket': ('[S [NP [N mwana]] '
                             '[VP [V [SM a] [V tongi]] '
                             '[NP [N ndako]]]]'),
            'notes': '`atongi` = a- (SM) + tong- (build) + -i (past).',
            'source': 'illustrative',
            'citation': 'Meeuwis (2013), *A Grammatical Overview of '
                        'Lingála*.',
        }],
    ),

    (
        {'slug': 'luganda', 'name': 'Oluganda',
         'english_name': 'Luganda',
         'family': 'niger-congo', 'subgroup': 'Bantu (J)',
         'region': 'Central Uganda', 'iso639_3': 'lug',
         'speakers': 8800000, 'word_order': 'svo',
         'notes': 'SVO; famous for its intricate concord system '
                  'with 10+ noun classes, each triggering distinct '
                  'agreement morphemes.'},
        [{
            'slug': 'lug-omulenzi-yazimba-ennyumba',
            'konso': 'omulenzi yazimba ennyumba',
            'gloss': 'boy  SM-PST-build  house',
            'translation': 'The boy built a house.',
            'tree_bracket': ('[S [NP [N omulenzi]] '
                             '[VP [V [SM ya] [V zimba]] '
                             '[NP [N ennyumba]]]]'),
            'notes': 'Class 1 `omu-` subject triggers SM `ya-` in '
                     'recent past.',
            'source': 'illustrative',
            'citation': 'Ashton et al. (1954), *A Luganda Grammar*.',
        }],
    ),

    (
        {'slug': 'sotho', 'name': 'Sesotho',
         'english_name': 'Sotho',
         'family': 'niger-congo', 'subgroup': 'Bantu (S)',
         'region': 'Lesotho, South Africa', 'iso639_3': 'sot',
         'speakers': 14000000, 'word_order': 'svo',
         'notes': 'SVO; noun class concord like other S-Bantu; '
                  'object-marker doubling is productive.'},
        [{
            'slug': 'sot-moshanyana-o-hahile-ntlo',
            'konso': 'moshanyana o hahile ntlo',
            'gloss': 'boy  SM  build.PST  house',
            'translation': 'The boy built a house.',
            'tree_bracket': ('[S [NP [N moshanyana]] '
                             '[VP [SM o] [V hahile] [NP [N ntlo]]]]'),
            'notes': 'Subject concord `o` separated orthographically '
                     'from the verb (convention for Sesotho writing).',
            'source': 'illustrative',
            'citation': 'Doke & Mofokeng (1957), *Textbook of '
                        'Southern Sotho Grammar*.',
        }],
    ),

    (
        {'slug': 'tswana', 'name': 'Setswana',
         'english_name': 'Tswana',
         'family': 'niger-congo', 'subgroup': 'Bantu (S)',
         'region': 'Botswana, South Africa', 'iso639_3': 'tsn',
         'speakers': 13700000, 'word_order': 'svo',
         'notes': 'SVO; sister to Sotho; disjoint/conjoint verb forms.'},
        [{
            'slug': 'tsn-mosimane-o-agile-ntlo',
            'konso': 'mosimane o agile ntlo',
            'gloss': 'boy  SM  build.PST  house',
            'translation': 'The boy built a house.',
            'tree_bracket': ('[S [NP [N mosimane]] '
                             '[VP [SM o] [V agile] [NP [N ntlo]]]]'),
            'notes': 'Disjoint verb form `agile` used before an '
                     'overt object (conjoint vs. disjoint alternation '
                     'is a Sotho-Tswana signature).',
            'source': 'illustrative',
            'citation': 'Cole (1955), *An Introduction to Tswana '
                        'Grammar*.',
        }],
    ),

    (
        {'slug': 'kongo', 'name': 'Kikongo',
         'english_name': 'Kongo',
         'family': 'niger-congo', 'subgroup': 'Bantu (H)',
         'region': 'DR Congo, Republic of the Congo, Angola',
         'iso639_3': 'kng', 'speakers': 6500000, 'word_order': 'svo',
         'notes': 'SVO; creolised form Kituba is a major lingua '
                  'franca of central Africa.'},
        [{
            'slug': 'kng-mwana-kutungidi-nzo',
            'konso': 'mwana kutungidi nzo',
            'gloss': 'child  build.PST  house',
            'translation': 'The child built a house.',
            'tree_bracket': ('[S [NP [N mwana]] '
                             '[VP [V kutungidi] [NP [N nzo]]]]'),
            'notes': '`ku-` is an infinitive/past prefix in some Kongo '
                     'varieties.',
            'source': 'illustrative',
            'citation': 'Laman (1912), *Grammar of the Kongo Language*.',
        }],
    ),

    (
        {'slug': 'umbundu', 'name': 'Úmbúndú',
         'english_name': 'Umbundu',
         'family': 'niger-congo', 'subgroup': 'Bantu (R)',
         'region': 'Central Angola', 'iso639_3': 'umb',
         'speakers': 7000000, 'word_order': 'svo',
         'notes': 'SVO; 4 tone levels (high, low, rising, falling).'},
        [{
            'slug': 'umb-omalehe-watunga-onjo',
            'konso': 'omalehe watunga onjo',
            'gloss': 'boy  SM.PST-build  house',
            'translation': 'The boy built a house.',
            'tree_bracket': ('[S [NP [N omalehe]] '
                             '[VP [V watunga] [NP [N onjo]]]]'),
            'notes': 'Tones are not marked in our orthographic '
                     'rendering — serious analysis requires them.',
            'source': 'illustrative',
            'citation': 'Schadeberg (1982), *A Sketch of Umbundu*.',
        }],
    ),

    # ═══════════════════════════════════════════════════════════════
    # NIGER-CONGO — Volta-Niger (Yoruba, Igbo)
    # ═══════════════════════════════════════════════════════════════
    (
        {'slug': 'yoruba', 'name': 'Èdè Yorùbá',
         'english_name': 'Yoruba',
         'family': 'niger-congo', 'subgroup': 'Volta-Niger (Yoruboid)',
         'region': 'SW Nigeria, Benin, Togo', 'iso639_3': 'yor',
         'speakers': 47000000, 'word_order': 'svo',
         'notes': 'SVO; tonal (3 level tones — high á, mid a, low à); '
                  'serial verb constructions productive; no overt '
                  'tense morphology (TAM via particles).'},
        [{
            'slug': 'yor-okunrin-kọ-ile',
            'konso': 'ọkùnrin náà kọ́ ilé',
            'gloss': 'man  DEF  build  house',
            'translation': 'The man built a house.',
            'tree_bracket': ('[S [NP [N ọkùnrin] [Det náà]] '
                             '[VP [V kọ́] [NP [N ilé]]]]'),
            'notes': 'Definite `náà` follows the head noun. Tone is '
                     'lexically + grammatically distinctive — `kọ̀` '
                     '(refuse), `kọ̀` (write), `kọ́` (build) differ '
                     'only in tone.',
            'source': 'illustrative',
            'citation': 'Bamgboṣe (1966), *A Grammar of Yoruba*.',
        }],
    ),

    (
        {'slug': 'igbo', 'name': 'Asụsụ Igbo',
         'english_name': 'Igbo',
         'family': 'niger-congo', 'subgroup': 'Volta-Niger (Igboid)',
         'region': 'SE Nigeria', 'iso639_3': 'ibo',
         'speakers': 44000000, 'word_order': 'svo',
         'notes': 'SVO; two-tone + downstep; productive serial-verb '
                  'constructions; vowel harmony (ATR).'},
        [{
            'slug': 'ibo-nwoke-wuru-ụlọ',
            'konso': 'nwoke wuru ụlọ',
            'gloss': 'man  build.PST  house',
            'translation': 'A man built a house.',
            'tree_bracket': ('[S [NP [N nwoke]] '
                             '[VP [V wuru] [NP [N ụlọ]]]]'),
            'notes': '`-ru` suffix marks past. ATR harmony: nwokè '
                     '(+ATR class) vs. ụlọ (-ATR class) — the dotted '
                     'vowels ị ọ ụ are -ATR counterparts of i o u.',
            'source': 'illustrative',
            'citation': 'Emenanjo (1978), *Elements of Modern Igbo '
                        'Grammar*.',
        }],
    ),

    # ═══════════════════════════════════════════════════════════════
    # NIGER-CONGO — Kwa (Akan, Ewe, Fon, Ga)
    # ═══════════════════════════════════════════════════════════════
    (
        {'slug': 'akan-twi', 'name': 'Twi',
         'english_name': 'Akan (Twi)',
         'family': 'niger-congo', 'subgroup': 'Kwa',
         'region': 'Ghana', 'iso639_3': 'aka',
         'speakers': 11000000, 'word_order': 'svo',
         'notes': 'SVO; tonal; ATR harmony; serial verbs; no number '
                  'agreement.'},
        [{
            'slug': 'aka-obarima-sii-dan',
            'konso': 'obarima no sii dan',
            'gloss': 'man  DEF  build.PST  house',
            'translation': 'The man built a house.',
            'tree_bracket': ('[S [NP [N obarima] [Det no]] '
                             '[VP [V sii] [NP [N dan]]]]'),
            'notes': 'Definite article `no` is postposed. `sii` is '
                     'past of `si` (build); the doubled vowel '
                     'indicates past tense in some Akan varieties.',
            'source': 'illustrative',
            'citation': 'Dolphyne (1988), *The Akan (Twi-Fante) '
                        'Language*.',
        }],
    ),

    (
        {'slug': 'ewe', 'name': 'Eʋegbe',
         'english_name': 'Ewe',
         'family': 'niger-congo', 'subgroup': 'Kwa (Gbe)',
         'region': 'Ghana, Togo', 'iso639_3': 'ewe',
         'speakers': 7000000, 'word_order': 'svo',
         'notes': 'SVO; tonal; serial verbs; productive ideophones; '
                  'nasality and labial-velars /kp gb/.'},
        [{
            'slug': 'ewe-ŋutsu-la-tu-aƒe',
            'konso': 'ŋutsu la tu aƒe',
            'gloss': 'man  DEF  build  house',
            'translation': 'The man built a house.',
            'tree_bracket': ('[S [NP [N ŋutsu] [Det la]] '
                             '[VP [V tu] [NP [N aƒe]]]]'),
            'notes': 'Definite `la` is postposed. No overt past tense '
                     'morphology — inferred from context.',
            'source': 'illustrative',
            'citation': 'Westermann (1930), *A Study of the Ewe '
                        'Language*; Ameka (1991).',
        }],
    ),

    (
        {'slug': 'fon', 'name': 'Fɔngbè',
         'english_name': 'Fon',
         'family': 'niger-congo', 'subgroup': 'Kwa (Gbe)',
         'region': 'Benin', 'iso639_3': 'fon',
         'speakers': 2200000, 'word_order': 'svo',
         'notes': 'SVO; tonal; serial verbs (among the richest in '
                  'Kwa); 7-vowel inventory + nasal counterparts.'},
        [{
            'slug': 'fon-sunnu-gba-xwe',
            'konso': 'sunnu ɔ gba xwe',
            'gloss': 'man  DEF  build  house',
            'translation': 'The man built a house.',
            'tree_bracket': ('[S [NP [N sunnu] [Det ɔ]] '
                             '[VP [V gba] [NP [N xwe]]]]'),
            'notes': 'Fon SVO. Serial-verb constructions are '
                     'widespread — a single event chain like '
                     '"take-bring-give" can use three juxtaposed verbs.',
            'source': 'illustrative',
            'citation': 'Lefebvre & Brousseau (2002), *A Grammar of '
                        'Fongbe*.',
        }],
    ),

    # ═══════════════════════════════════════════════════════════════
    # NIGER-CONGO — Atlantic (Wolof, Fulfulde)
    # ═══════════════════════════════════════════════════════════════
    (
        {'slug': 'wolof', 'name': 'Wolof',
         'english_name': 'Wolof',
         'family': 'niger-congo', 'subgroup': 'Atlantic (Senegambian)',
         'region': 'Senegal, Gambia, Mauritania', 'iso639_3': 'wol',
         'speakers': 12000000, 'word_order': 'svo',
         'notes': 'SVO; agglutinating; "focus" inflection is central '
                  '— sentence form depends on what is in focus '
                  '(subject, verb, complement).'},
        [{
            'slug': 'wol-goor-bi-tabax-na-kër',
            'konso': 'góor gi tabax na kër',
            'gloss': 'man  DEF  build  PERF  house',
            'translation': 'The man built a house.',
            'tree_bracket': ('[S [NP [N góor] [Det gi]] '
                             '[VP [V tabax] [Aux na] [NP [N kër]]]]'),
            'notes': 'Perfect auxiliary `na` is the neutral / '
                     'subject-focus form. Definite clitic `gi` (animate '
                     'human class) follows the head.',
            'source': 'illustrative',
            'citation': 'Diouf (2009), *Grammaire du wolof '
                        'contemporain*.',
        }],
    ),

    (
        {'slug': 'fulfulde', 'name': 'Fulfulde / Pulaar',
         'english_name': 'Fula (Fulfulde)',
         'family': 'niger-congo', 'subgroup': 'Atlantic (Senegambian)',
         'region': 'W Africa, Sahel (Senegal → Sudan)',
         'iso639_3': 'ful', 'speakers': 40000000, 'word_order': 'svo',
         'notes': 'SVO; over 20 noun classes with consonant mutation '
                  'of the stem-initial consonant keyed to class.'},
        [{
            'slug': 'ful-gorko-on-mahi-suudu',
            'konso': "gorko on mahi suudu",
            'gloss': 'man  DEF  build.PST  house',
            'translation': 'The man built a house.',
            'tree_bracket': ("[S [NP [N gorko] [Det on]] "
                             "[VP [V mahi] [NP [N suudu]]]]"),
            'notes': 'Noun class concord: `gorko` (class 1 human) '
                     'takes the class-1 article `on`.',
            'source': 'illustrative',
            'citation': 'Arnott (1970), *The Nominal and Verbal '
                        'Systems of Fula*.',
        }],
    ),

    # ═══════════════════════════════════════════════════════════════
    # NIGER-CONGO — Mande (Bambara, Mandinka)
    # ═══════════════════════════════════════════════════════════════
    (
        {'slug': 'bambara', 'name': 'Bamanankan',
         'english_name': 'Bambara',
         'family': 'niger-congo', 'subgroup': 'Mande',
         'region': 'Mali', 'iso639_3': 'bam',
         'speakers': 14000000, 'word_order': 'sov',
         'notes': 'S-Aux-O-V — unusual for West Africa; tonal; '
                  'N\'Ko script popular alongside Latin.'},
        [{
            'slug': 'bam-cɛ-ye-so-jɔ',
            'konso': 'cɛ ye so jɔ',
            'gloss': 'man  PFV  house  build',
            'translation': 'The man built a house.',
            'tree_bracket': ('[S [NP cɛ] '
                             '[VP [Aux ye] [NP so] [V jɔ]]]'),
            'notes': 'Aspectual auxiliary `ye` (perfective) sits '
                     'between subject and object — the object then '
                     'precedes the verb (S-Aux-O-V). Typical of Mande.',
            'source': 'illustrative',
            'citation': 'Dumestre (2003), *Grammaire fondamentale '
                        'du bambara*.',
        }],
    ),

    (
        {'slug': 'mandinka', 'name': 'Mandingo',
         'english_name': 'Mandinka',
         'family': 'niger-congo', 'subgroup': 'Mande',
         'region': 'Senegal, Gambia, Guinea-Bissau',
         'iso639_3': 'mnk', 'speakers': 1800000, 'word_order': 'sov',
         'notes': 'Close relative of Bambara; same S-Aux-O-V order '
                  'with perfective / imperfective auxiliary.'},
        [{
            'slug': 'mnk-kewo-ye-buŋo-loo',
            'konso': 'kewo ye buŋo loo',
            'gloss': 'man.DEF  PFV  house.DEF  build',
            'translation': 'The man built the house.',
            'tree_bracket': ('[S [NP [N kewo]] '
                             '[VP [Aux ye] [NP [N buŋo]] [V loo]]]'),
            'notes': 'Definite `-o` suffix on both subject and object.',
            'source': 'illustrative',
            'citation': 'Creissels (1983), *Éléments de grammaire '
                        'de la langue mandinka*.',
        }],
    ),

    # ═══════════════════════════════════════════════════════════════
    # NILO-SAHARAN — Nilotic
    # ═══════════════════════════════════════════════════════════════
    (
        {'slug': 'dinka', 'name': 'Thuɔŋjäŋ',
         'english_name': 'Dinka',
         'family': 'nilo-saharan', 'subgroup': 'Nilotic (West)',
         'region': 'South Sudan', 'iso639_3': 'din',
         'speakers': 4500000, 'word_order': 'svo',
         'notes': 'SVO; vowel length and voice quality (breathy vs. '
                  'creaky) are phonemic; rich verbal morphology via '
                  'ablaut ("root and pattern" in a Nilotic language).'},
        [{
            'slug': 'din-mony-acï-dhɛ̈ɛ̈ny-looi',
            'konso': 'mony acï dhɛ̈ɛ̈ny looi',
            'gloss': 'man  PFV  house  build',
            'translation': 'A man has built a house.',
            'tree_bracket': ('[S [NP mony] '
                             '[VP [Aux acï] [NP dhɛ̈ɛ̈ny] [V looi]]]'),
            'notes': 'Perfect auxiliary `acï`. Vowel diacritics mark '
                     'length and breathy voice.',
            'source': 'illustrative',
            'citation': 'Andersen (1987), *The Phonemic System of '
                        'Agar Dinka*.',
        }],
    ),

    (
        {'slug': 'nuer', 'name': 'Thok Naath',
         'english_name': 'Nuer',
         'family': 'nilo-saharan', 'subgroup': 'Nilotic (West)',
         'region': 'South Sudan, Ethiopia', 'iso639_3': 'nus',
         'speakers': 2000000, 'word_order': 'svo',
         'notes': 'SVO; three-way vowel length; modal tonal contrasts.'},
        [{
            'slug': 'nus-wut-ci-duëël-lath',
            'konso': 'wut cɛ duëël lath',
            'gloss': 'man  PFV  house  build',
            'translation': 'The man built a house.',
            'tree_bracket': ('[S [NP wut] '
                             '[VP [Aux cɛ] [NP duëël] [V lath]]]'),
            'notes': 'Very close sibling to Dinka; shared Nilotic '
                     'aspectual auxiliary `cɛ/acï`.',
            'source': 'illustrative',
            'citation': 'Crazzolara (1933), *Outlines of a Nuer '
                        'Grammar*.',
        }],
    ),

    (
        {'slug': 'maasai', 'name': 'ɔl Maa',
         'english_name': 'Maasai',
         'family': 'nilo-saharan', 'subgroup': 'Nilotic (East)',
         'region': 'Kenya, Tanzania', 'iso639_3': 'mas',
         'speakers': 1500000, 'word_order': 'vso',
         'notes': 'VSO; verb-initial; gender on nouns; ATR vowel '
                  'harmony.'},
        [{
            'slug': 'mas-eidukun-olayioni-enkaji',
            'konso': 'eidukun olayioni enkaji',
            'gloss': 'build.PST-3SG  boy.M  house.F',
            'translation': 'The boy built the house.',
            'tree_bracket': ('[S [V eidukun] '
                             '[NP [N olayioni]] '
                             '[NP [N enkaji]]]'),
            'notes': 'Maasai is strictly VSO. Masculine `ol-` and '
                     'feminine `en-` articles are portmanteau '
                     'markers of class + definiteness.',
            'source': 'illustrative',
            'citation': 'Tucker & Mpaayei (1955), *A Maasai Grammar*.',
        }],
    ),

    (
        {'slug': 'luo', 'name': 'Dholuo',
         'english_name': 'Luo',
         'family': 'nilo-saharan', 'subgroup': 'Nilotic (West)',
         'region': 'W Kenya, N Tanzania', 'iso639_3': 'luo',
         'speakers': 5000000, 'word_order': 'svo',
         'notes': 'SVO; tonal; ATR harmony; postposed demonstratives.'},
        [{
            'slug': 'luo-dichuo-nogero-ot',
            'konso': 'dichuo nogero ot',
            'gloss': 'man  PST-build  house',
            'translation': 'A man built a house.',
            'tree_bracket': ('[S [NP dichuo] '
                             '[VP [V nogero] [NP ot]]]'),
            'notes': 'Past prefix `no-` on the verb.',
            'source': 'illustrative',
            'citation': 'Omondi (1982), *The Major Syntactic '
                        'Structures of Dholuo*.',
        }],
    ),

    # ═══════════════════════════════════════════════════════════════
    # NILO-SAHARAN — Saharan, Songhay
    # ═══════════════════════════════════════════════════════════════
    (
        {'slug': 'kanuri', 'name': 'Kànùrí',
         'english_name': 'Kanuri',
         'family': 'nilo-saharan', 'subgroup': 'Saharan',
         'region': 'Nigeria, Niger, Chad, Cameroon',
         'iso639_3': 'knc', 'speakers': 9600000, 'word_order': 'sov',
         'notes': 'SOV; postpositional; tonal; the historical '
                  'language of the Kanem-Bornu Empire.'},
        [{
            'slug': 'knc-kamjiro-fato-yakkin',
            'konso': 'kamjiro fato yakkin',
            'gloss': 'man  house  build.PST.3SG',
            'translation': 'The man built a house.',
            'tree_bracket': ('[S [NP kamjiro] '
                             '[VP [NP fato] [V yakkin]]]'),
            'notes': 'SOV like most Saharan / Nilo-Saharan except '
                     'the Nilotic branch.',
            'source': 'illustrative',
            'citation': 'Cyffer (1998), *A Sketch of Kanuri*.',
        }],
    ),

    (
        {'slug': 'songhai', 'name': 'Soŋay',
         'english_name': 'Songhai (Koyra Chiini)',
         'family': 'nilo-saharan', 'subgroup': 'Songhay',
         'region': 'Mali (Timbuktu), Niger', 'iso639_3': 'khq',
         'speakers': 300000, 'word_order': 'svo',
         'notes': 'SVO (this variety); some sister Songhay languages '
                  'are SOV. TAM particles preverbal.'},
        [{
            'slug': 'khq-aru-na-hu-tee',
            'konso': 'aru na hu tee',
            'gloss': 'man  PST  house  do/build',
            'translation': 'The man built a house.',
            'tree_bracket': ('[S [NP aru] '
                             '[VP [Aux na] [NP hu] [V tee]]]'),
            'notes': 'Past TAM particle `na` precedes the verb. In '
                     'this variety the object precedes the verb '
                     'despite general SVO — a mixed profile.',
            'source': 'illustrative',
            'citation': 'Heath (1999), *A Grammar of Koyra Chiini*.',
        }],
    ),

    # ═══════════════════════════════════════════════════════════════
    # KHOE-KWADI / "KHOISAN" (clicks)
    # ═══════════════════════════════════════════════════════════════
    (
        {'slug': 'khoekhoe', 'name': 'Khoekhoegowab (Nama)',
         'english_name': 'Khoekhoe (Nama/Damara)',
         'family': 'khoe-kwadi', 'subgroup': 'Khoe (Central)',
         'region': 'Namibia, South Africa, Botswana',
         'iso639_3': 'naq', 'speakers': 200000, 'word_order': 'sov',
         'notes': 'SOV; four click phonemes (| ! ǂ ǁ) with '
                  'accompaniments; Person-Gender-Number marker suffixes '
                  'on NPs.'},
        [{
            'slug': 'naq-khoeb-omib-ge-kuru',
            'konso': 'khoeb omib ge kuru',
            'gloss': 'man.3SG.M  house.3SG.M  DECL  make/build',
            'translation': 'The man built a house.',
            'tree_bracket': ('[S [NP [N khoeb]] '
                             '[VP [NP [N omib]] [Decl ge] [V kuru]]]'),
            'notes': 'Declarative particle `ge`. 3SG.M suffix `-b` '
                     'on both nouns. Clicks |, !, ǂ, ǁ are not '
                     'present in this particular sentence but are '
                     'the hallmark Khoe feature.',
            'source': 'illustrative',
            'citation': 'Haacke (1999), *The Tonology of Khoekhoe '
                        '(Nama/Damara)*.',
        }],
    ),

    (
        {'slug': 'juhoansi', 'name': "Juǀ\u2019hoansi",
         'english_name': "Ju|'hoansi",
         'family': 'khoe-kwadi', 'subgroup': 'Kx\'a (Ju)',
         'region': 'Namibia, Botswana', 'iso639_3': 'ktz',
         'speakers': 20000, 'word_order': 'svo',
         'notes': 'SVO; 48 click phonemes; one of the famous "San" '
                  'groups; the language of the !Kung bushmen.'},
        [{
            'slug': 'ktz-ju-ko-tju',
            'konso': "ju ko ǁom",
            'gloss': 'person  PRF  build.shelter',
            'translation': 'A person built a shelter.',
            'tree_bracket': ("[S [NP ju] [VP [Aux ko] [V ǁom]]]"),
            'notes': "Lateral click ǁ in the verb. Ju|'hoansi is SVO.",
            'source': 'illustrative',
            'citation': "Dickens (2005), *A Concise Grammar of "
                        "Juǀ'hoan*.",
        }],
    ),

    (
        {'slug': 'taa', 'name': "!Xóõ",
         'english_name': '!Xóõ (Taa)',
         'family': 'khoe-kwadi', 'subgroup': 'Tuu',
         'region': 'Botswana, Namibia', 'iso639_3': 'nmn',
         'speakers': 2500, 'word_order': 'svo',
         'notes': 'SVO; famous for having possibly the largest '
                  'consonant inventory of any documented language '
                  '(~160 segments incl. five click types).'},
        [{
            'slug': 'nmn-taa-nn-dao',
            'konso': 'tâa ʘuu dao',
            'gloss': 'person  build  shelter',
            'translation': 'A person built a shelter.',
            'tree_bracket': ("[S [NP tâa] [VP [V ʘuu] [NP dao]]]"),
            'notes': "Bilabial click ʘ. The bracket tree elides a "
                     "great deal of !Xóõ's nominal complexity.",
            'source': 'illustrative',
            'citation': 'Traill (1994), *A !Xóõ Dictionary*.',
        }],
    ),

    (
        {'slug': 'sandawe', 'name': 'Sandaweki',
         'english_name': 'Sandawe',
         'family': 'khoe-kwadi', 'subgroup': 'Sandawe (possibly Khoe)',
         'region': 'Tanzania', 'iso639_3': 'sad',
         'speakers': 60000, 'word_order': 'sov',
         'notes': 'SOV; four click phonemes. Historically grouped '
                  'with "Khoisan"; modern work links it to Khoe.'},
        [{
            'slug': 'sad-hatsa-keke-k-a',
            'konso': 'xonu !a ka',
            'gloss': 'man  house  build.PST',
            'translation': 'The man built a house.',
            'tree_bracket': '[S [NP xonu] [VP [NP !a] [V ka]]]',
            'notes': 'Postalveolar click ! in the object. Sandawe is '
                     'SOV.',
            'source': 'illustrative',
            'citation': 'Steeman (2012), *A Grammar of Sandawe*.',
        }],
    ),

    # ═══════════════════════════════════════════════════════════════
    # ISOLATE
    # ═══════════════════════════════════════════════════════════════
    (
        {'slug': 'hadza', 'name': 'Hadzane',
         'english_name': 'Hadza',
         'family': 'isolate', 'subgroup': 'Language isolate',
         'region': 'Tanzania (Lake Eyasi)', 'iso639_3': 'hts',
         'speakers': 1000, 'word_order': 'svo',
         'notes': 'Language isolate; five click phonemes; SVO in '
                  'basic clauses; gender (M/F) on determiners + '
                  'verbs.'},
        [{
            'slug': 'hts-monoko-ako-domoko',
            'konso': "monoko ako hadakwe",
            'gloss': 'man.M  house.M  build.PST.3SG.M',
            'translation': 'The man built the house.',
            'tree_bracket': '[S [NP monoko] [VP [NP ako] [V hadakwe]]]',
            'notes': 'Tree simplified; Hadza is lightly documented '
                     'and most sentence-level analyses are recent.',
            'source': 'illustrative',
            'citation': 'Sands (2013), *Hadza grammar sketch*; '
                        'Miller (2013).',
        }],
    ),

    # ═══════════════════════════════════════════════════════════════
    # AUSTRONESIAN — Malagasy
    # ═══════════════════════════════════════════════════════════════
    (
        {'slug': 'malagasy', 'name': 'Malagasy (teny Malagasy)',
         'english_name': 'Malagasy',
         'family': 'austronesian', 'subgroup': 'Malayo-Polynesian '
                                              '(Barito)',
         'region': 'Madagascar', 'iso639_3': 'plt',
         'speakers': 25000000, 'word_order': 'vos',
         'notes': 'VOS — verb-initial, subject-final; rare word '
                  'order worldwide; Austronesian voice system '
                  '(actor, undergoer, circumstantial).'},
        [{
            'slug': 'plt-nanao-trano-ilay-lehilahy',
            'konso': 'nanao trano ilay lehilahy',
            'gloss': 'AV.PST-make  house  DEF  man',
            'translation': 'The man made/built a house.',
            'tree_bracket': ('[S [V nanao] [NP trano] '
                             '[NP [Det ilay] [N lehilahy]]]'),
            'notes': 'Verb-Object-Subject. The final NP is the '
                     'subject — typical Malagasy. `n-` prefix marks '
                     'past; actor voice selects the actor as subject.',
            'source': 'illustrative',
            'citation': 'Keenan (1976), "Remarkable subjects in '
                        'Malagasy"; Rasolofo (2006).',
        }],
    ),

    # ═══════════════════════════════════════════════════════════════
    # INDO-EUROPEAN (African)
    # ═══════════════════════════════════════════════════════════════
    (
        {'slug': 'afrikaans', 'name': 'Afrikaans',
         'english_name': 'Afrikaans',
         'family': 'indo-european', 'subgroup': 'Germanic (West)',
         'region': 'South Africa, Namibia', 'iso639_3': 'afr',
         'speakers': 7200000, 'word_order': 'svo',
         'notes': 'SVO in matrix clauses, SOV in subordinate clauses '
                  '(V2 in main, verb-final in embedded — classic '
                  'Germanic). Extensively simplified morphology '
                  'vs. Dutch.'},
        [{
            'slug': 'afr-die-man-het-n-huis-gebou',
            'konso': 'die man het \u2019n huis gebou',
            'gloss': 'the  man  have  a  house  built',
            'translation': 'The man built a house.',
            'tree_bracket': ("[S [NP [Det die] [N man]] "
                             "[VP [Aux het] "
                             "[NP [Det 'n] [N huis]] "
                             "[V gebou]]]"),
            'notes': 'Auxiliary `het` + past participle `gebou` — '
                     'the object stays between aux and participle, '
                     'a Germanic brace construction.',
            'source': 'illustrative',
            'citation': 'Donaldson (1993), *A Grammar of Afrikaans*.',
        }],
    ),

    # ═══════════════════════════════════════════════════════════════
    # CREOLES / PIDGINS
    # ═══════════════════════════════════════════════════════════════
    (
        {'slug': 'nigerian-pidgin', 'name': 'Naijá',
         'english_name': 'Nigerian Pidgin',
         'family': 'creole', 'subgroup': 'English-lexifier',
         'region': 'Nigeria', 'iso639_3': 'pcm',
         'speakers': 75000000, 'word_order': 'svo',
         'notes': 'SVO; English-lexified; preverbal TAM particles '
                  '(don, go, dey); far more morphologically isolating '
                  'than English.'},
        [{
            'slug': 'pcm-di-man-don-build-house',
            'konso': 'di man don build house',
            'gloss': 'the  man  PFV  build  house',
            'translation': 'The man has built a house.',
            'tree_bracket': ('[S [NP [Det di] [N man]] '
                             '[VP [Aux don] [V build] [NP house]]]'),
            'notes': 'Preverbal `don` marks perfective aspect — '
                     'unrelated (despite the orthography) to '
                     'English "done".',
            'source': 'illustrative',
            'citation': 'Faraclas (1996), *Nigerian Pidgin*.',
        }],
    ),

    (
        {'slug': 'krio', 'name': 'Krio',
         'english_name': 'Krio (Sierra Leone)',
         'family': 'creole', 'subgroup': 'English-lexifier',
         'region': 'Sierra Leone', 'iso639_3': 'kri',
         'speakers': 7400000, 'word_order': 'svo',
         'notes': 'SVO; English-lexified; substrates from Yoruba, '
                  'Temne, Akan.'},
        [{
            'slug': 'kri-di-man-bil-ose',
            'konso': 'di man bil ose',
            'gloss': 'the  man  build  house',
            'translation': 'The man built a house.',
            'tree_bracket': ('[S [NP [Det di] [N man]] '
                             '[VP [V bil] [NP ose]]]'),
            'notes': 'Zero TAM in the neutral past sense — context '
                     'alone carries tense.',
            'source': 'illustrative',
            'citation': 'Finney (2004), *Krio Syntax*.',
        }],
    ),

    (
        {'slug': 'sango', 'name': 'Sängö',
         'english_name': 'Sango',
         'family': 'creole', 'subgroup': 'Ngbandi-lexifier creole',
         'region': 'Central African Republic', 'iso639_3': 'sag',
         'speakers': 5000000, 'word_order': 'svo',
         'notes': 'SVO; lingua franca of CAR; Ngbandi-based creole '
                  'with French and Bantu loans.'},
        [{
            'slug': 'sag-koli-asala-da',
            'konso': 'kôli asâla da',
            'gloss': 'man  3SG-build  house',
            'translation': 'The man built a house.',
            'tree_bracket': ('[S [NP kôli] '
                             '[VP [V asâla] [NP da]]]'),
            'notes': 'Subject prefix `a-` on the verb is retained '
                     'from the Bantu substrate even though Sango\'s '
                     'lexifier is Ngbandi.',
            'source': 'illustrative',
            'citation': 'Samarin (1967), *A Grammar of Sango*.',
        }],
    ),

    (
        {'slug': 'cape-verdean', 'name': 'Kabuverdianu',
         'english_name': 'Cape Verdean Creole',
         'family': 'creole', 'subgroup': 'Portuguese-lexifier',
         'region': 'Cape Verde', 'iso639_3': 'kea',
         'speakers': 1300000, 'word_order': 'svo',
         'notes': 'SVO; Portuguese-lexified; Mande + West African '
                  'substrates; oldest Atlantic creole.'},
        [{
            'slug': 'kea-omi-fazi-kaza',
            'konso': 'omi fazi kaza',
            'gloss': 'man  make.PST  house',
            'translation': 'A man built a house.',
            'tree_bracket': ('[S [NP omi] '
                             '[VP [V fazi] [NP kaza]]]'),
            'notes': 'Lexemes from Portuguese: homem → omi, '
                     'fez/fazer → fazi, casa → kaza.',
            'source': 'illustrative',
            'citation': 'Baptista (2002), *The Syntax of Cape '
                        'Verdean Creole*.',
        }],
    ),
]


class Command(BaseCommand):
    help = ('Seed ~45 African languages + one representative '
            'sentence each. Extends (does not replace) the Konso '
            'sentences from seed_konso.')

    def add_arguments(self, parser):
        parser.add_argument(
            '--reset', action='store_true',
            help='Delete ALL Language rows (and their Sentences) '
                 'before seeding. Destructive.')

    def handle(self, *args, **opts):
        if opts['reset']:
            sent_n = Sentence.objects.filter(
                language__isnull=False).delete()[0]
            lang_n = Language.objects.all().delete()[0]
            self.stdout.write(
                f'Deleted {lang_n} languages and {sent_n} attached '
                f'sentences.')

        made_lang, updated_lang = 0, 0
        made_sent, updated_sent, bad_trees = 0, 0, 0

        for lang_data, sentences in SEEDS:
            slug = lang_data['slug']
            with transaction.atomic():
                lang, created = Language.objects.update_or_create(
                    slug=slug, defaults=lang_data)
                if created:
                    made_lang += 1
                else:
                    updated_lang += 1
                self.stdout.write(
                    f'{"+" if created else "~"} {slug:22} '
                    f'{lang.english_name}')

                for row in sentences:
                    try:
                        parse_bracket(row['tree_bracket'])
                    except Exception as e:
                        bad_trees += 1
                        self.stderr.write(self.style.ERROR(
                            f'  ! {row["slug"]}: bad tree ({e})'))
                        continue
                    defaults = {**{k: v for k, v in row.items()
                                   if k != 'slug'},
                                'language': lang}
                    _, was_new = Sentence.objects.update_or_create(
                        slug=row['slug'], defaults=defaults)
                    if was_new:
                        made_sent += 1
                    else:
                        updated_sent += 1

        # Link pre-existing Konso sentences to the Konso Language row.
        konso_lang = Language.objects.filter(slug='konso').first()
        if konso_lang:
            linked = Sentence.objects.filter(
                language__isnull=True).update(language=konso_lang)
            if linked:
                self.stdout.write(
                    f'Linked {linked} legacy Konso sentences to '
                    f'Language<konso>.')

        self.stdout.write(self.style.SUCCESS(
            f'Languages: +{made_lang} new, ~{updated_lang} updated. '
            f'Sentences: +{made_sent} new, ~{updated_sent} updated, '
            f'{bad_trees} bad trees.'))
