"""Finer-resolution Northwest Semitic coverage, plus related branches.

Muka's initial Semitic coverage was two ancient Canaanite/Aramaic
entries (Ancient Hebrew, Imperial Aramaic) and three Ethiosemitic
plus MSA / Egyptian Arabic — enough to sketch the family but too
coarse for anyone interested in the Northwest Semitic sub-area.

This seed fills out the Canaanite and Aramaic branches and adds
four close relatives for contrast:

  Canaanite (Northwest, with Ugaritic as sister branch):
    - Modern Hebrew, Samaritan Hebrew
    - Phoenician, Punic
    - Moabite
    - Ugaritic

  Aramaic (Northwest):
    Ancient / classical —
      - Old Aramaic-Sam'alian, Nabataean Aramaic
      - Classical Syriac
      - Jewish Babylonian Aramaic
      - Jewish Palestinian Aramaic (Targumic)
      - Samaritan Aramaic
      - Christian Palestinian Aramaic
      - Classical Mandaic
    Modern (Neo-Aramaic) —
      - Western Neo-Aramaic (Maaloula)
      - Turoyo (Ṭur ʿAbdin)
      - Assyrian Neo-Aramaic
      - Chaldean Neo-Aramaic
      - Hulaulá (Lishán Didán)
      - Neo-Mandaic

  Related branches:
    - Akkadian (East Semitic) — 2 sentences
    - Sabaic (Sayhadic / Old South Arabian)
    - Mehri (Modern South Arabian)
    - Maltese (Central Semitic, Siculo-Arabic descendant — Latin script)

Each entry gets one illustrative sentence in labelled-bracket form
except Akkadian (two: seize-the-city and build-a-house, both Old
Babylonian). Sentences drawn from known inscriptional or literary
material are flagged ``literature`` with a citation; composed
grammar-book examples stay ``illustrative``.

Run:      venv/bin/python manage.py seed_northwest_semitic
Re-run:   safe — both languages and sentences use update_or_create.
"""

from django.core.management.base import BaseCommand
from django.db import transaction

from muka.models import Language, Sentence
from muka.tree import parse_bracket


