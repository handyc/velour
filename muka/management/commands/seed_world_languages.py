"""Seed world-languages coverage beyond Africa.

17 languages hand-picked by the user — Sanskrit, Ancient Hebrew,
Dutch, Mandarin, Cantonese, Latin, Ancient Greek, Imperial Aramaic,
Hittite, Pali, Classical Tibetan, Vietnamese, German, Spanish, French,
Japanese, and Ancient Egyptian — each with one illustrative tree.

Every sentence is ``illustrative`` (author-composed to show a
typologically notable feature using documented morphology); a reader
with the standard grammar in hand should upgrade the ``source`` field
to ``literature`` with a proper citation.

Run:      venv/bin/python manage.py seed_world_languages
Reset:    (don't — this is additive; use --reset on seed_african only)
"""

from django.core.management.base import BaseCommand
from django.db import transaction

from muka.models import Language, Sentence
from muka.tree import parse_bracket


SEEDS = [

    # ═══════════════════════════════════════════════════════════════
    # INDO-EUROPEAN — Indo-Aryan (classical)
    # ═══════════════════════════════════════════════════════════════
    (
        {'slug': 'sanskrit', 'glottocode': 'sans1269',
         'name': 'संस्कृतम्', 'english_name': 'Sanskrit',
         'family': 'indo-european', 'family_name': 'Indo-European',
         'subgroup': 'Indo-Aryan (Old Indo-Aryan)',
         'region': 'Classical India', 'iso639_3': 'san',
         'macroarea': 'Eurasia', 'speakers': 25000,
         'word_order': 'sov', 'script': 'Devanāgarī',
         'extinct': True,
         'notes': 'Classical SOV (free in verse); eight nominal cases; '
                  'sandhi rules fuse word boundaries. Panini\'s Aṣṭādhyāyī '
                  '(~500 BCE) is among the world\'s oldest formal grammars.'},
        [{
            'slug': 'san-naro-gham-agacchat',
            'konso': 'नरो गृहम् अगच्छत्',
            'gloss': 'man.NOM.SG  house.ACC.SG  go.IMPF.3SG',
            'translation': 'The man went to the house.',
            'tree_bracket': ('[S [NP [N naro]] '
                             '[VP [NP [N gṛham]] [V agacchat]]]'),
            'notes': 'SOV canonical order. Sandhi turns /naraḥ gṛham/ '
                     'into /naro gṛham/ (visarga → o before voiced). '
                     'Imperfect augment a- marks past.',
            'source': 'illustrative',
            'citation': 'Whitney (1889), *Sanskrit Grammar*, §§776–785.',
        }],
    ),

    (
        {'slug': 'pali', 'glottocode': 'pali1273',
         'name': 'पाऴि', 'english_name': 'Pali',
         'family': 'indo-european', 'family_name': 'Indo-European',
         'subgroup': 'Indo-Aryan (Middle Indo-Aryan, Prakrit)',
         'region': 'Theravada Buddhist canon',
         'iso639_3': 'pli', 'macroarea': 'Eurasia',
         'speakers': 0, 'word_order': 'sov',
         'script': 'Devanāgarī / Sinhala / Thai / Burmese (liturgical)',
         'extinct': True,
         'notes': 'Liturgical language of Theravada Buddhism; written '
                  'in whatever script the local Sangha uses. SOV with '
                  'simplified Sanskrit morphology (no retroflex clusters, '
                  'reduced case syncretism).'},
        [{
            'slug': 'pli-puriso-gaham-gacchati',
            'konso': 'puriso gahaṃ gacchati',
            'gloss': 'man.NOM.SG  house.ACC.SG  go.PRES.3SG',
            'translation': 'The man goes to the house.',
            'tree_bracket': ('[S [NP [N puriso]] '
                             '[VP [NP [N gahaṃ]] [V gacchati]]]'),
            'notes': 'Pali *puriso* ← Skt. *puruṣaḥ*; *gahaṃ* ← *gṛham*. '
                     'Cluster simplification and vowel lowering typical '
                     'of Middle Indo-Aryan.',
            'source': 'illustrative',
            'citation': 'Warder (1963), *Introduction to Pali*.',
        }],
    ),

    # ═══════════════════════════════════════════════════════════════
    # INDO-EUROPEAN — Italic / Hellenic / Anatolian
    # ═══════════════════════════════════════════════════════════════
    (
        {'slug': 'latin', 'glottocode': 'lati1261',
         'name': 'Lingua Latīna', 'english_name': 'Latin',
         'family': 'indo-european', 'family_name': 'Indo-European',
         'subgroup': 'Italic (Latino-Faliscan)',
         'region': 'Roman Empire', 'iso639_3': 'lat',
         'macroarea': 'Eurasia', 'speakers': 0,
         'word_order': 'sov', 'script': 'Latin',
         'extinct': True,
         'notes': 'Classical Latin is SOV-dominant but word order is '
                  'pragmatically free because case endings carry '
                  'grammatical role. Six cases (nom acc gen dat abl voc).'},
        [{
            'slug': 'lat-vir-domum-aedificavit',
            'konso': 'vir domum aedificāvit',
            'gloss': 'man.NOM.SG  house.ACC.SG  build.PRF.3SG',
            'translation': 'The man built a/the house.',
            'tree_bracket': ('[S [NP [N vir]] '
                             '[VP [NP [N domum]] [V aedificāvit]]]'),
            'notes': 'SOV baseline. Perfect -āvit = 3SG active perfect '
                     'indicative. No articles — definiteness is context.',
            'source': 'illustrative',
            'citation': 'Allen & Greenough (1903), *New Latin Grammar*.',
        }],
    ),

    (
        {'slug': 'ancient-greek', 'glottocode': 'anci1242',
         'name': 'Ἀρχαία Ἑλληνική', 'english_name': 'Ancient Greek',
         'family': 'indo-european', 'family_name': 'Indo-European',
         'subgroup': 'Hellenic (Ionic-Attic)',
         'region': 'Classical Greece', 'iso639_3': 'grc',
         'macroarea': 'Eurasia', 'speakers': 0,
         'word_order': 'free', 'script': 'Greek',
         'extinct': True,
         'notes': 'Ionic-Attic as codified in classical Athens. Free '
                  'word order via five cases (nom gen dat acc voc), '
                  'three numbers (sg/dual/pl), rich participial syntax. '
                  'Definite article ὁ ἡ τό.'},
        [{
            'slug': 'grc-ho-anthrop-oikon-oikodom',
            'konso': 'ὁ ἄνθρωπος οἶκον ᾠκοδόμησεν',
            'gloss': 'the.NOM.M.SG  man.NOM.SG  house.ACC.SG  build.AOR.3SG',
            'translation': 'The man built a house.',
            'tree_bracket': ('[S [NP [Det ὁ] [N ἄνθρωπος]] '
                             '[VP [NP [N οἶκον]] [V ᾠκοδόμησεν]]]'),
            'notes': 'Aorist ᾠκοδόμησεν carries temporal augment (the '
                     'initial ᾠ- is /ōi-/, the augmented ο- + ι-stem). '
                     'SOV is one of several possible orders; topic-focus '
                     'rearranges freely.',
            'source': 'illustrative',
            'citation': 'Smyth (1920), *Greek Grammar*.',
        }],
    ),

    (
        {'slug': 'hittite', 'glottocode': 'hitt1242',
         'name': 'Nešili', 'english_name': 'Hittite',
         'family': 'indo-european', 'family_name': 'Indo-European',
         'subgroup': 'Anatolian',
         'region': 'Bronze-Age Anatolia (Ḫattuša)',
         'iso639_3': 'hit', 'macroarea': 'Eurasia',
         'speakers': 0, 'word_order': 'sov',
         'script': 'Cuneiform',
         'extinct': True,
         'notes': 'Oldest attested Indo-European language (c. 1650–1200 '
                  'BCE). Strict SOV, no grammatical gender (only '
                  'animate/neuter), clitic chains follow the first word.'},
        [{
            'slug': 'hit-antuhsas-par-saniskit',
            'konso': 'antuḫšaš parnaš šanḫiškit',
            'gloss': 'man.NOM.SG  house.ACC.SG  build.IMPF.3SG',
            'translation': 'The man was building the house.',
            'tree_bracket': ('[S [NP [N antuḫšaš]] '
                             '[VP [NP [N parnaš]] [V šanḫiškit]]]'),
            'notes': 'SOV Anatolian baseline; imperfective -ške-. '
                     'Transliteration uses the standard Hittitological '
                     'conventions for cuneiform.',
            'source': 'illustrative',
            'citation': 'Hoffner & Melchert (2008), *A Grammar of the '
                        'Hittite Language*.',
        }],
    ),

    # ═══════════════════════════════════════════════════════════════
    # INDO-EUROPEAN — Germanic
    # ═══════════════════════════════════════════════════════════════
    (
        {'slug': 'dutch', 'glottocode': 'dutc1256',
         'name': 'Nederlands', 'english_name': 'Dutch',
         'family': 'indo-european', 'family_name': 'Indo-European',
         'subgroup': 'Germanic (West)',
         'region': 'Netherlands, Belgium (Flanders), Suriname',
         'iso639_3': 'nld', 'macroarea': 'Eurasia',
         'speakers': 24000000, 'word_order': 'mixed',
         'script': 'Latin',
         'notes': 'V2 in main clauses; verb-final in subordinate — the '
                  'classic Germanic brace. Auxiliary + past participle '
                  'flanks the object. Three genders collapsed to two '
                  'in Standard Dutch (de/het).'},
        [{
            'slug': 'nld-de-man-heeft-een-huis-gebouwd',
            'konso': 'de man heeft een huis gebouwd',
            'gloss': 'the  man  have.3SG  a  house  build.PTCP',
            'translation': 'The man has built a house.',
            'tree_bracket': ('[S [NP [Det de] [N man]] '
                             '[VP [Aux heeft] '
                             '[NP [Det een] [N huis]] '
                             '[V gebouwd]]]'),
            'notes': 'Aux *heeft* in V2, participle *gebouwd* clause-final. '
                     'Object *een huis* sits inside the brace.',
            'source': 'illustrative',
            'citation': 'Donaldson (2008), *Dutch: A Comprehensive Grammar*.',
        }],
    ),

    (
        {'slug': 'german', 'glottocode': 'stan1295',
         'name': 'Deutsch', 'english_name': 'German',
         'family': 'indo-european', 'family_name': 'Indo-European',
         'subgroup': 'Germanic (West, High German)',
         'region': 'Germany, Austria, Switzerland, Liechtenstein',
         'iso639_3': 'deu', 'macroarea': 'Eurasia',
         'speakers': 95000000, 'word_order': 'mixed',
         'script': 'Latin',
         'notes': 'V2 main / verb-final subordinate (same brace as '
                  'Dutch). Four cases, three genders retained. Articles '
                  'decline fully.'},
        [{
            'slug': 'deu-der-mann-hat-ein-haus-gebaut',
            'konso': 'der Mann hat ein Haus gebaut',
            'gloss': 'the.NOM  man  have.3SG  a.ACC  house  build.PTCP',
            'translation': 'The man has built a house.',
            'tree_bracket': ('[S [NP [Det der] [N Mann]] '
                             '[VP [Aux hat] '
                             '[NP [Det ein] [N Haus]] '
                             '[V gebaut]]]'),
            'notes': 'V2 brace: Aux *hat* in second position, participle '
                     '*gebaut* clause-final. Nominative *der Mann* / '
                     'accusative *ein Haus* disambiguated by case on '
                     'the determiner.',
            'source': 'illustrative',
            'citation': 'Durrell (2011), *Hammer\'s German Grammar*.',
        }],
    ),

    # ═══════════════════════════════════════════════════════════════
    # INDO-EUROPEAN — Romance
    # ═══════════════════════════════════════════════════════════════
    (
        {'slug': 'spanish', 'glottocode': 'stan1288',
         'name': 'Español', 'english_name': 'Spanish',
         'family': 'indo-european', 'family_name': 'Indo-European',
         'subgroup': 'Romance (Ibero-Romance)',
         'region': 'Spain, Latin America, Equatorial Guinea',
         'iso639_3': 'spa', 'macroarea': 'Eurasia',
         'speakers': 500000000, 'word_order': 'svo',
         'script': 'Latin',
         'notes': 'SVO default, free word order possible. Pro-drop '
                  '(subject pronouns usually omitted). Differential object '
                  'marking with animate *a*.'},
        [{
            'slug': 'spa-el-hombre-construyo-una-casa',
            'konso': 'el hombre construyó una casa',
            'gloss': 'the  man  build.PRET.3SG  a  house',
            'translation': 'The man built a house.',
            'tree_bracket': ('[S [NP [Det el] [N hombre]] '
                             '[VP [V construyó] '
                             '[NP [Det una] [N casa]]]]'),
            'notes': 'Preterite *construyó* (-ó, stressed). No pro-drop '
                     'here because we name the subject; in narrative '
                     'contexts *construyó una casa* alone would suffice.',
            'source': 'illustrative',
            'citation': 'Butt & Benjamin (2011), *A New Reference '
                        'Grammar of Modern Spanish*.',
        }],
    ),

    (
        {'slug': 'french', 'glottocode': 'stan1290',
         'name': 'Français', 'english_name': 'French',
         'family': 'indo-european', 'family_name': 'Indo-European',
         'subgroup': 'Romance (Gallo-Romance)',
         'region': 'France, Canada (Québec), Belgium, Switzerland, '
                   'West/Central Africa',
         'iso639_3': 'fra', 'macroarea': 'Eurasia',
         'speakers': 300000000, 'word_order': 'svo',
         'script': 'Latin',
         'notes': 'SVO. Passé composé = aux *avoir*/*être* + past '
                  'participle; orthography preserves Latin etymology '
                  'more than pronunciation warrants.'},
        [{
            'slug': 'fra-lhomme-a-construit-une-maison',
            'konso': "l'homme a construit une maison",
            'gloss': 'the-man  have.3SG  build.PTCP  a  house',
            'translation': 'The man built / has built a house.',
            'tree_bracket': ('[S [NP [Det l\u2019] [N homme]] '
                             '[VP [Aux a] [V construit] '
                             '[NP [Det une] [N maison]]]]'),
            'notes': 'Passé composé is the normal past in speech — '
                     'simple past (*passé simple*) survives in '
                     'literature. Aux + participle + object.',
            'source': 'illustrative',
            'citation': 'Grevisse & Goosse (2016), *Le Bon Usage*.',
        }],
    ),

    # ═══════════════════════════════════════════════════════════════
    # AFROASIATIC — Semitic (non-African, classical)
    # ═══════════════════════════════════════════════════════════════
    (
        {'slug': 'ancient-hebrew', 'glottocode': 'anci1244',
         'name': 'עִבְרִית מִקְרָאִית', 'english_name': 'Ancient Hebrew',
         'family': 'afroasiatic', 'family_name': 'Afro-Asiatic',
         'subgroup': 'Semitic (Northwest, Canaanite)',
         'region': 'Ancient Israel/Judah, Hebrew Bible',
         'iso639_3': 'hbo', 'macroarea': 'Eurasia',
         'speakers': 0, 'word_order': 'vso',
         'script': 'Hebrew (square script)',
         'extinct': True,
         'notes': 'Biblical / Classical Hebrew is VSO in narrative '
                  'prose (waw-consecutive) and SVO in direct speech. '
                  'Construct state for genitives, definite article ha-.'},
        [{
            'slug': 'hbo-bana-haish-bayit',
            'konso': 'בָּנָה הָאִישׁ בַּיִת',
            'gloss': 'build.PRF.3SG.M  the-man  house',
            'translation': 'The man built a house.',
            'tree_bracket': ('[S [V bānâ] '
                             '[NP [Det hā-] [N \u2019îš]] '
                             '[NP [N bayit]]]'),
            'notes': 'VSO narrative order. *bānâ* is qal perfect 3SG.M. '
                     '*hā-* = definite article assimilating before '
                     '\u2019āleph. Transliteration follows SBL style.',
            'source': 'illustrative',
            'citation': 'Joüon & Muraoka (2006), *A Grammar of Biblical '
                        'Hebrew*.',
        }],
    ),

    (
        {'slug': 'imperial-aramaic', 'glottocode': 'impe1235',
         'name': 'ארמית', 'english_name': 'Imperial Aramaic',
         'family': 'afroasiatic', 'family_name': 'Afro-Asiatic',
         'subgroup': 'Semitic (Northwest, Aramaic)',
         'region': 'Achaemenid Empire (700–300 BCE)',
         'iso639_3': 'arc', 'macroarea': 'Eurasia',
         'speakers': 0, 'word_order': 'svo',
         'script': 'Aramaic / Imperial Aramaic',
         'extinct': True,
         'notes': 'Lingua franca of the Achaemenid Empire and the '
                  'parent of later Jewish Aramaic, Syriac, Mandaic. '
                  'Post-posed definite article -ā (emphatic state).'},
        [{
            'slug': 'arc-gabra-bena-bayta',
            'konso': 'גַּבְרָא בְּנָא בַּיְתָא',
            'gloss': 'man-DEF  build.PRF.3SG.M  house-DEF',
            'translation': 'The man built the house.',
            'tree_bracket': ('[S [NP [N gabrā]] '
                             '[VP [V benā] [NP [N baytā]]]]'),
            'notes': 'Emphatic -ā on both nouns = the post-posed '
                     'definite article (unlike Hebrew\'s prefixed ha-). '
                     'SVO is the typical Imperial Aramaic order.',
            'source': 'illustrative',
            'citation': 'Folmer (1995), *The Aramaic Language in the '
                        'Achaemenid Period*.',
        }],
    ),

    # ═══════════════════════════════════════════════════════════════
    # AFROASIATIC — Ancient Egyptian
    # ═══════════════════════════════════════════════════════════════
    (
        {'slug': 'ancient-egyptian', 'glottocode': 'egyp1246',
         'name': 'r n Kmt', 'english_name': 'Ancient Egyptian',
         'family': 'afroasiatic', 'family_name': 'Afro-Asiatic',
         'subgroup': 'Egyptian',
         'region': 'Ancient Egypt (3000 BCE – 400 CE)',
         'iso639_3': 'egy', 'macroarea': 'Africa',
         'speakers': 0, 'word_order': 'vso',
         'script': 'Hieroglyphs (also Hieratic, Demotic, Coptic)',
         'extinct': True,
         'notes': 'Strict VSO in the sḏm.f and sḏm.n.f forms. Hieroglyphs '
                  'write consonants only (plus ideograms and determinatives); '
                  'vowels are reconstructed from Coptic. Transliteration '
                  'uses standard Egyptological conventions.'},
        [{
            'slug': 'egy-qd-z-pr',
            'konso': 'qd z pr',
            'gloss': 'build.PRF  man  house',
            'translation': 'The man built a house.',
            'tree_bracket': ('[S [V qd] [NP [N z]] [NP [N pr]]]'),
            'notes': 'VSO, hallmark Egyptian order. *qd* = "to build", '
                     '*z* (𓊃) = "man", *pr* (𓉐) = "house". Hieroglyphic '
                     'determinatives (not shown in transliteration) would '
                     'disambiguate these consonant skeletons in writing.',
            'source': 'illustrative',
            'citation': 'Allen (2010), *Middle Egyptian*, 3rd ed.',
        }],
    ),

    # ═══════════════════════════════════════════════════════════════
    # SINO-TIBETAN
    # ═══════════════════════════════════════════════════════════════
    (
        {'slug': 'mandarin', 'glottocode': 'mand1415',
         'name': '普通话', 'english_name': 'Mandarin Chinese',
         'family': 'sino-tibetan', 'family_name': 'Sino-Tibetan',
         'subgroup': 'Sinitic',
         'region': 'China, Taiwan, Singapore',
         'iso639_3': 'cmn', 'macroarea': 'Eurasia',
         'speakers': 920000000, 'word_order': 'svo',
         'script': 'Chinese (Hanzi) — simplified / traditional',
         'notes': 'SVO isolating. Aspect markers 了 le (perfective), '
                  '過 guo (experiential), 著 zhe (durative). Classifiers '
                  'obligatory between numeral and noun.'},
        [{
            'slug': 'cmn-nanren-gai-le-fangzi',
            'konso': '男人盖了房子',
            'gloss': 'man  build  PFV  house',
            'translation': 'The man built a house.',
            'tree_bracket': ('[S [NP [N 男人]] '
                             '[VP [V 盖] [Asp 了] [NP [N 房子]]]]'),
            'notes': 'Postverbal 了 = perfective aspect, not past tense. '
                     '*盖 gài* is the standard verb for "build (a house)".',
            'source': 'illustrative',
            'citation': 'Li & Thompson (1981), *Mandarin Chinese: A '
                        'Functional Reference Grammar*.',
        }],
    ),

    (
        {'slug': 'cantonese', 'glottocode': 'yuec1235',
         'name': '粵語', 'english_name': 'Cantonese',
         'family': 'sino-tibetan', 'family_name': 'Sino-Tibetan',
         'subgroup': 'Sinitic (Yue)',
         'region': 'Hong Kong, Macao, Guangdong, diaspora',
         'iso639_3': 'yue', 'macroarea': 'Eurasia',
         'speakers': 85000000, 'word_order': 'svo',
         'script': 'Chinese (traditional Hanzi, incl. Cantonese-specific)',
         'notes': 'Six lexical tones (vs. Mandarin\'s four). Shares SVO '
                  'isolating morphology with Mandarin but distinct '
                  'aspect particles (咗 zo2 perfective, 緊 gan2 progressive) '
                  'and different core vocabulary.'},
        [{
            'slug': 'yue-naam-jan-zou-zo-gaan-uk',
            'konso': '男人造咗間屋',
            'gloss': 'man  build  PFV  CL  house',
            'translation': 'The man built a house.',
            'tree_bracket': ('[S [NP [N 男人]] '
                             '[VP [V 造] [Asp 咗] '
                             '[NP [Cl 間] [N 屋]]]]'),
            'notes': 'Perfective 咗 zo2 (Mandarin 了 le). Classifier '
                     '間 gaan1 is obligatory before 屋 uk1 "house". '
                     'Glottolog labels this entry "Yue Chinese".',
            'source': 'illustrative',
            'citation': 'Matthews & Yip (2011), *Cantonese: A '
                        'Comprehensive Grammar*.',
        }],
    ),

    (
        {'slug': 'classical-tibetan', 'glottocode': 'clas1254',
         'name': 'བོད་སྐད་', 'english_name': 'Classical Tibetan',
         'family': 'sino-tibetan', 'family_name': 'Sino-Tibetan',
         'subgroup': 'Tibetic (Old Tibetan, classical)',
         'region': 'Tibetan Plateau (literary language)',
         'iso639_3': 'xct', 'macroarea': 'Eurasia',
         'speakers': 0, 'word_order': 'sov',
         'script': 'Tibetan (dbu-can)',
         'extinct': True,
         'notes': 'SOV with ergative-absolutive alignment (agent marked '
                  '-s/-gis). Classical written form has been stable for '
                  '1300 years while spoken dialects have diverged.'},
        [{
            'slug': 'xct-mi-yis-khang-pa-brtsigs',
            'konso': 'མིས་ཁང་པ་བརྩིགས།',
            'gloss': 'man-ERG  house  build.PST',
            'translation': 'The man built a house.',
            'tree_bracket': ('[S [NP [N mi] [Case -s]] '
                             '[VP [NP [N khang-pa]] [V brtsigs]]]'),
            'notes': 'Ergative marker -s on *mi* "man"; absolutive '
                     '(zero) on the object *khang-pa* "house". Past '
                     'stem *brtsigs* of *rtsig-pa* "to build".',
            'source': 'illustrative',
            'citation': 'Hahn (1996), *Lehrbuch der klassischen '
                        'tibetischen Schriftsprache*.',
        }],
    ),

    # ═══════════════════════════════════════════════════════════════
    # JAPONIC
    # ═══════════════════════════════════════════════════════════════
    (
        {'slug': 'japanese', 'glottocode': 'nucl1643',
         'name': '日本語', 'english_name': 'Japanese',
         'family': 'japonic', 'family_name': 'Japonic',
         'subgroup': 'Japanese (Tokyo standard)',
         'region': 'Japan', 'iso639_3': 'jpn',
         'macroarea': 'Eurasia', 'speakers': 125000000,
         'word_order': 'sov',
         'script': 'Kanji + Hiragana + Katakana',
         'notes': 'Strict SOV; topic particle は wa, subject が ga, '
                  'object を o. Head-final throughout: postpositions, '
                  'relative clauses precede head noun.'},
        [{
            'slug': 'jpn-otoko-wa-ie-o-tateta',
            'konso': '男は家を建てた',
            'gloss': 'man  TOP  house  ACC  build.PST',
            'translation': 'The man built a house.',
            'tree_bracket': ('[S [NP [N 男] [Top は]] '
                             '[VP [NP [N 家] [Case を]] [V 建てた]]]'),
            'notes': 'は marks topic, を marks object, verb final. '
                     '建てた = past of 建てる "to build (a building)".',
            'source': 'illustrative',
            'citation': 'Kuno (1973), *The Structure of the Japanese '
                        'Language*.',
        }],
    ),

    # ═══════════════════════════════════════════════════════════════
    # AUSTROASIATIC
    # ═══════════════════════════════════════════════════════════════
    (
        {'slug': 'vietnamese', 'glottocode': 'viet1252',
         'name': 'Tiếng Việt', 'english_name': 'Vietnamese',
         'family': 'austroasiatic', 'family_name': 'Austroasiatic',
         'subgroup': 'Vietic',
         'region': 'Vietnam, diaspora',
         'iso639_3': 'vie', 'macroarea': 'Eurasia',
         'speakers': 85000000, 'word_order': 'svo',
         'script': 'Latin (Chữ Quốc Ngữ, with diacritics)',
         'notes': 'SVO isolating, six tones (northern) / five (southern). '
                  'Aspect particles đã (past), đang (progressive), sẽ '
                  '(future). Classifiers obligatory before common nouns.'},
        [{
            'slug': 'vie-nguoi-dan-ong-da-xay-mot-ngoi-nha',
            'konso': 'người đàn ông đã xây một ngôi nhà',
            'gloss': 'person  male  PST  build  one  CL  house',
            'translation': 'The man built a house.',
            'tree_bracket': ('[S [NP [N người] [N đàn] [N ông]] '
                             '[VP [T đã] [V xây] '
                             '[NP [Num một] [Cl ngôi] [N nhà]]]]'),
            'notes': 'Preverbal đã marks past/perfective. Classifier '
                     'ngôi is specific to buildings and tomb-like '
                     'constructions.',
            'source': 'illustrative',
            'citation': 'Thompson (1987), *A Vietnamese Reference '
                        'Grammar*.',
        }],
    ),
]


class Command(BaseCommand):
    help = ('Seed 17 world languages (Sanskrit, Hebrew, Dutch, Mandarin, '
            'Cantonese, Latin, Ancient Greek, Aramaic, Hittite, Pali, '
            'Classical Tibetan, Vietnamese, German, Spanish, French, '
            'Japanese, Ancient Egyptian) with one illustrative tree each. '
            'Additive — safe to re-run.')

    def handle(self, *args, **opts):
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

        self.stdout.write(self.style.SUCCESS(
            f'Languages: +{made_lang} new, ~{updated_lang} updated. '
            f'Sentences: +{made_sent} new, ~{updated_sent} updated, '
            f'{bad_trees} bad trees.'))