SEEDS = [

    # ═══════════════════════════════════════════════════════════════
    # CANAANITE — Hebrew branches
    # ═══════════════════════════════════════════════════════════════
    (
        {'slug': 'modern-hebrew', 'glottocode': 'hebr1245',
         'name': 'עִבְרִית', 'english_name': 'Modern Hebrew',
         'family': 'afroasiatic', 'family_name': 'Afro-Asiatic',
         'subgroup': 'Semitic (Northwest, Canaanite)',
         'region': 'Israel', 'iso639_3': 'heb', 'macroarea': 'Eurasia',
         'speakers': 9_000_000, 'word_order': 'svo',
         'script': 'Hebrew (square script)',
         'extinct': False,
         'latitude': 31.7761, 'longitude': 35.1725,
         'notes': 'Revived from Biblical Hebrew in the late 19th–early '
                  '20th century; syntax has shifted toward SVO under '
                  'European contact while morphology (binyan patterns, '
                  'construct state) stays broadly classical.'},
        [{
            'slug': 'heb-ha-yeled-qore-sefer',
            'konso': 'הילד קורא ספר',
            'gloss': 'the-boy  read.PRS.SG.M  book',
            'translation': 'The boy is reading a book.',
            'tree_bracket': ('[S [NP [Det ha-] [N yeled]] '
                             '[VP [V qoreʾ] [NP [N sefer]]]]'),
            'notes': 'Canonical Modern Hebrew SVO. Present-tense verbs '
                     'are originally participles and agree in gender and '
                     'number but not person. No indefinite article on '
                     '*sefer*.',
            'source': 'illustrative',
            'citation': 'Glinert (2015), *Modern Hebrew: An Essential '
                        'Grammar*, §§12–14.',
        }],
    ),

    (
        {'slug': 'samaritan-hebrew', 'glottocode': 'sama1313',
         'name': 'ࠏࠁࠓࠉࠕ ࠔࠌࠓࠉࠌ', 'english_name': 'Samaritan Hebrew',
         'family': 'afroasiatic', 'family_name': 'Afro-Asiatic',
         'subgroup': 'Semitic (Northwest, Canaanite)',
         'region': 'Mount Gerizim, Nablus / Holon',
         'iso639_3': 'smp', 'macroarea': 'Eurasia',
         'speakers': 800, 'word_order': 'vso',
         'script': 'Samaritan',
         'extinct': False,
         'latitude': 32.0817, 'longitude': 35.4487,
         'notes': 'Liturgical/Torah-reading register of the Samaritan '
                  'community. The consonantal text is essentially the '
                  'Pentateuch, but phonology differs sharply from '
                  'Tiberian Hebrew: loss of the gutturals, assimilation '
                  'of emphatics, and a distinct vowel system. Script '
                  'continues Paleo-Hebrew.'},
        [{
            'slug': 'smp-bara-elowwem',
            'konso': 'ברא אלהים את השמים',
            'gloss': 'create.PRF.3SG.M  God  ACC  the-heavens',
            'translation': '(God created the heavens — opening of '
                           'Genesis 1:1, Samaritan reading.)',
            'tree_bracket': ('[S [V bārā] [NP [N ēlūwwəm]] '
                             '[NP [Part ēt] [NP [Det aš-] [N šāmīm]]]]'),
            'notes': 'Samaritan phonology realises אלהים as *ēlūwwəm* '
                     '(no /h/ and with /u/ for Tiberian /o/), ה־ '
                     'assimilates to aš- before the sibilant. VSO '
                     'narrative order preserved from Biblical Hebrew.',
            'source': 'literature',
            'citation': 'Ben-Ḥayyim (2000), *A Grammar of Samaritan '
                        'Hebrew*, §§3.1, 4.4; text: Samaritan Pentateuch '
                        'Gen 1:1.',
        }],
    ),

    # ═══════════════════════════════════════════════════════════════
    # CANAANITE — Phoenician branch
    # ═══════════════════════════════════════════════════════════════
    (
        {'slug': 'phoenician', 'glottocode': 'phoe1239',
         'name': '𐤃𐤁𐤓𐤉𐤌 𐤊𐤍𐤏𐤍𐤉𐤌',
         'english_name': 'Phoenician',
         'family': 'afroasiatic', 'family_name': 'Afro-Asiatic',
         'subgroup': 'Semitic (Northwest, Canaanite)',
         'region': 'Levantine coast (Tyre, Sidon, Byblos)',
         'iso639_3': 'phn', 'macroarea': 'Eurasia',
         'speakers': 0, 'word_order': 'vso',
         'script': 'Phoenician',
         'extinct': True,
         'latitude': 34.12, 'longitude': 35.65,
         'notes': 'Closest known sister of Biblical Hebrew. No definite '
                  'article in the earliest layer; h- spreads later. '
                  'VSO in narrative, with a strong tradition of '
                  'verbless nominal-identity clauses in royal '
                  'inscriptions (ʾnk + PN).'},
        [{
            'slug': 'phn-anok-kilamuwa',
            'konso': '𐤀𐤍𐤊 𐤊𐤋𐤌𐤅 𐤁𐤓 𐤇𐤉𐤀',
            'gloss': 'I  Kilamuwa  son  Ḥayya',
            'translation': 'I am Kilamuwa, son of Ḥayya.',
            'tree_bracket': ('[S [NP [Pron ʾnk]] '
                             '[NP [N klmw] '
                             '[NP [N br] [N ḥyʾ]]]]'),
            'notes': 'Verbless identification clause — the pronoun '
                     '*ʾnk* is the predicate subject, the apposed NP '
                     'the predicate. Typical opening of a royal '
                     'inscription.',
            'source': 'literature',
            'citation': 'KAI 24:1 (Kilamuwa inscription, Zincirli, '
                        '9th c. BCE).',
        }],
    ),

    (
        {'slug': 'punic', 'glottocode': 'puni1241',
         'name': '𐤃𐤁𐤓𐤉𐤌 𐤐𐤍𐤊𐤉𐤌', 'english_name': 'Punic',
         'family': 'afroasiatic', 'family_name': 'Afro-Asiatic',
         'subgroup': 'Semitic (Northwest, Canaanite)',
         'region': 'Carthage and the western Mediterranean',
         'iso639_3': 'xpu', 'macroarea': 'Africa',
         'speakers': 0, 'word_order': 'vso',
         'script': 'Phoenician / Neo-Punic',
         'extinct': True,
         'latitude': 36.5272, 'longitude': 10.3564,
         'notes': 'Late Western descendant of Phoenician, epigraphic '
                  'from ~800 BCE until the Roman African provinces. '
                  'Neo-Punic cursive evolves distinctive letter shapes. '
                  'The Latin-script Punic fragment in Plautus\' '
                  '*Poenulus* is the best-known non-epigraphic witness.'},
        [{
            'slug': 'xpu-l-adon-l-baal-hammon',
            'konso': '𐤋𐤀𐤃𐤍 𐤋𐤁𐤏𐤋 𐤇𐤌𐤍',
            'gloss': 'to-lord  to-Baʿal  Ḥammon',
            'translation': 'To the Lord, to Baʿal-Ḥammon.',
            'tree_bracket': ('[PP [P l-] '
                             '[NP [N ʾdn] '
                             '[PP [P l-] '
                             '[NP [N bʿl] [N ḥmn]]]]]'),
            'notes': 'Dedicatory formula heading many Punic votive '
                     'stelae from Carthage and Tophet sanctuaries. '
                     'Two parallel l- prepositional phrases — the '
                     'generic *ʾdn* "lord" glosses the specific deity '
                     '*bʿl ḥmn* that follows.',
            'source': 'literature',
            'citation': 'CIS I 180 and passim (Carthage votive stelae, '
                        '4th–2nd c. BCE).',
        }],
    ),

    (
        {'slug': 'moabite', 'glottocode': 'moab1234',
         'name': '𐤋𐤔𐤍 𐤌𐤀𐤁', 'english_name': 'Moabite',
         'family': 'afroasiatic', 'family_name': 'Afro-Asiatic',
         'subgroup': 'Semitic (Northwest, Canaanite)',
         'region': 'Transjordanian plateau (Dibon/Moab)',
         'iso639_3': 'obm', 'macroarea': 'Eurasia',
         'speakers': 0, 'word_order': 'vso',
         'script': 'Paleo-Hebrew / Moabite',
         'extinct': True,
         'latitude': 31.515, 'longitude': 35.784,
         'notes': 'Attested almost entirely through the Mesha Stele '
                  '(KAI 181, ~840 BCE) and a few smaller inscriptions. '
                  'Mutually intelligible with Hebrew; shares the '
                  'prefixed definite article h-, the waw-consecutive, '
                  'and the Canaanite shift.'},
        [{
            'slug': 'obm-anok-mesha',
            'konso': '𐤀𐤍𐤊 𐤌𐤔𐤏 𐤁𐤍 𐤊𐤌𐤔𐤉𐤕 𐤌𐤋𐤊 𐤌𐤀𐤁',
            'gloss': 'I  Mesha  son  Kemosh-yatti  king  Moab',
            'translation': 'I am Mesha, son of Kemosh-yatti, king of '
                           'Moab.',
            'tree_bracket': ('[S [NP [Pron ʾnk]] '
                             '[NP [N mšʿ] '
                             '[NP [N bn] [N kmšyt]] '
                             '[NP [N mlk] [N mʾb]]]]'),
            'notes': 'Opening line of the Mesha Stele. Verbless '
                     'nominal identity clause, identical pattern to '
                     'Phoenician Kilamuwa — characteristic of 9th-c. '
                     'royal memorial inscriptions across the NW '
                     'Semitic area.',
            'source': 'literature',
            'citation': 'KAI 181:1 (Mesha Stele, Dibon, ca. 840 BCE).',
        }],
    ),

    # ═══════════════════════════════════════════════════════════════
    # NORTHWEST SEMITIC — Ugaritic (sister branch to Canaanite/Aramaic)
    # ═══════════════════════════════════════════════════════════════
    (
        {'slug': 'ugaritic', 'glottocode': 'ugar1238',
         'name': '𐎍𐎌𐎐 𐎜𐎂𐎗𐎚',
         'english_name': 'Ugaritic',
         'family': 'afroasiatic', 'family_name': 'Afro-Asiatic',
         'subgroup': 'Semitic (Northwest, Ugaritic)',
         'region': 'Ras Shamra, coastal Syria (Late Bronze Age)',
         'iso639_3': 'uga', 'macroarea': 'Eurasia',
         'speakers': 0, 'word_order': 'vso',
         'script': 'Ugaritic cuneiform alphabet',
         'extinct': True,
         'latitude': 35.6, 'longitude': 35.78,
         'notes': 'Attested in a ~30-letter alphabetic cuneiform from '
                  '~1400–1200 BCE. Classified either with Canaanite or '
                  'as its own Northwest Semitic branch. Sibilant '
                  'inventory closer to Proto-Semitic than Canaanite '
                  '(preserves ṯ, ḏ, ẓ, ġ).'},
        [{
            'slug': 'uga-yqra-krt',
            'konso': '𐎊𐎖𐎗𐎛 𐎋𐎗𐎚 𐎍𐎛𐎍',
            'gloss': 'call.IMPF.3SG.M  Kirta  to-El',
            'translation': 'Kirta calls to El.',
            'tree_bracket': ('[S [V yqrʾ] '
                             '[NP [N krt]] '
                             '[PP [P l-] [N ʾil]]]'),
            'notes': 'VSO narrative pattern of the Ugaritic epic '
                     'cycles. The prefix conjugation *yqrʾ* functions '
                     'as narrative present in the poetic texts; '
                     'directional *l-* marks the addressee of a verb '
                     'of speaking.',
            'source': 'illustrative',
            'citation': 'Pardee (2003), "Ugaritic", in Woodard ed. '
                        '*Cambridge Encyclopedia of the World\'s '
                        'Ancient Languages*, §§5.2.2, 5.4.1.',
        }],
    ),

    # ═══════════════════════════════════════════════════════════════
    # ARAMAIC — ancient and classical
    # ═══════════════════════════════════════════════════════════════
    (
        {'slug': 'old-aramaic-samalian', 'glottocode': 'olda1245',
         'name': 'ארמית עתיקה',
         'english_name': "Old Aramaic / Sam'alian",
         'family': 'afroasiatic', 'family_name': 'Afro-Asiatic',
         'subgroup': 'Semitic (Northwest, Aramaic, Old)',
         'region': 'North Syria / SE Anatolia (Samʾal, Aleppo)',
         'iso639_3': 'oar', 'macroarea': 'Eurasia',
         'speakers': 0, 'word_order': 'svo',
         'script': 'Aramaic (Old)',
         'extinct': True,
         'latitude': 32.84, 'longitude': 37.0,
         'notes': 'First-millennium-BCE stratum that precedes the '
                  'Imperial Aramaic koiné. Samʾalian (Zincirli) '
                  'preserves archaic features (masculine-plural -w '
                  'rather than -n, no definite -ā) and is sometimes '
                  'classed apart from mainline Old Aramaic.'},
        [{
            'slug': 'oar-pnmw-br-qrl',
            'konso': 'אנך פנמו בר קרל מלך יאדי',
            'gloss': 'I  Panamuwa  son  Qarli  king  Yaʾudi',
            'translation': 'I am Panamuwa, son of Qarli, king of '
                           'Yaʾudi.',
            'tree_bracket': ('[S [NP [Pron ʾnk]] '
                             '[NP [N pnmw] '
                             '[NP [N br] [N qrl]] '
                             '[NP [N mlk] [N yʾdy]]]]'),
            'notes': 'Samʾalian royal-identity clause. Same pattern '
                     'as the Canaanite ʾnk openings — the NW Semitic '
                     'area shares a "monumental voice" across '
                     'languages. Note masculine "son" is *br* '
                     '(Aramaic) not *bn* (Canaanite).',
            'source': 'literature',
            'citation': 'KAI 214:1 (Hadad inscription of Panamuwa I, '
                        'Zincirli, mid-8th c. BCE).',
        }],
    ),

    (
        {'slug': 'nabataean-aramaic', 'glottocode': 'naba1241',
         'name': 'ארמית נבטית',
         'english_name': 'Nabataean Aramaic',
         'family': 'afroasiatic', 'family_name': 'Afro-Asiatic',
         'subgroup': 'Semitic (Northwest, Aramaic, Western)',
         'region': 'Nabataean kingdom (Petra, Hegra)',
         'iso639_3': 'xna', 'macroarea': 'Eurasia',
         'speakers': 0, 'word_order': 'svo',
         'script': 'Nabataean',
         'extinct': True,
         'latitude': 30.3285, 'longitude': 35.4444,
         'notes': 'Written register of the Nabataean kingdom, '
                  '2nd c. BCE–early 4th c. CE. The cursive Nabataean '
                  'script is the direct ancestor of Arabic writing; '
                  'the spoken language of the Nabataeans is now '
                  'generally taken to have been an early form of '
                  'Arabic, even though the inscriptions are Aramaic.'},
        [{
            'slug': 'xna-dnh-qbra',
            'konso': 'דנה כפרא די עבד חרתת מלך נבטו',
            'gloss': 'this  tomb-DEF  REL  make.PRF.3SG  Ḥāritat  '
                     'king  Nabatu',
            'translation': 'This is the tomb which Ḥāritat, king of '
                           'the Nabataeans, made.',
            'tree_bracket': ('[S [NP [Dem dnh]] [NP [N kprʾ]] '
                             '[CP [Rel dy] '
                             '[S [V ʿbd] '
                             '[NP [N ḥrtt] '
                             '[NP [N mlk] [N nbṭw]]]]]]'),
            'notes': 'Classic Nabataean funerary formula. *dy* is '
                     'both relative and genitive marker. Emphatic '
                     '-ā on *kprʾ* marks definiteness, as in all '
                     'mainline Aramaic.',
            'source': 'literature',
            'citation': 'Healey (1993), *The Nabataean Tomb '
                        'Inscriptions of Madaʾin Salih*, H1.',
        }],
    ),

    (
        {'slug': 'classical-syriac', 'glottocode': 'clas1252',
         'name': 'ܠܫܢܐ ܣܘܪܝܝܐ', 'english_name': 'Classical Syriac',
         'family': 'afroasiatic', 'family_name': 'Afro-Asiatic',
         'subgroup': 'Semitic (Northwest, Aramaic, Eastern)',
         'region': 'Edessa (Urfa) and the wider Syriac world',
         'iso639_3': 'syc', 'macroarea': 'Eurasia',
         'speakers': 0, 'word_order': 'vso',
         'script': 'Syriac (Estrangela / Serto / Madnḥāyā)',
         'extinct': True,
         'latitude': 37.1129, 'longitude': 42.1432,
         'notes': 'Literary Eastern Aramaic of Edessa, the vehicle of '
                  'the Peshitta and a vast patristic and scientific '
                  'literature. Still used liturgically by Syriac '
                  'Orthodox, Maronite, Assyrian and Chaldean churches.'},
        [{
            'slug': 'syc-emar-marya',
            'konso': 'ܐܡܪ ܡܪܝܐ',
            'gloss': 'say.PRF.3SG.M  Lord-DEF',
            'translation': 'The Lord said.',
            'tree_bracket': ('[S [V ʾemar] '
                             '[NP [N māryā]]]'),
            'notes': 'Verb-initial narrative clause, ubiquitous '
                     'Peshitta pattern. *māryā* = emphatic-state '
                     '*mār* + definite -ā, the standard Aramaic '
                     'rendering of the divine name.',
            'source': 'literature',
            'citation': 'Peshitta, passim (e.g. Gen 12:1); grammar: '
                        'Muraoka (2005), *Classical Syriac*, §§71–72.',
        }],
    ),

    (
        {'slug': 'jewish-babylonian-aramaic', 'glottocode': 'jewi1240',
         'name': 'ארמית בבלית',
         'english_name': 'Jewish Babylonian Aramaic',
         'family': 'afroasiatic', 'family_name': 'Afro-Asiatic',
         'subgroup': 'Semitic (Northwest, Aramaic, Eastern)',
         'region': 'Babylonia (Sasanian Mesopotamia)',
         'iso639_3': 'tmr', 'macroarea': 'Eurasia',
         'speakers': 0, 'word_order': 'svo',
         'script': 'Hebrew (square script)',
         'extinct': True,
         'latitude': 32.273, 'longitude': 44.245,
         'notes': 'Language of the Babylonian Talmud and geonic '
                  'responsa (~200–1200 CE). Distinct from Western '
                  'Aramaic in vocabulary, morphology (e.g. '
                  'prefixed n- / l- third-person imperfective), and '
                  'the loss of final laryngeals.'},
        [{
            'slug': 'tmr-amar-rava',
            'konso': 'אמר רבא',
            'gloss': 'say.PRF.3SG.M  Rava',
            'translation': 'Rava said.',
            'tree_bracket': ('[S [V ʾamar] [NP [N Rāvā]]]'),
            'notes': 'The iconic Talmudic citation formula. '
                     'Verb-first, subject is the attributed sage. '
                     'The whole Babylonian Talmud is built out of '
                     'chains of these.',
            'source': 'literature',
            'citation': 'Bavli, passim; grammar: Sokoloff (2002), '
                        '*A Dictionary of Jewish Babylonian Aramaic*.',
        }],
    ),

    (
        {'slug': 'jewish-palestinian-aramaic', 'glottocode': 'jewi1242',
         'name': 'ארמית ארץ־ישראלית',
         'english_name': 'Jewish Palestinian Aramaic',
         'family': 'afroasiatic', 'family_name': 'Afro-Asiatic',
         'subgroup': 'Semitic (Northwest, Aramaic, Western)',
         'region': 'Roman/Byzantine Palestine',
         'iso639_3': 'jpa', 'macroarea': 'Eurasia',
         'speakers': 0, 'word_order': 'vso',
         'script': 'Hebrew (square script)',
         'extinct': True,
         'latitude': 32.276, 'longitude': 35.195,
         'notes': 'Targumic / Galilean Aramaic — the vernacular '
                  'substrate of the Palestinian Talmud, the Targumim '
                  '(Onqelos, Jonathan, Neofiti), and most Midrashim. '
                  'Western Aramaic diagnostic: 3MP perfective ends '
                  '-wn, imperfective prefix is y-.'},
        [{
            'slug': 'jpa-bqadmin-bera',
            'konso': 'בקדמין ברא יהוה ית שמיא',
            'gloss': 'in-beginning  create.PRF.3SG.M  YHWH  ACC  '
                     'heavens-DEF',
            'translation': 'In the beginning YHWH created the heavens.',
            'tree_bracket': ('[S [PP [P b-] [N qaḏmīn]] '
                             '[V bǝrā] '
                             '[NP [N YHWH]] '
                             '[NP [Part yaṯ] '
                             '[NP [N šǝmayyā]]]]'),
            'notes': 'Opening of Targum Onqelos to Genesis 1:1 '
                     '(abbreviated). *yaṯ* is the characteristic '
                     'Western-Aramaic definite-accusative particle, '
                     'cognate with Hebrew *ʾet*.',
            'source': 'literature',
            'citation': 'Targum Onqelos, Gen 1:1; grammar: Sokoloff '
                        '(2002), *A Dictionary of Jewish Palestinian '
                        'Aramaic*.',
        }],
    ),

    (
        {'slug': 'samaritan-aramaic', 'glottocode': 'sama1314',
         'name': 'ࠀࠓࠌࠉࠕ ࠔࠌࠓࠉࠕࠍ',
         'english_name': 'Samaritan Aramaic',
         'family': 'afroasiatic', 'family_name': 'Afro-Asiatic',
         'subgroup': 'Semitic (Northwest, Aramaic, Western)',
         'region': 'Samaritan community (Mt Gerizim / Holon)',
         'iso639_3': 'sam', 'macroarea': 'Eurasia',
         'speakers': 0, 'word_order': 'vso',
         'script': 'Samaritan',
         'extinct': True,
         'latitude': 32.0817, 'longitude': 35.4487,
         'notes': 'Written in the Samaritan alphabet by the Samaritan '
                  'community from roughly the 3rd–10th c. CE. '
                  'Preserved in the Samaritan Targum, the Memar '
                  'Marqah and liturgical texts. Closely parallel to '
                  'Jewish Palestinian Aramaic in morphology but '
                  'distinct in lexicon and vocalisation.'},
        [{
            'slug': 'sam-bqdmh-bra',
            'konso': 'בקדמה ברא אלה ית שמיה',
            'gloss': 'in-beginning  create.PRF.3SG.M  God  ACC  '
                     'heavens-DEF',
            'translation': 'In the beginning God created the heavens.',
            'tree_bracket': ('[S [PP [P b-] [N qadmah]] '
                             '[V bǝrā] '
                             '[NP [N ʾĕlāh]] '
                             '[NP [Part yaṯ] [NP [N šǝmayyah]]]]'),
            'notes': 'Samaritan Targum Gen 1:1. Where Onqelos has '
                     '*ʾĕlāhā* (emphatic -ā, definite), the Samaritan '
                     'reflex drops the final vowel and writes '
                     '*ʾĕlāh*; directional *h-* / *-h* marks the '
                     'emphatic state instead.',
            'source': 'literature',
            'citation': 'Samaritan Targum, Gen 1:1; grammar: Tal '
                        '(1980), *The Samaritan Targum of the '
                        'Pentateuch*.',
        }],
    ),

    (
        {'slug': 'christian-palestinian-aramaic', 'glottocode': 'chri1264',
         'name': 'ܐܪܡܝܬ ܡܣܝܚܝܬ',
         'english_name': 'Christian Palestinian Aramaic',
         'family': 'afroasiatic', 'family_name': 'Afro-Asiatic',
         'subgroup': 'Semitic (Northwest, Aramaic, Western)',
         'region': 'Melkite communities of Palestine/Transjordan',
         'iso639_3': 'cpa', 'macroarea': 'Eurasia',
         'speakers': 0, 'word_order': 'svo',
         'script': 'Syriac (Christian Palestinian)',
         'extinct': True,
         'latitude': 31.7683, 'longitude': 35.2137,
         'notes': 'Western-Aramaic liturgical dialect of Melkite '
                  '(Chalcedonian) Christians, 6th–13th c. CE. Written '
                  'in a distinct Syriac-family script; corpus consists '
                  'mostly of Gospel lectionaries and patristic '
                  'translations from Greek.'},
        [{
            'slug': 'cpa-abun-d-bshmaya',
            'konso': 'ܐܒܘܢ ܕܒܫܡܝܐ',
            'gloss': 'father-our  REL-in-heavens-DEF',
            'translation': 'Our Father who is in the heavens.',
            'tree_bracket': ('[NP [N ʾbwn] '
                             '[CP [Rel d-] '
                             '[PP [P b-] [NP [N šmyʾ]]]]]'),
            'notes': 'Opening of the Lord\'s Prayer in CPA Gospel '
                     'lectionaries. Relative *d-* introduces a '
                     'locative copula-less clause — "who (is) in '
                     'heaven". Same NP structure as the Syriac '
                     'Peshitta version.',
            'source': 'literature',
            'citation': 'CPA lectionary of Mt 6:9; grammar: Müller-'
                        'Kessler (1991), *Grammatik des Christlich-'
                        'Palästinisch-Aramäischen*.',
        }],
    ),

    (
        {'slug': 'classical-mandaic', 'glottocode': 'clas1253',
         'name': 'ࡌࡀࡍࡃࡀࡉࡉࡀ', 'english_name': 'Classical Mandaic',
         'family': 'afroasiatic', 'family_name': 'Afro-Asiatic',
         'subgroup': 'Semitic (Northwest, Aramaic, Eastern)',
         'region': 'Lower Mesopotamia / Khuzestan',
         'iso639_3': 'myz', 'macroarea': 'Eurasia',
         'speakers': 0, 'word_order': 'svo',
         'script': 'Mandaic',
         'extinct': True,
         'latitude': 36.1203, 'longitude': 49.5659,
         'notes': 'Liturgical language of the Mandaeans, the gnostic '
                  'community of the lower Tigris-Euphrates and '
                  'Karun. Corpus: the Ginza Rabbā, the Book of John, '
                  'the Qolasta, magic bowls. Distinctive Mandaic '
                  'script writes vowels as full letters (including '
                  'matres lectionis for short vowels).'},
        [{
            'slug': 'myz-b-shuma-d-hiia',
            'konso': 'ࡁࡔࡅࡌࡀ ࡖࡄࡉࡉࡀ ࡓࡁࡉࡀ',
            'gloss': 'in-name-DEF  REL-life.PL-DEF  great.PL',
            'translation': 'In the name of the Great Life.',
            'tree_bracket': ('[PP [P b-] '
                             '[NP [N šuma] '
                             '[CP [Rel d-] '
                             '[NP [N hiia] [Adj rbia]]]]]'),
            'notes': 'Invocation opening almost every Mandaic '
                     'liturgical and ritual text. *hiia rbia* '
                     '"the Great Life" is the Mandaean name for '
                     'the supreme principle; *hiia* is '
                     'morphologically plural (life-waters).',
            'source': 'literature',
            'citation': 'Ginza Rabbā, Right §1.1; grammar: Macuch '
                        '(1965), *Handbook of Classical and Modern '
                        'Mandaic*, §§250ff.',
        }],
    ),

    # ═══════════════════════════════════════════════════════════════
    # ARAMAIC — modern (Neo-Aramaic)
    # ═══════════════════════════════════════════════════════════════
    (
        {'slug': 'western-neo-aramaic', 'glottocode': 'west2763',
         'name': 'ܐܪܡܝ ܡܥܠܘܠܐ',
         'english_name': 'Western Neo-Aramaic',
         'family': 'afroasiatic', 'family_name': 'Afro-Asiatic',
         'subgroup': 'Semitic (Northwest, Aramaic, Western)',
         'region': 'Maaloula, Bakhʿa, Jubbʿadin (Qalamoun, Syria)',
         'iso639_3': 'amw', 'macroarea': 'Eurasia',
         'speakers': 15000, 'word_order': 'svo',
         'script': 'Syriac / Arabic (when written)',
         'extinct': False,
         'latitude': 33.8162, 'longitude': 36.484,
         'notes': 'The last surviving Western Aramaic vernacular. '
                  'Three villages in the Qalamoun range north of '
                  'Damascus, traditionally Christian (Maaloula) and '
                  'Muslim (Bakhʿa, Jubbʿadin). Severely disrupted by '
                  'the Syrian war since 2011.'},
        [{
            'slug': 'amw-ana-ixelet-lahma',
            'konso': 'ܐܢܐ ܐܝܟܠܝܬ ܠܚܡܐ',
            'gloss': 'I  eat.PRF.1SG  bread',
            'translation': 'I ate bread.',
            'tree_bracket': ('[S [NP [Pron ana]] '
                             '[VP [V ixelēt] [NP [N laḥma]]]]'),
            'notes': 'Pronoun-subject SVO. The perfective 1SG suffix '
                     '-ēt continues old Aramaic -t; root ʾ-k-l '
                     '"eat" is shared across Semitic.',
            'source': 'illustrative',
            'citation': 'Arnold (1990), *Das Neuwestaramäische V: '
                        'Grammatik*.',
        }],
    ),

    (
        {'slug': 'turoyo', 'glottocode': 'turo1239',
         'name': 'ܛܘܪܝܐ / Ṣuryoyo',
         'english_name': 'Turoyo',
         'family': 'afroasiatic', 'family_name': 'Afro-Asiatic',
         'subgroup': 'Semitic (Northwest, Aramaic, Eastern)',
         'region': 'Ṭur ʿAbdin (SE Turkey) and diaspora',
         'iso639_3': 'tru', 'macroarea': 'Eurasia',
         'speakers': 100000, 'word_order': 'sov',
         'script': 'Syriac (Serto) / Latin (diaspora)',
         'extinct': False,
         'latitude': 37.2275, 'longitude': 42.1451,
         'notes': 'Central Neo-Aramaic of the Ṭur ʿAbdin plateau, '
                  'Syriac Orthodox community. Most speakers now in '
                  'Germany, Sweden, and the Netherlands. In the '
                  'imperfective Turoyo uses SOV word order under '
                  'long-term Kurdish and Turkish contact.'},
        [{
            'slug': 'tru-u-aleymo-qorele',
            'konso': 'ܐܘ ܥܠܝܡܐ ܐܘ ܟܬܘܒܐ ܩܘܪܐ ܠܗ',
            'gloss': 'the-boy  the-book  read.IMPF-3SG.M',
            'translation': 'The boy is reading the book.',
            'tree_bracket': ('[S [NP [Det u-] [N ʿleymo]] '
                             '[NP [Det u-] [N ktowo]] '
                             '[V qorele]]'),
            'notes': 'SOV under Kurdish contact. Prefixed *u-* is the '
                     'masculine definite article (feminine *i-*), '
                     'distinct from the classical Aramaic postposed '
                     '-ā. *qore-le* = verb + enclitic agreement with '
                     'the subject.',
            'source': 'illustrative',
            'citation': 'Jastrow (1993), *Laut- und Formenlehre des '
                        'neuaramäischen Dialekts von Mīdin im Ṭūr '
                        'ʿAbdīn*, §§68, 112.',
        }],
    ),

    (
        {'slug': 'assyrian-neo-aramaic', 'glottocode': 'assy1241',
         'name': 'ܠܫܢܐ ܐܬܘܪܝܐ', 'english_name': 'Assyrian Neo-Aramaic',
         'family': 'afroasiatic', 'family_name': 'Afro-Asiatic',
         'subgroup': 'Semitic (Northwest, Aramaic, Eastern / NENA)',
         'region': 'N. Iraq, NW Iran, SE Turkey and diaspora',
         'iso639_3': 'aii', 'macroarea': 'Eurasia',
         'speakers': 600000, 'word_order': 'svo',
         'script': 'Syriac (Madnḥāyā / Eastern)',
         'extinct': False,
         'latitude': 36.75, 'longitude': 43.0,
         'notes': 'Largest North-Eastern Neo-Aramaic (NENA) language, '
                  'speakers are members of the Assyrian Church of the '
                  'East and the Ancient Church of the East. Standard '
                  'literary register is based on the dialect of '
                  'Urmia.'},
        [{
            'slug': 'aii-ana-bi-akhlin-lakhma',
            'konso': 'ܐܢܐ ܒܝ ܐܟܠܢ ܠܚܡܐ',
            'gloss': 'I  PROG-eat.IMPF.1SG  bread',
            'translation': 'I am eating bread.',
            'tree_bracket': ('[S [NP [Pron ʾana]] '
                             '[VP [V bi-ʾakhlin] [NP [N laxma]]]]'),
            'notes': 'Progressive with the proclitic *bi-* (< *bǝ-* '
                     '"in") plus the imperfective — a widespread '
                     'NENA innovation. Subject pronoun is optional '
                     'but common for topic-marking.',
            'source': 'illustrative',
            'citation': 'Khan (2008), *The Jewish Neo-Aramaic Dialect '
                        'of Urmi*, §§4.8, 4.19 (Christian/Jewish '
                        'Urmi share the construction).',
        }],
    ),

    (
        {'slug': 'chaldean-neo-aramaic', 'glottocode': 'chal1275',
         'name': 'ܟܠܕܝܐ', 'english_name': 'Chaldean Neo-Aramaic',
         'family': 'afroasiatic', 'family_name': 'Afro-Asiatic',
         'subgroup': 'Semitic (Northwest, Aramaic, Eastern / NENA)',
         'region': 'Nineveh Plain (Iraq) and diaspora',
         'iso639_3': 'cld', 'macroarea': 'Eurasia',
         'speakers': 220000, 'word_order': 'svo',
         'script': 'Syriac (Madnḥāyā)',
         'extinct': False,
         'latitude': 37.0972, 'longitude': 43.5027,
         'notes': 'Sister NENA language to Assyrian Neo-Aramaic; '
                  'speakers are members of the Chaldean Catholic '
                  'Church. Varieties cluster around Alqosh and the '
                  'Nineveh Plain villages, with large diaspora in '
                  'Detroit and Sydney.'},
        [{
            'slug': 'cld-ana-baxlen-laxma',
            'konso': 'ܐܢܐ ܒܐܟܠܢ ܠܚܡܐ',
            'gloss': 'I  PROG-eat.IMPF.1SG  bread',
            'translation': 'I am eating bread.',
            'tree_bracket': ('[S [NP [Pron ʾana]] '
                             '[VP [V baxlen] [NP [N laxma]]]]'),
            'notes': 'Same progressive-imperfective construction as '
                     'Assyrian, with a slightly reduced *bi-* → *b-* '
                     'prefix. Lexically closer to the Alqosh '
                     'dialect.',
            'source': 'illustrative',
            'citation': 'Coghill (2003), *The Neo-Aramaic Dialect of '
                        'Alqosh*, §§4.2, 6.1.',
        }],
    ),

    (
        {'slug': 'hulaula', 'glottocode': 'hula1244',
         'name': 'לשן דידן', 'english_name': 'Hulaulá',
         'family': 'afroasiatic', 'family_name': 'Afro-Asiatic',
         'subgroup': 'Semitic (Northwest, Aramaic, Eastern / NENA)',
         'region': 'Iranian Kurdistan (formerly)',
         'iso639_3': 'huy', 'macroarea': 'Eurasia',
         'speakers': 10000, 'word_order': 'sov',
         'script': 'Hebrew (square script)',
         'extinct': False,
         'latitude': 31.9111, 'longitude': 43.4865,
         'notes': 'Jewish Neo-Aramaic — "Lishán Didán" ("our '
                  'language") — of the Jews of Iranian Kurdistan, '
                  'in particular Saqqiz, Sanandaj, and Kerend. Almost '
                  'no speakers remain in the historical region after '
                  'the 1950s emigration to Israel. NENA with strong '
                  'Kurdish influence and SOV order.'},
        [{
            'slug': 'huy-ana-xzeli-xona',
            'konso': 'אנה חזילי חונה',
            'gloss': 'I  see.PRF-1SG  brother',
            'translation': 'I saw a brother.',
            'tree_bracket': ('[S [NP [Pron ana]] '
                             '[NP [N xona]] '
                             '[V xze-li]]'),
            'notes': 'SOV, and the perfective cross-references the '
                     'agent via an L-suffix (-li "by me") on the '
                     'verb — the classic "ergative-like" alignment '
                     'of NENA perfectives, inherited and '
                     'restructured from the participle-plus-*l-* '
                     'construction of Late Aramaic.',
            'source': 'illustrative',
            'citation': 'Khan (2009), *The Jewish Neo-Aramaic Dialect '
                        'of Sanandaj*, §§4.15, 6.2.',
        }],
    ),

    (
        {'slug': 'neo-mandaic', 'glottocode': 'nucl1706',
         'name': 'ࡌࡀࡍࡃࡀࡉࡉࡀ ࡅࡃࡉࡔࡀ',
         'english_name': 'Neo-Mandaic',
         'family': 'afroasiatic', 'family_name': 'Afro-Asiatic',
         'subgroup': 'Semitic (Northwest, Aramaic, Eastern)',
         'region': 'Ahvaz, Khorramshahr (Khuzestan, Iran)',
         'iso639_3': 'mid', 'macroarea': 'Eurasia',
         'speakers': 200, 'word_order': 'sov',
         'script': 'Mandaic / Persian',
         'extinct': False,
         'latitude': 31.3443, 'longitude': 48.8128,
         'notes': 'Critically endangered vernacular descendant of '
                  'Classical Mandaic, spoken by a few hundred '
                  'Mandaeans still in Iran (and emigré communities '
                  'in Australia, the US and Sweden). SOV under '
                  'Persian contact.'},
        [{
            'slug': 'mid-ana-ebra-qam-chazeli',
            'konso': 'ࡀࡍࡀ ࡀࡁࡓࡀ ࡒࡀࡌ ࡇࡆࡋࡉ',
            'gloss': 'I  son  PROG  see.PRF-1SG',
            'translation': 'I saw the son.',
            'tree_bracket': ('[S [NP [Pron ana]] '
                             '[NP [N ebra]] '
                             '[VP [Asp qam] [V ḥzeli]]]'),
            'notes': 'SOV with a pre-verbal aspectual *qam-* ('
                     'cognate with classical *qāʾem*) fronted onto '
                     'the perfective verb. L-suffix -li again cross-'
                     'references the agent — same NENA pattern, '
                     'independently inherited.',
            'source': 'illustrative',
            'citation': 'Häberl (2009), *The Neo-Mandaic Dialect of '
                        'Khorramshahr*, §§4.2.3, 4.4.',
        }],
    ),

    # ═══════════════════════════════════════════════════════════════
    # RELATED — East Semitic (Akkadian)
    # ═══════════════════════════════════════════════════════════════
    (
        {'slug': 'akkadian', 'glottocode': 'akka1240',
         'name': '𒀝𒅗𒁺𒌑',
         'english_name': 'Akkadian',
         'family': 'afroasiatic', 'family_name': 'Afro-Asiatic',
         'subgroup': 'Semitic (East)',
         'region': 'Mesopotamia (Assyria and Babylonia)',
         'iso639_3': 'akk', 'macroarea': 'Eurasia',
         'speakers': 0, 'word_order': 'sov',
         'script': 'Cuneiform (logo-syllabic)',
         'extinct': True,
         'latitude': 33.1, 'longitude': 44.1,
         'notes': 'The only East Semitic language with an extensive '
                  'written record (ca. 2500 BCE–100 CE in '
                  'cuneiform). SOV word order — unusual for Semitic — '
                  'almost certainly under Sumerian contact. Splits '
                  'historically into Assyrian and Babylonian dialects.'},
        [
            {
                'slug': 'akk-sarrum-alam-isbat',
                'konso': '𒈗 𒀀𒉌 𒄑𒁁',
                'gloss': 'king-NOM  city-ACC  seize.PRF.3SG.M',
                'translation': 'The king seized the city.',
                'tree_bracket': ('[S [NP [N šarrum]] '
                                 '[NP [N ālam]] '
                                 '[V iṣbat]]'),
                'notes': 'Textbook Old Babylonian SOV with case '
                         'endings: -um nominative, -am accusative, '
                         '-im genitive (the so-called mimation). '
                         '*iṣbat* = preterite G-stem of ṣ-b-t.',
                'source': 'illustrative',
                'citation': 'Huehnergard (2011), *A Grammar of '
                            'Akkadian*, §§3.1, 14.2.',
            },
            {
                'slug': 'akk-awilum-bitam-ibni',
                'konso': '𒀀𒉿𒈝 𒂍𒀀𒈠 𒅁𒉌',
                'gloss': 'man-NOM  house-ACC  build.PRF.3SG.M',
                'translation': 'The man built a house.',
                'tree_bracket': ('[S [NP [N awīlum]] '
                                 '[NP [N bītam]] '
                                 '[V ibni]]'),
                'notes': 'Another minimal SOV transitive. *ibni* = '
                         'preterite G-stem of the III-weak root '
                         'b-n-y. Root cognate with Hebrew/Aramaic '
                         'bny — one of the clearest pan-Semitic '
                         'roots.',
                'source': 'illustrative',
                'citation': 'Huehnergard (2011), *A Grammar of '
                            'Akkadian*, §22.2.',
            },
        ],
    ),

    # ═══════════════════════════════════════════════════════════════
    # RELATED — South Semitic (Sayhadic + Modern South Arabian)
    # ═══════════════════════════════════════════════════════════════
    (
        {'slug': 'sabaic', 'glottocode': 'saba1279',
         'name': '𐩪𐩨𐩱𐩬',
         'english_name': 'Sabaic',
         'family': 'afroasiatic', 'family_name': 'Afro-Asiatic',
         'subgroup': 'Semitic (South, Sayhadic)',
         'region': 'Saba\' kingdom, highland Yemen',
         'iso639_3': 'xsa', 'macroarea': 'Eurasia',
         'speakers': 0, 'word_order': 'vso',
         'script': 'Ancient South Arabian (musnad)',
         'extinct': True,
         'latitude': 15.42, 'longitude': 45.35,
         'notes': 'Best-attested of the four Sayhadic / "Old South '
                  'Arabian" languages (Sabaic, Minaic, Qatabanic, '
                  'Hadramautic), ca. 1000 BCE–600 CE. Dedicatory and '
                  'monumental genres dominate; the script is '
                  'monumental consonantal, read right-to-left or '
                  'boustrophedon.'},
        [{
            'slug': 'xsa-hqny-almaqh',
            'konso': '𐩠𐩤𐩬𐩺 𐩱𐩡𐩣𐩤𐩠 𐩮𐩡𐩣𐩬',
            'gloss': 'dedicate.CAUS.PRF.3SG.M  Almaqah  statue-DEF',
            'translation': 'He dedicated a statue to Almaqah.',
            'tree_bracket': ('[S [V hqny] '
                             '[NP [N ʾlmqh]] '
                             '[NP [N ṣlmn]]]'),
            'notes': 'The classic Sabaic votive formula — causative '
                     '*h-* prefix on q-n-y "acquire / dedicate", '
                     'recipient deity as first NP, the dedicated '
                     'object (here *ṣlm* "statue" + mimation -n as '
                     'definite article) as second.',
            'source': 'literature',
            'citation': 'CIH 140 and passim (Awām temple, Marib); '
                        'grammar: Stein (2011), "Ancient South '
                        'Arabian", in Weninger ed. *The Semitic '
                        'Languages*.',
        }],
    ),

    (
        {'slug': 'mehri', 'glottocode': 'mehr1241',
         'name': 'مهريّت', 'english_name': 'Mehri',
         'family': 'afroasiatic', 'family_name': 'Afro-Asiatic',
         'subgroup': 'Semitic (South, Modern South Arabian)',
         'region': 'Dhofar (Oman), Mahra (Yemen)',
         'iso639_3': 'gdq', 'macroarea': 'Eurasia',
         'speakers': 180000, 'word_order': 'svo',
         'script': 'Arabic (when written) / Latin (scholarly)',
         'extinct': False,
         'latitude': 16.793, 'longitude': 52.473,
         'notes': 'Most widely spoken of the six Modern South '
                  'Arabian languages (Mehri, Soqotri, Jibbali/Shehri, '
                  'Hobyot, Harsusi, Bathari). Preserves Proto-Semitic '
                  '*ś — distinguishes s/ś/š. No native script; '
                  'literate community writes in Arabic with '
                  'diacritics.'},
        [{
            'slug': 'gdq-ghayg-gharob-habit',
            'konso': 'غيگ غارٶب حَيبيت',
            'gloss': 'man  know.PRF.3SG.M  camel.F',
            'translation': 'The man knows the camel.',
            'tree_bracket': ('[S [NP [N ġayg]] '
                             '[VP [V ġarōb] '
                             '[NP [N ḥaybīt]]]]'),
            'notes': 'Mehri prefers SVO with topicalised subjects; '
                     'definiteness is not morphologically marked on '
                     'nouns (no article). *ḥaybīt* is the feminine '
                     'singulative of *ḥbr* / *ḥāybān* "camels".',
            'source': 'illustrative',
            'citation': 'Watson (2012), *The Structure of Mehri*, '
                        '§§3.1, 5.1.',
        }],
    ),

    # ═══════════════════════════════════════════════════════════════
    # RELATED — Central Semitic (Arabic descendant in Europe)
    # ═══════════════════════════════════════════════════════════════
    (
        {'slug': 'maltese', 'glottocode': 'malt1254',
         'name': 'Malti', 'english_name': 'Maltese',
         'family': 'afroasiatic', 'family_name': 'Afro-Asiatic',
         'subgroup': 'Semitic (Central, Arabic)',
         'region': 'Malta', 'iso639_3': 'mlt', 'macroarea': 'Eurasia',
         'speakers': 520000, 'word_order': 'svo',
         'script': 'Latin (with ċ, ġ, ħ, ż)',
         'extinct': False,
         'latitude': 35.8884, 'longitude': 14.4508,
         'notes': 'The only Semitic language written in the Latin '
                  'alphabet and the only Semitic language that is an '
                  'official EU language. Descended from Siculo-Arabic '
                  '(the Arabic of Sicily) with heavy Sicilian / '
                  'Italian / English adstrate — half the lexicon is '
                  'Romance. Semitic morphology largely intact.'},
        [{
            'slug': 'mlt-it-tifel-jaqra-ktieb',
            'konso': 'It-tifel jaqra ktieb',
            'gloss': 'the-boy  read.IMPF.3SG.M  book',
            'translation': 'The boy is reading a book.',
            'tree_bracket': ('[S [NP [Det It-] [N tifel]] '
                             '[VP [V jaqra] [NP [N ktieb]]]]'),
            'notes': 'Prefixed *il-* (→ *it-* by sun-letter '
                     'assimilation before *t*) continues the Arabic '
                     'definite article *al-*. Imperfective prefix '
                     '*j-* (Standard Arabic *y-*) marks 3SG.M, the '
                     'template *jaqra* from the root q-r-ʾ "read".',
            'source': 'illustrative',
            'citation': 'Borg & Azzopardi-Alexander (1997), *Maltese*, '
                        '§§3.1, 5.1.',
        }],
    ),
]


class Command(BaseCommand):
    help = ('Seed Muka with finer-resolution Northwest Semitic coverage '
            '(Canaanite, Ugaritic, Aramaic ancient & modern) plus '
            'Akkadian, Sabaic, Mehri, and Maltese.')

    def handle(self, *args, **options):
        made_lang = updated_lang = 0
        made_sent = updated_sent = 0
        bad_trees = 0

        with transaction.atomic():
            for lang_fields, sentences in SEEDS:
                slug = lang_fields['slug']
                defaults = {k: v for k, v in lang_fields.items()
                            if k != 'slug'}
                lang, created = Language.objects.update_or_create(
                    slug=slug, defaults=defaults)
                if created:
                    made_lang += 1
                else:
                    updated_lang += 1
                self.stdout.write(
                    f'{"+" if created else "~"} {slug:34} '
                    f'{lang.english_name}')

                for row in sentences:
                    try:
                        parse_bracket(row['tree_bracket'])
                    except Exception as e:
                        bad_trees += 1
                        self.stderr.write(self.style.ERROR(
                            f'  ! {row["slug"]}: bad tree ({e})'))
                        continue
                    s_defaults = {**{k: v for k, v in row.items()
                                     if k != 'slug'},
                                  'language': lang}
                    _, was_new = Sentence.objects.update_or_create(
                        slug=row['slug'], defaults=s_defaults)
                    if was_new:
                        made_sent += 1
                    else:
                        updated_sent += 1

        self.stdout.write(self.style.SUCCESS(
            f'Languages: +{made_lang} new, ~{updated_lang} updated. '
            f'Sentences: +{made_sent} new, ~{updated_sent} updated, '
            f'{bad_trees} bad trees.'))
