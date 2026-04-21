"""Seed world-language expansion — closing the biggest coverage gaps.

Adds ~55 languages spread across:

* the user's explicit list: Polish, Italian, Modern Greek, Russian,
  Ukrainian, Latvian, Estonian, Portuguese, Hindi;
* remaining top-20-by-speakers globals: English, Bengali, Urdu,
  Persian, Turkish, Korean, Tamil, Telugu, Marathi, Javanese, Thai,
  Burmese, Tagalog, Indonesian;
* major European gaps: Czech, Hungarian, Finnish, Swedish, Norwegian,
  Danish, Romanian, Serbo-Croatian, Bulgarian, Lithuanian, Icelandic,
  Irish, Welsh, Basque, Catalan, Albanian, Georgian, Armenian;
* family-opener sentinels — one sentence each unlocks a whole family
  tree: Nahuatl (Uto-Aztecan), Quechua (Quechuan), Kʼicheʼ (Mayan),
  Navajo (Na-Dene), Cherokee (Iroquoian), Ojibwe (Algic), Kalaallisut
  (Eskimo-Aleut), Warlpiri (Pama-Nyungan), Hawaiian + Māori + Tagalog
  + Indonesian + Javanese (Austronesian), Tok Pisin (Papua bridge);
* sign language: ASL;
* constructed: Esperanto, Toki Pona.

Every sentence is ``illustrative`` — author-composed from published
grammars to demonstrate basic constituent order. Verify against the
cited grammar before quoting, and upgrade ``source='literature'``
with page references once checked.

Trees use the ``surface|romanization`` leaf-token convention for
non-Latin scripts so the SVG renderer draws a second transliteration
line beneath each glyph.

Run:      venv/bin/python manage.py seed_world_expansion
Re-run:   safe — update_or_create on slugs.
"""

from django.core.management.base import BaseCommand
from django.db import transaction

from muka.models import Language, Sentence
from muka.tree import parse_bracket


SEEDS = [

    # ═══════════════════════════════════════════════════════════════
    # INDO-EUROPEAN — Germanic (close the English/Nordic gap)
    # ═══════════════════════════════════════════════════════════════
    (
        {'slug': 'english', 'name': 'English', 'english_name': 'English',
         'family': 'indo-european', 'family_name': 'Indo-European',
         'subgroup': 'Germanic (West)',
         'region': 'UK, USA, global', 'macroarea': 'Eurasia',
         'iso639_3': 'eng', 'glottocode': 'stan1293',
         'speakers': 1500000000, 'word_order': 'svo', 'script': 'Latin',
         'notes': 'Analytic SVO with residual V2 in auxiliaries. '
                  'Do-support in questions + negatives is idiosyncratic '
                  'among Germanic languages.'},
        [{
            'slug': 'eng-the-man-built-a-house',
            'konso': 'the man built a house',
            'gloss': 'DEF  man  build.PST  INDEF  house',
            'translation': 'The man built a house.',
            'tree_bracket': ('[S [NP [Det the] [N man]] '
                             '[VP [V built] [NP [Det a] [N house]]]]'),
            'notes': 'Plain transitive SVO, definite subject + '
                     'indefinite object.',
            'source': 'illustrative',
            'citation': 'Huddleston & Pullum (2002), CGEL §4.',
        }],
    ),
    (
        {'slug': 'swedish', 'name': 'Svenska', 'english_name': 'Swedish',
         'family': 'indo-european', 'family_name': 'Indo-European',
         'subgroup': 'Germanic (North)',
         'region': 'Sweden, Finland', 'macroarea': 'Eurasia',
         'iso639_3': 'swe', 'glottocode': 'swed1254',
         'speakers': 10000000, 'word_order': 'svo', 'script': 'Latin',
         'notes': 'V2; post-posed definite article (-en / -et); '
                  'two grammatical genders (common / neuter).'},
        [{
            'slug': 'swe-mannen-byggde-ett-hus',
            'konso': 'mannen byggde ett hus',
            'gloss': 'man.DEF  build.PST  INDEF.NEUT  house',
            'translation': 'The man built a house.',
            'tree_bracket': ('[S [NP [N mannen]] '
                             '[VP [V byggde] [NP [Det ett] [N hus]]]]'),
            'notes': 'Definite -en is a suffix, not an article.',
            'source': 'illustrative',
            'citation': 'Holmes & Hinchliffe (2013), *Swedish: A '
                        'Comprehensive Grammar*.',
        }],
    ),
    (
        {'slug': 'norwegian', 'name': 'Norsk (bokmål)',
         'english_name': 'Norwegian (Bokmål)',
         'family': 'indo-european', 'family_name': 'Indo-European',
         'subgroup': 'Germanic (North)',
         'region': 'Norway', 'macroarea': 'Eurasia',
         'iso639_3': 'nob', 'glottocode': 'norw1259',
         'speakers': 5000000, 'word_order': 'svo', 'script': 'Latin',
         'notes': 'V2; Bokmål is one of two official written standards '
                  '(the other is Nynorsk, glottocode norw1262).'},
        [{
            'slug': 'nor-mannen-bygde-et-hus',
            'konso': 'mannen bygde et hus',
            'gloss': 'man.DEF  build.PST  INDEF.NEUT  house',
            'translation': 'The man built a house.',
            'tree_bracket': ('[S [NP [N mannen]] '
                             '[VP [V bygde] [NP [Det et] [N hus]]]]'),
            'notes': 'Mutually intelligible with Swedish + Danish.',
            'source': 'illustrative',
            'citation': 'Faarlund et al. (1997), *Norsk '
                        'referansegrammatikk*.',
        }],
    ),
    (
        {'slug': 'danish', 'name': 'Dansk', 'english_name': 'Danish',
         'family': 'indo-european', 'family_name': 'Indo-European',
         'subgroup': 'Germanic (North)',
         'region': 'Denmark', 'macroarea': 'Eurasia',
         'iso639_3': 'dan', 'glottocode': 'dani1285',
         'speakers': 6000000, 'word_order': 'svo', 'script': 'Latin',
         'notes': 'V2; stød (a phonation contrast) distinguishes '
                  'minimal pairs; extensive vowel reduction.'},
        [{
            'slug': 'dan-manden-byggede-et-hus',
            'konso': 'manden byggede et hus',
            'gloss': 'man.DEF  build.PST  INDEF.NEUT  house',
            'translation': 'The man built a house.',
            'tree_bracket': ('[S [NP [N manden]] '
                             '[VP [V byggede] [NP [Det et] [N hus]]]]'),
            'notes': 'Orthography transparent, phonology opaque — Danes '
                     'swallow half the consonants in rapid speech.',
            'source': 'illustrative',
            'citation': 'Allan et al. (1995), *Danish: A Comprehensive '
                        'Grammar*.',
        }],
    ),
    (
        {'slug': 'icelandic', 'name': 'Íslenska',
         'english_name': 'Icelandic',
         'family': 'indo-european', 'family_name': 'Indo-European',
         'subgroup': 'Germanic (North)',
         'region': 'Iceland', 'macroarea': 'Eurasia',
         'iso639_3': 'isl', 'glottocode': 'icel1247',
         'speakers': 330000, 'word_order': 'svo', 'script': 'Latin',
         'notes': 'Four-case system (nom/acc/dat/gen) largely intact '
                  'from Old Norse; purist neologism policy.'},
        [{
            'slug': 'isl-madurinn-byggdi-hus',
            'konso': 'maðurinn byggði hús',
            'gloss': 'man.DEF.NOM  build.PST.3SG  house.ACC',
            'translation': 'The man built a house.',
            'tree_bracket': ('[S [NP [N maðurinn]] '
                             '[VP [V byggði] [NP [N hús]]]]'),
            'notes': 'Definite -inn is suffixed like other Nordic '
                     'languages; case morphology still productive.',
            'source': 'illustrative',
            'citation': 'Þráinsson (2007), *The Syntax of Icelandic*.',
        }],
    ),

    # ═══════════════════════════════════════════════════════════════
    # INDO-EUROPEAN — Slavic
    # ═══════════════════════════════════════════════════════════════
    (
        {'slug': 'polish', 'name': 'Polski', 'english_name': 'Polish',
         'family': 'indo-european', 'family_name': 'Indo-European',
         'subgroup': 'Slavic (West)',
         'region': 'Poland', 'macroarea': 'Eurasia',
         'iso639_3': 'pol', 'glottocode': 'poli1260',
         'speakers': 45000000, 'word_order': 'svo', 'script': 'Latin',
         'notes': 'Seven noun cases (nom/gen/dat/acc/ins/loc/voc); '
                  'perfective/imperfective aspect pairs on every verb; '
                  'pro-drop with rich verbal morphology.'},
        [{
            'slug': 'pol-mezczyzna-zbudowal-dom',
            'konso': 'mężczyzna zbudował dom',
            'gloss': 'man.NOM  build.PFV.PST.3SG.M  house.ACC',
            'translation': 'The man built a house.',
            'tree_bracket': ('[S [NP [N mężczyzna]] '
                             '[VP [V zbudował] [NP [N dom]]]]'),
            'notes': 'Perfective prefix `z-` on *budować* → *zbudować* '
                     '(complete the house). Case is morphological, '
                     'word order relatively free; SVO here is the '
                     'pragmatically neutral default.',
            'source': 'illustrative',
            'citation': 'Swan (2002), *A Grammar of Contemporary Polish*.',
        }],
    ),
    (
        {'slug': 'russian', 'name': 'Русский',
         'english_name': 'Russian',
         'family': 'indo-european', 'family_name': 'Indo-European',
         'subgroup': 'Slavic (East)',
         'region': 'Russia, ex-USSR', 'macroarea': 'Eurasia',
         'iso639_3': 'rus', 'glottocode': 'russ1263',
         'speakers': 260000000, 'word_order': 'svo', 'script': 'Cyrillic',
         'notes': 'Six cases; pro-drop; no articles; perfective/imperfective '
                  'aspect; copula dropped in present tense.'},
        [{
            'slug': 'rus-chelovek-postroil-dom',
            'konso': 'человек|chelovek построил|postroil дом|dom',
            'gloss': 'man.NOM  build.PFV.PST.3SG.M  house.ACC',
            'translation': 'The man built a house.',
            'tree_bracket': ('[S [NP [N человек|chelovek]] '
                             '[VP [V построил|postroil] '
                             '[NP [N дом|dom]]]]'),
            'notes': 'Perfective prefix `по-` signals telic completion. '
                     'Surface forms annotated with Latin transliteration.',
            'source': 'illustrative',
            'citation': 'Wade (2010), *A Comprehensive Russian Grammar*.',
        }],
    ),
    (
        {'slug': 'ukrainian', 'name': 'Українська',
         'english_name': 'Ukrainian',
         'family': 'indo-european', 'family_name': 'Indo-European',
         'subgroup': 'Slavic (East)',
         'region': 'Ukraine', 'macroarea': 'Eurasia',
         'iso639_3': 'ukr', 'glottocode': 'ukra1253',
         'speakers': 40000000, 'word_order': 'svo', 'script': 'Cyrillic',
         'notes': 'Seven cases including vocative (unlike Russian which '
                  'lost the vocative). Future tense built from imperfective '
                  '`буду` + infinitive is distinctly Ukrainian.'},
        [{
            'slug': 'ukr-cholovik-pobuduvav-dim',
            'konso': 'чоловік|cholovik побудував|pobuduvav дім|dim',
            'gloss': 'man.NOM  build.PFV.PST.3SG.M  house.ACC',
            'translation': 'The man built a house.',
            'tree_bracket': ('[S [NP [N чоловік|cholovik]] '
                             '[VP [V побудував|pobuduvav] '
                             '[NP [N дім|dim]]]]'),
            'notes': 'Close East-Slavic sibling of Russian; most lexicon '
                     'differs, cases + aspect system similar.',
            'source': 'illustrative',
            'citation': 'Pugh & Press (1999), *Ukrainian: A '
                        'Comprehensive Grammar*.',
        }],
    ),
    (
        {'slug': 'czech', 'name': 'Čeština', 'english_name': 'Czech',
         'family': 'indo-european', 'family_name': 'Indo-European',
         'subgroup': 'Slavic (West)',
         'region': 'Czechia', 'macroarea': 'Eurasia',
         'iso639_3': 'ces', 'glottocode': 'czec1258',
         'speakers': 10000000, 'word_order': 'svo', 'script': 'Latin',
         'notes': 'Seven cases; phonemic vowel length; initial stress; '
                  'diglossia between standard (spisovná) and colloquial '
                  '(obecná) registers.'},
        [{
            'slug': 'ces-muz-postavil-dum',
            'konso': 'muž postavil dům',
            'gloss': 'man.NOM  build.PFV.PST.3SG.M  house.ACC',
            'translation': 'The man built a house.',
            'tree_bracket': ('[S [NP [N muž]] '
                             '[VP [V postavil] [NP [N dům]]]]'),
            'notes': 'Perfective prefix `po-`; ů = long u (historical o).',
            'source': 'illustrative',
            'citation': 'Naughton (2005), *Czech: An Essential Grammar*.',
        }],
    ),
    (
        {'slug': 'serbo-croatian', 'name': 'Srpskohrvatski / Srpskohrvatski',
         'english_name': 'Serbo-Croatian (BCMS)',
         'family': 'indo-european', 'family_name': 'Indo-European',
         'subgroup': 'Slavic (South)',
         'region': 'Bosnia, Croatia, Montenegro, Serbia',
         'macroarea': 'Eurasia',
         'iso639_3': 'hbs', 'glottocode': 'sout1528',
         'speakers': 17000000, 'word_order': 'svo', 'script': 'Latin/Cyrillic',
         'notes': 'Pluricentric; written in both Latin and Cyrillic; '
                  'pitch accent + vowel length. BCMS = Bosnian, '
                  'Croatian, Montenegrin, Serbian.'},
        [{
            'slug': 'hbs-covjek-je-sagradio-kucu',
            'konso': 'čovjek je sagradio kuću',
            'gloss': 'man.NOM  AUX.3SG  build.PFV.PST.M.SG  house.ACC',
            'translation': 'The man built a house.',
            'tree_bracket': ('[S [NP [N čovjek]] '
                             '[VP [Aux je] '
                             '[VP [V sagradio] [NP [N kuću]]]]]'),
            'notes': 'Perfect tense = clitic auxiliary `je` (be.3SG) + '
                     'past participle agreeing with subject.',
            'source': 'illustrative',
            'citation': 'Alexander (2006), *Bosnian, Croatian, Serbian: '
                        'A Grammar*.',
        }],
    ),
    (
        {'slug': 'bulgarian', 'name': 'Български',
         'english_name': 'Bulgarian',
         'family': 'indo-european', 'family_name': 'Indo-European',
         'subgroup': 'Slavic (South)',
         'region': 'Bulgaria', 'macroarea': 'Eurasia',
         'iso639_3': 'bul', 'glottocode': 'bulg1262',
         'speakers': 8000000, 'word_order': 'svo', 'script': 'Cyrillic',
         'notes': 'Lost case morphology (only vestigial vocative + pronoun '
                  'oblique); developed a post-posed definite article and '
                  'an evidential verbal system — Balkan Sprachbund features.'},
        [{
            'slug': 'bul-chovek-postroi-kashta',
            'konso': 'човекът|chovekat построи|postroi къща|kashta',
            'gloss': 'man.DEF  build.PFV.AOR.3SG  house',
            'translation': 'The man built a house.',
            'tree_bracket': ('[S [NP [N човекът|chovekat]] '
                             '[VP [V построи|postroi] '
                             '[NP [N къща|kashta]]]]'),
            'notes': 'Post-posed definite `-ът`; aorist carries past + '
                     'witnessed evidential.',
            'source': 'illustrative',
            'citation': 'Scatton (1984), *A Reference Grammar of '
                        'Modern Bulgarian*.',
        }],
    ),

    # ═══════════════════════════════════════════════════════════════
    # INDO-EUROPEAN — Romance (close the Portuguese/Italian/Romanian gap)
    # ═══════════════════════════════════════════════════════════════
    (
        {'slug': 'portuguese', 'name': 'Português',
         'english_name': 'Portuguese',
         'family': 'indo-european', 'family_name': 'Indo-European',
         'subgroup': 'Romance (Western Iberian)',
         'region': 'Portugal, Brazil, Angola, Mozambique, Cape Verde, '
                   'East Timor', 'macroarea': 'Eurasia',
         'iso639_3': 'por', 'glottocode': 'port1283',
         'speakers': 260000000, 'word_order': 'svo', 'script': 'Latin',
         'notes': 'Largest Lusophone variety is Brazilian; nasal vowels; '
                  'personal infinitive (a unique Romance feature); subject '
                  'pro-drop preserved in European but weakening in Brazilian.'},
        [{
            'slug': 'por-o-homem-construiu-uma-casa',
            'konso': 'o homem construiu uma casa',
            'gloss': 'DEF  man  build.PFV.PST.3SG  INDEF.F  house.F',
            'translation': 'The man built a house.',
            'tree_bracket': ('[S [NP [Det o] [N homem]] '
                             '[VP [V construiu] '
                             '[NP [Det uma] [N casa]]]]'),
            'notes': 'Pretérito perfeito simples — the default narrative '
                     'past. Feminine *casa* triggers feminine determiner.',
            'source': 'illustrative',
            'citation': 'Cunha & Cintra (1984), *Nova Gramática do '
                        'Português Contemporâneo*.',
        }],
    ),
    (
        {'slug': 'italian', 'name': 'Italiano',
         'english_name': 'Italian',
         'family': 'indo-european', 'family_name': 'Indo-European',
         'subgroup': 'Romance (Italo-Dalmatian)',
         'region': 'Italy, Switzerland, Vatican, San Marino, global',
         'macroarea': 'Eurasia',
         'iso639_3': 'ita', 'glottocode': 'ital1282',
         'speakers': 65000000, 'word_order': 'svo', 'script': 'Latin',
         'notes': 'Pro-drop; rich verb morphology; passato prossimo '
                  '(auxiliary + participle) is the default spoken past '
                  'rather than the simple preterite.'},
        [{
            'slug': 'ita-l-uomo-ha-costruito-una-casa',
            'konso': "l'uomo ha costruito una casa",
            'gloss': 'DEF  man  AUX.3SG  build.PST.PTCP  INDEF.F  house.F',
            'translation': 'The man built a house.',
            'tree_bracket': ("[S [NP [Det l'] [N uomo]] "
                             '[VP [Aux ha] '
                             '[VP [V costruito] '
                             '[NP [Det una] [N casa]]]]]'),
            'notes': 'Passato prossimo = avere (transitive) / essere '
                     '(unaccusative) + past participle. Elision of '
                     '*lo* before a vowel → *l\'*.',
            'source': 'illustrative',
            'citation': 'Maiden & Robustelli (2013), *A Reference '
                        'Grammar of Modern Italian*.',
        }],
    ),
    (
        {'slug': 'romanian', 'name': 'Română',
         'english_name': 'Romanian',
         'family': 'indo-european', 'family_name': 'Indo-European',
         'subgroup': 'Romance (Eastern)',
         'region': 'Romania, Moldova', 'macroarea': 'Eurasia',
         'iso639_3': 'ron', 'glottocode': 'roma1327',
         'speakers': 24000000, 'word_order': 'svo', 'script': 'Latin',
         'notes': 'Only Romance language with a Slavic-style post-posed '
                  'definite article and surviving vocative case. Uses '
                  'subjunctive instead of infinitive in most contexts.'},
        [{
            'slug': 'ron-barbatul-a-construit-o-casa',
            'konso': 'bărbatul a construit o casă',
            'gloss': 'man.DEF  AUX.3SG  build.PST.PTCP  INDEF.F  house.F',
            'translation': 'The man built a house.',
            'tree_bracket': ('[S [NP [N bărbatul]] '
                             '[VP [Aux a] '
                             '[VP [V construit] '
                             '[NP [Det o] [N casă]]]]]'),
            'notes': 'Post-posed definite -ul (masc) / -a (fem) is a '
                     'Balkan Sprachbund feature shared with Bulgarian.',
            'source': 'illustrative',
            'citation': 'Gönczöl-Davies (2008), *Romanian: An Essential '
                        'Grammar*.',
        }],
    ),
    (
        {'slug': 'catalan', 'name': 'Català', 'english_name': 'Catalan',
         'family': 'indo-european', 'family_name': 'Indo-European',
         'subgroup': 'Romance (Occitano-Romance)',
         'region': 'Catalonia, Valencia, Balearic Islands, Andorra, '
                   'Roussillon, Alghero', 'macroarea': 'Eurasia',
         'iso639_3': 'cat', 'glottocode': 'stan1289',
         'speakers': 10000000, 'word_order': 'svo', 'script': 'Latin',
         'notes': 'Closer to Occitan than to Spanish despite geography; '
                  'perfect periphrasis uses *vaig + infinitive* as a '
                  'past tense (unique among Romance).'},
        [{
            'slug': 'cat-home-va-construir-una-casa',
            'konso': "l'home va construir una casa",
            'gloss': 'DEF  man  go.3SG  build.INF  INDEF.F  house.F',
            'translation': 'The man built a house.',
            'tree_bracket': ("[S [NP [Det l'] [N home]] "
                             '[VP [Aux va] '
                             '[VP [V construir] '
                             '[NP [Det una] [N casa]]]]]'),
            'notes': 'Perfet perifràstic — *va + infinitive* means PAST, '
                     'not FUTURE as in other Romance languages.',
            'source': 'illustrative',
            'citation': 'Wheeler, Yates & Dols (1999), *Catalan: A '
                        'Comprehensive Grammar*.',
        }],
    ),

    # ═══════════════════════════════════════════════════════════════
    # INDO-EUROPEAN — Hellenic, Albanian, Armenian
    # ═══════════════════════════════════════════════════════════════
    (
        {'slug': 'modern-greek', 'name': 'Ελληνικά',
         'english_name': 'Modern Greek',
         'family': 'indo-european', 'family_name': 'Indo-European',
         'subgroup': 'Hellenic',
         'region': 'Greece, Cyprus', 'macroarea': 'Eurasia',
         'iso639_3': 'ell', 'glottocode': 'mode1248',
         'speakers': 13000000, 'word_order': 'svo', 'script': 'Greek',
         'notes': 'Lost infinitive; subjunctive replaces it. Four-case '
                  'system (nom/gen/acc/voc). Pro-drop.'},
        [{
            'slug': 'ell-o-antras-echtise-ena-spiti',
            'konso': 'ο|o άντρας|andras έχτισε|echtise ένα|ena σπίτι|spiti',
            'gloss': 'DEF  man.NOM  build.PFV.PST.3SG  INDEF  house.ACC',
            'translation': 'The man built a house.',
            'tree_bracket': ('[S [NP [Det ο|o] [N άντρας|andras]] '
                             '[VP [V έχτισε|echtise] '
                             '[NP [Det ένα|ena] [N σπίτι|spiti]]]]'),
            'notes': 'Aorist (simple past) with perfective aspect. Greek '
                     'distinguishes perfective / imperfective as tense-'
                     'independent categories.',
            'source': 'illustrative',
            'citation': 'Holton, Mackridge & Philippaki-Warburton (2012), '
                        '*Greek: A Comprehensive Grammar*.',
        }],
    ),
    (
        {'slug': 'albanian', 'name': 'Shqip',
         'english_name': 'Albanian',
         'family': 'indo-european', 'family_name': 'Indo-European',
         'subgroup': 'Albanian',
         'region': 'Albania, Kosovo, North Macedonia',
         'macroarea': 'Eurasia',
         'iso639_3': 'sqi', 'glottocode': 'alba1267',
         'speakers': 7500000, 'word_order': 'svo', 'script': 'Latin',
         'notes': 'Own branch of Indo-European (no close relatives). '
                  'Post-posed definite article; admirative mood.'},
        [{
            'slug': 'sqi-burri-ndertoi-nje-shtepi',
            'konso': 'burri ndërtoi një shtëpi',
            'gloss': 'man.DEF  build.PFV.AOR.3SG  INDEF  house',
            'translation': 'The man built a house.',
            'tree_bracket': ('[S [NP [N burri]] '
                             '[VP [V ndërtoi] '
                             '[NP [Det një] [N shtëpi]]]]'),
            'notes': 'Definite -i suffix on masculine *burr-* → *burri*.',
            'source': 'illustrative',
            'citation': 'Newmark, Hubbard & Prifti (1982), *Standard '
                        'Albanian*.',
        }],
    ),
    (
        {'slug': 'armenian', 'name': 'Հայերեն',
         'english_name': 'Armenian (Eastern)',
         'family': 'indo-european', 'family_name': 'Indo-European',
         'subgroup': 'Armenian',
         'region': 'Armenia, diaspora', 'macroarea': 'Eurasia',
         'iso639_3': 'hye', 'glottocode': 'nucl1235',
         'speakers': 6700000, 'word_order': 'sov', 'script': 'Armenian',
         'notes': 'Own branch of Indo-European; SOV; seven cases; '
                  'own script designed by Mesrop Mashtots in 405 CE.'},
        [{
            'slug': 'hye-mardə-tun-kaṙuc̣ec',
            'konso': 'մարդը|marde տուն|tun կառուցեց|karutsets',
            'gloss': 'man.DEF  house  build.PFV.AOR.3SG',
            'translation': 'The man built a house.',
            'tree_bracket': ('[S [NP [N մարդը|marde]] '
                             '[VP [NP [N տուն|tun]] '
                             '[V կառուցեց|karutsets]]]'),
            'notes': 'SOV — verb final. Post-posed definite -ը (schwa).',
            'source': 'illustrative',
            'citation': 'Dum-Tragut (2009), *Armenian: Modern Eastern '
                        'Armenian*.',
        }],
    ),

    # ═══════════════════════════════════════════════════════════════
    # INDO-EUROPEAN — Baltic + Celtic
    # ═══════════════════════════════════════════════════════════════
    (
        {'slug': 'latvian', 'name': 'Latviešu valoda',
         'english_name': 'Latvian',
         'family': 'indo-european', 'family_name': 'Indo-European',
         'subgroup': 'Baltic',
         'region': 'Latvia', 'macroarea': 'Eurasia',
         'iso639_3': 'lav', 'glottocode': 'latv1249',
         'speakers': 1750000, 'word_order': 'svo', 'script': 'Latin',
         'notes': 'Seven cases; fixed initial stress; pitch accent on '
                  'long syllables; one of two surviving Baltic languages.'},
        [{
            'slug': 'lav-virietis-uzcela-maju',
            'konso': 'vīrietis uzcēla māju',
            'gloss': 'man.NOM  build.PFV.PST.3  house.ACC',
            'translation': 'The man built a house.',
            'tree_bracket': ('[S [NP [N vīrietis]] '
                             '[VP [V uzcēla] [NP [N māju]]]]'),
            'notes': 'Perfective prefix `uz-`. Ā, ē, ī, ū are long '
                     'vowels written with macrons.',
            'source': 'illustrative',
            'citation': 'Nau (1998), *Latvian*, LINCOM Europa.',
        }],
    ),
    (
        {'slug': 'lithuanian', 'name': 'Lietuvių kalba',
         'english_name': 'Lithuanian',
         'family': 'indo-european', 'family_name': 'Indo-European',
         'subgroup': 'Baltic',
         'region': 'Lithuania', 'macroarea': 'Eurasia',
         'iso639_3': 'lit', 'glottocode': 'lith1251',
         'speakers': 3000000, 'word_order': 'svo', 'script': 'Latin',
         'notes': 'Preserves archaic IE morphology — often cited as the '
                  'most conservative living IE language (seven cases, '
                  'dual number in dialects, pitch accent).'},
        [{
            'slug': 'lit-vyras-pastate-nama',
            'konso': 'vyras pastatė namą',
            'gloss': 'man.NOM  build.PFV.PST.3  house.ACC',
            'translation': 'The man built a house.',
            'tree_bracket': ('[S [NP [N vyras]] '
                             '[VP [V pastatė] [NP [N namą]]]]'),
            'notes': 'Accusative case marker -ą (nasal vowel, historical '
                     'PIE *-om).',
            'source': 'illustrative',
            'citation': 'Ambrazas (ed.) (1997), *Lithuanian Grammar*.',
        }],
    ),
    (
        {'slug': 'irish', 'name': 'Gaeilge', 'english_name': 'Irish',
         'family': 'indo-european', 'family_name': 'Indo-European',
         'subgroup': 'Celtic (Goidelic)',
         'region': 'Ireland', 'macroarea': 'Eurasia',
         'iso639_3': 'gle', 'glottocode': 'iris1253',
         'speakers': 170000, 'word_order': 'vso', 'script': 'Latin',
         'notes': 'VSO; initial consonant mutations (lenition + eclipsis); '
                  'no verb "to have" — possession via *tá X ag Y*.'},
        [{
            'slug': 'gle-thog-an-fear-teach',
            'konso': 'thóg an fear teach',
            'gloss': 'build.PST  DEF  man  house',
            'translation': 'The man built a house.',
            'tree_bracket': ('[S [V thóg] '
                             '[NP [Det an] [N fear]] '
                             '[NP [N teach]]]'),
            'notes': 'Lenition on *tóg* → *thóg* in the past tense is '
                     'morphological, not phonological.',
            'source': 'illustrative',
            'citation': 'Stenson (2020), *Modern Irish: A Comprehensive '
                        'Grammar*.',
        }],
    ),
    (
        {'slug': 'welsh', 'name': 'Cymraeg', 'english_name': 'Welsh',
         'family': 'indo-european', 'family_name': 'Indo-European',
         'subgroup': 'Celtic (Brythonic)',
         'region': 'Wales', 'macroarea': 'Eurasia',
         'iso639_3': 'cym', 'glottocode': 'wels1247',
         'speakers': 890000, 'word_order': 'vso', 'script': 'Latin',
         'notes': 'VSO; mutations (soft / nasal / aspirate) triggered '
                  'by grammatical context; inflected prepositions.'},
        [{
            'slug': 'cym-adeiladodd-y-dyn-dy',
            'konso': 'adeiladodd y dyn dŷ',
            'gloss': 'build.PST.3SG  DEF  man  house.SM',
            'translation': 'The man built a house.',
            'tree_bracket': ('[S [V adeiladodd] '
                             '[NP [Det y] [N dyn]] '
                             '[NP [N dŷ]]]'),
            'notes': 'Soft mutation *tŷ* → *dŷ* triggered by being the '
                     'direct object of an inflected verb.',
            'source': 'illustrative',
            'citation': 'King (2015), *Modern Welsh: A Comprehensive '
                        'Grammar*.',
        }],
    ),

    # ═══════════════════════════════════════════════════════════════
    # INDO-EUROPEAN — Indo-Iranian (Indo-Aryan + Iranian)
    # ═══════════════════════════════════════════════════════════════
    (
        {'slug': 'hindi', 'name': 'हिन्दी', 'english_name': 'Hindi',
         'family': 'indo-european', 'family_name': 'Indo-European',
         'subgroup': 'Indo-Aryan (Central)',
         'region': 'North India', 'macroarea': 'Eurasia',
         'iso639_3': 'hin', 'glottocode': 'hind1269',
         'speakers': 600000000, 'word_order': 'sov', 'script': 'Devanagari',
         'notes': 'SOV; split-ergative (ergative `ne` appears on '
                  'transitive subjects in perfective aspect); '
                  'post-positions; compound verbs ubiquitous.'},
        [{
            'slug': 'hin-aadmi-ne-ghar-banaya',
            'konso': 'आदमी|aadmi ने|ne घर|ghar बनाया|banaya',
            'gloss': 'man  ERG  house  build.PFV.M.SG',
            'translation': 'The man built a house.',
            'tree_bracket': ('[S [NP [N आदमी|aadmi] [Case ने|ne]] '
                             '[VP [NP [N घर|ghar]] '
                             '[V बनाया|banaya]]]'),
            'notes': 'Ergative case-marking postposition *ने* appears '
                     'only in perfective transitive clauses — hallmark '
                     'of Indo-Aryan split-ergativity.',
            'source': 'illustrative',
            'citation': 'Kachru (2006), *Hindi*, London Oriental and '
                        'African Language Library.',
        }],
    ),
    (
        {'slug': 'urdu', 'name': 'اُردُو', 'english_name': 'Urdu',
         'family': 'indo-european', 'family_name': 'Indo-European',
         'subgroup': 'Indo-Aryan (Central)',
         'region': 'Pakistan, North India', 'macroarea': 'Eurasia',
         'iso639_3': 'urd', 'glottocode': 'urdu1245',
         'speakers': 230000000, 'word_order': 'sov',
         'script': 'Perso-Arabic (Nastaliq)',
         'notes': 'Sister register of Hindi — shared grammar, divergent '
                  'lexicon (Persian/Arabic loans in Urdu, Sanskrit in '
                  'Hindi) and script. Written right-to-left in Nastaliq.'},
        [{
            'slug': 'urd-aadmi-ne-ghar-banaya',
            'konso': 'آدمی|aadmi نے|ne گھر|ghar بنایا|banaya',
            'gloss': 'man  ERG  house  build.PFV.M.SG',
            'translation': 'The man built a house.',
            'tree_bracket': ('[S [NP [N آدمی|aadmi] [Case نے|ne]] '
                             '[VP [NP [N گھر|ghar]] '
                             '[V بنایا|banaya]]]'),
            'notes': 'Same sentence as Hindi in the other script. '
                     'Ergative *نے* + perfective agreement pattern.',
            'source': 'illustrative',
            'citation': 'Schmidt (1999), *Urdu: An Essential Grammar*.',
        }],
    ),
    (
        {'slug': 'bengali', 'name': 'বাংলা',
         'english_name': 'Bengali (Bangla)',
         'family': 'indo-european', 'family_name': 'Indo-European',
         'subgroup': 'Indo-Aryan (Eastern)',
         'region': 'Bangladesh, West Bengal, Tripura',
         'macroarea': 'Eurasia',
         'iso639_3': 'ben', 'glottocode': 'beng1280',
         'speakers': 265000000, 'word_order': 'sov', 'script': 'Bengali',
         'notes': 'SOV; no grammatical gender; four-way verbal honorific '
                  'distinction; no ergative case (unlike Hindi/Urdu).'},
        [{
            'slug': 'ben-lokti-ekti-ghor-toiri-korlo',
            'konso': 'লোকটি|lokti একটি|ekti ঘর|ghor '
                     'তৈরি|toiri করল|korlo',
            'gloss': 'man.DEF  INDEF  house  make  do.PST.3',
            'translation': 'The man built a house.',
            'tree_bracket': ('[S [NP [N লোকটি|lokti]] '
                             '[VP [NP [Det একটি|ekti] '
                             '[N ঘর|ghor]] '
                             '[V [V তৈরি|toiri] '
                             '[V করল|korlo]]]]'),
            'notes': 'Light-verb compound *tairi kara* "to make / '
                     'build" — a noun + *kara* "do" forms a complex '
                     'predicate. Very productive in Bengali.',
            'source': 'illustrative',
            'citation': 'Thompson (2012), *Bengali: A Comprehensive '
                        'Grammar*.',
        }],
    ),
    (
        {'slug': 'marathi', 'name': 'मराठी',
         'english_name': 'Marathi',
         'family': 'indo-european', 'family_name': 'Indo-European',
         'subgroup': 'Indo-Aryan (Southern)',
         'region': 'Maharashtra, India', 'macroarea': 'Eurasia',
         'iso639_3': 'mar', 'glottocode': 'mara1378',
         'speakers': 83000000, 'word_order': 'sov', 'script': 'Devanagari',
         'notes': 'SOV; three-way gender (M/F/N); split-ergative like '
                  'Hindi; inclusive/exclusive *āmhī / āpaṇ* distinction.'},
        [{
            'slug': 'mar-manusane-ghar-bandhale',
            'konso': 'माणसाने|manusane घर|ghar बांधले|bandhale',
            'gloss': 'man.ERG  house  build.PFV.N',
            'translation': 'The man built a house.',
            'tree_bracket': ('[S [NP [N माणसाने|manusane]] '
                             '[VP [NP [N घर|ghar]] '
                             '[V बांधले|bandhale]]]'),
            'notes': 'Ergative -ने appears as a case suffix rather than '
                     'a separate postposition. Verb agrees with the '
                     'neuter object *ghar*.',
            'source': 'illustrative',
            'citation': 'Pandharipande (1997), *Marathi*, Routledge.',
        }],
    ),
    (
        {'slug': 'persian', 'name': 'فارسی',
         'english_name': 'Persian (Farsi)',
         'family': 'indo-european', 'family_name': 'Indo-European',
         'subgroup': 'Iranian (Southwestern)',
         'region': 'Iran, Afghanistan (Dari), Tajikistan (Tajik)',
         'macroarea': 'Eurasia',
         'iso639_3': 'pes', 'glottocode': 'west2369',
         'speakers': 110000000, 'word_order': 'sov',
         'script': 'Perso-Arabic',
         'notes': 'SOV; definite direct object marked by enclitic '
                  '*-rā* (the *ezāfe* is a separate construction linking '
                  'modifier + head).'},
        [{
            'slug': 'fas-mard-yek-khane-sakht',
            'konso': 'مرد|mard یک|yek خانه|khane ساخت|sakht',
            'gloss': 'man  INDEF  house  build.PST.3SG',
            'translation': 'The man built a house.',
            'tree_bracket': ('[S [NP [N مرد|mard]] '
                             '[VP [NP [Det یک|yek] '
                             '[N خانه|khane]] '
                             '[V ساخت|sakht]]]'),
            'notes': 'No *-rā* because the object is indefinite. Word '
                     'order SOV with VP-final verb.',
            'source': 'illustrative',
            'citation': 'Mahootian (1997), *Persian*, Routledge.',
        }],
    ),

    # ═══════════════════════════════════════════════════════════════
    # URALIC — Estonian, Finnish, Hungarian
    # ═══════════════════════════════════════════════════════════════
    (
        {'slug': 'estonian', 'name': 'Eesti keel',
         'english_name': 'Estonian',
         'family': 'uralic', 'family_name': 'Uralic',
         'subgroup': 'Finnic',
         'region': 'Estonia', 'macroarea': 'Eurasia',
         'iso639_3': 'est', 'glottocode': 'esto1258',
         'speakers': 1100000, 'word_order': 'svo', 'script': 'Latin',
         'notes': '14 cases; three-way vowel + consonant length (short '
                  '/ long / overlong); no grammatical gender; no future '
                  'tense — uses present or modal periphrasis.'},
        [{
            'slug': 'est-mees-ehitas-maja',
            'konso': 'mees ehitas maja',
            'gloss': 'man.NOM  build.PST.3SG  house.GEN/ACC',
            'translation': 'The man built a house.',
            'tree_bracket': ('[S [NP [N mees]] '
                             '[VP [V ehitas] [NP [N maja]]]]'),
            'notes': 'Total object in the genitive/accusative case '
                     '(*maja*); a partitive object (*maja* → *maja*, '
                     'same form but different function) would signal '
                     'incomplete / atelic action.',
            'source': 'illustrative',
            'citation': 'Erelt (ed.) (2003), *Estonian Language*, '
                        'Estonian Academy Publishers.',
        }],
    ),
    (
        {'slug': 'finnish', 'name': 'Suomi',
         'english_name': 'Finnish',
         'family': 'uralic', 'family_name': 'Uralic',
         'subgroup': 'Finnic',
         'region': 'Finland', 'macroarea': 'Eurasia',
         'iso639_3': 'fin', 'glottocode': 'finn1318',
         'speakers': 5400000, 'word_order': 'svo', 'script': 'Latin',
         'notes': '15 cases; vowel harmony (front/back); consonant '
                  'gradation; no grammatical gender; no articles.'},
        [{
            'slug': 'fin-mies-rakensi-talon',
            'konso': 'mies rakensi talon',
            'gloss': 'man.NOM  build.PST.3SG  house.GEN/ACC',
            'translation': 'The man built a house.',
            'tree_bracket': ('[S [NP [N mies]] '
                             '[VP [V rakensi] [NP [N talon]]]]'),
            'notes': 'Total-object accusative = genitive -n here, marking '
                     'completion. Partitive *taloa* would mean "built a '
                     'house (ongoing / some of)".',
            'source': 'illustrative',
            'citation': 'Karlsson (1999), *Finnish: An Essential Grammar*.',
        }],
    ),
    (
        {'slug': 'hungarian', 'name': 'Magyar',
         'english_name': 'Hungarian',
         'family': 'uralic', 'family_name': 'Uralic',
         'subgroup': 'Ugric',
         'region': 'Hungary', 'macroarea': 'Eurasia',
         'iso639_3': 'hun', 'glottocode': 'hung1274',
         'speakers': 13000000, 'word_order': 'free', 'script': 'Latin',
         'notes': '~18 cases; vowel harmony; definite vs. indefinite '
                  'verb conjugation; pragmatically driven word order '
                  '(focus slot immediately pre-verbal).'},
        [{
            'slug': 'hun-a-ferfi-epitett-egy-hazat',
            'konso': 'a férfi épített egy házat',
            'gloss': 'DEF  man  build.PST.3SG.INDEF  INDEF  house.ACC',
            'translation': 'The man built a house.',
            'tree_bracket': ('[S [NP [Det a] [N férfi]] '
                             '[VP [V épített] '
                             '[NP [Det egy] [N házat]]]]'),
            'notes': 'Indefinite conjugation *épített* (not *építette*) '
                     'because the object is indefinite — Hungarian '
                     'verbs agree with object definiteness.',
            'source': 'illustrative',
            'citation': 'Kenesei, Vago & Fenyvesi (1998), *Hungarian*.',
        }],
    ),

    # ═══════════════════════════════════════════════════════════════
    # TURKIC, KOREANIC, KARTVELIAN, EUROPEAN ISOLATE
    # ═══════════════════════════════════════════════════════════════
    (
        {'slug': 'turkish', 'name': 'Türkçe',
         'english_name': 'Turkish',
         'family': 'turkic', 'family_name': 'Turkic',
         'subgroup': 'Oghuz',
         'region': 'Turkey, Cyprus, diaspora', 'macroarea': 'Eurasia',
         'iso639_3': 'tur', 'glottocode': 'nucl1301',
         'speakers': 88000000, 'word_order': 'sov', 'script': 'Latin',
         'notes': 'SOV; agglutinative; vowel harmony; evidential '
                  'distinction (witnessed *-dI* vs. inferential *-mIş*); '
                  'no grammatical gender.'},
        [{
            'slug': 'tur-adam-ev-yapti',
            'konso': 'adam bir ev yaptı',
            'gloss': 'man  INDEF  house  make/build.PST.3SG',
            'translation': 'The man built a house.',
            'tree_bracket': ('[S [NP [N adam]] '
                             '[VP [NP [Det bir] [N ev]] '
                             '[V yaptı]]]'),
            'notes': 'Witnessed past *-tı* signals the speaker has '
                     'direct evidence. *-mış* would mean reported '
                     'or inferred.',
            'source': 'illustrative',
            'citation': 'Göksel & Kerslake (2005), *Turkish: A '
                        'Comprehensive Grammar*.',
        }],
    ),
    (
        {'slug': 'korean', 'name': '한국어',
         'english_name': 'Korean',
         'family': 'koreanic', 'family_name': 'Koreanic',
         'subgroup': 'Han',
         'region': 'Korea, diaspora', 'macroarea': 'Eurasia',
         'iso639_3': 'kor', 'glottocode': 'kore1280',
         'speakers': 80000000, 'word_order': 'sov', 'script': 'Hangul',
         'notes': 'SOV; agglutinative; extensive honorific system '
                  'morphologically realised on verbs + pronouns + '
                  'particles; topic marker *-은/는* vs. subject *-이/가*.'},
        [{
            'slug': 'kor-namjaga-jibeul-jieotda',
            'konso': '남자가|namjaga 집을|jibeul 지었다|jieotda',
            'gloss': 'man.NOM  house.ACC  build.PFV.PST.DECL',
            'translation': 'The man built a house.',
            'tree_bracket': ('[S [NP [N 남자가|namjaga]] '
                             '[VP [NP [N 집을|jibeul]] '
                             '[V 지었다|jieotda]]]'),
            'notes': 'Case particles attach as suffixes: *-가* (nom) + '
                     '*-을* (acc). Sentence-final *-다* is the plain '
                     'declarative ending — style level matters.',
            'source': 'illustrative',
            'citation': 'Sohn (1999), *The Korean Language*.',
        }],
    ),
    (
        {'slug': 'georgian', 'name': 'ქართული',
         'english_name': 'Georgian',
         'family': 'kartvelian', 'family_name': 'Kartvelian',
         'subgroup': 'Karto-Zan',
         'region': 'Georgia', 'macroarea': 'Eurasia',
         'iso639_3': 'kat', 'glottocode': 'nucl1302',
         'speakers': 3700000, 'word_order': 'sov', 'script': 'Mkhedruli',
         'notes': 'Three-way split case alignment (nom/erg/dat) driven '
                  'by TAM series; polypersonal agreement; unique '
                  'Mkhedruli script with no capital letters.'},
        [{
            'slug': 'kat-katsma-sakhli-aashena',
            'konso': 'კაცმა|katsma სახლი|sakhli ააშენა|aashena',
            'gloss': 'man.ERG  house.NOM  build.AOR.3SG',
            'translation': 'The man built a house.',
            'tree_bracket': ('[S [NP [N კაცმა|katsma]] '
                             '[VP [NP [N სახლი|sakhli]] '
                             '[V ააშენა|aashena]]]'),
            'notes': 'Aorist triggers ergative alignment: the transitive '
                     'subject takes *-მა* (erg) while the object is '
                     'in the nominative. Present tense uses nom/dat.',
            'source': 'illustrative',
            'citation': 'Hewitt (1995), *Georgian: A Structural '
                        'Reference Grammar*.',
        }],
    ),
    (
        {'slug': 'basque', 'name': 'Euskara',
         'english_name': 'Basque',
         'family': 'isolate', 'family_name': '',
         'subgroup': '(isolate)',
         'region': 'Basque Country (Spain/France)', 'macroarea': 'Eurasia',
         'iso639_3': 'eus', 'glottocode': 'basq1248',
         'speakers': 750000, 'word_order': 'sov', 'script': 'Latin',
         'notes': 'Language isolate in Europe; ergative-absolutive '
                  'alignment throughout; polypersonal verbal agreement; '
                  'SOV with free pragmatic ordering.'},
        [{
            'slug': 'eus-gizonak-etxea-eraiki-zuen',
            'konso': 'gizonak etxea eraiki zuen',
            'gloss': 'man.ERG  house.ABS  build.PFV  AUX.3SG.3SG.PST',
            'translation': 'The man built the house.',
            'tree_bracket': ('[S [NP [N gizonak]] '
                             '[VP [NP [N etxea]] '
                             '[VP [V eraiki] [Aux zuen]]]]'),
            'notes': 'Ergative suffix *-k* on transitive subject; '
                     'absolutive (unmarked) on object; auxiliary *zuen* '
                     'agrees with both arguments.',
            'source': 'illustrative',
            'citation': 'Hualde & Ortiz de Urbina (eds.) (2003), *A '
                        'Grammar of Basque*.',
        }],
    ),

    # ═══════════════════════════════════════════════════════════════
    # DRAVIDIAN
    # ═══════════════════════════════════════════════════════════════
    (
        {'slug': 'tamil', 'name': 'தமிழ்', 'english_name': 'Tamil',
         'family': 'dravidian', 'family_name': 'Dravidian',
         'subgroup': 'Southern',
         'region': 'Tamil Nadu, Sri Lanka, Singapore, Malaysia',
         'macroarea': 'Eurasia',
         'iso639_3': 'tam', 'glottocode': 'tami1289',
         'speakers': 78000000, 'word_order': 'sov', 'script': 'Tamil',
         'notes': 'SOV; agglutinative; no grammatical gender on nouns '
                  'but 2-way rational/non-rational distinction; deep '
                  'diglossia between classical + spoken varieties.'},
        [{
            'slug': 'tam-manithan-oru-veettaik-kattinan',
            'konso': 'மனிதன்|manithan ஒரு|oru வீட்டைக்|veettaik '
                     'கட்டினான்|kattinan',
            'gloss': 'man.NOM  INDEF  house.ACC  build.PST.3SG.M',
            'translation': 'The man built a house.',
            'tree_bracket': ('[S [NP [N மனிதன்|manithan]] '
                             '[VP [NP [Det ஒரு|oru] '
                             '[N வீட்டைக்|veettaik]] '
                             '[V கட்டினான்|kattinan]]]'),
            'notes': 'Verb suffix *-ān* agrees with 3SG masculine '
                     'rational subject — Dravidian verbs index '
                     'person+number+gender+rationality of subject.',
            'source': 'illustrative',
            'citation': 'Lehmann (1989), *A Grammar of Modern Tamil*.',
        }],
    ),
    (
        {'slug': 'telugu', 'name': 'తెలుగు',
         'english_name': 'Telugu',
         'family': 'dravidian', 'family_name': 'Dravidian',
         'subgroup': 'South-Central',
         'region': 'Andhra Pradesh, Telangana', 'macroarea': 'Eurasia',
         'iso639_3': 'tel', 'glottocode': 'telu1262',
         'speakers': 96000000, 'word_order': 'sov', 'script': 'Telugu',
         'notes': 'SOV; agglutinative; three genders (M/F/N) in verbal '
                  'agreement; inclusive/exclusive 1PL distinction.'},
        [{
            'slug': 'tel-manishi-illu-kattadu',
            'konso': 'మనిషి|manishi ఇల్లు|illu కట్టాడు|kattadu',
            'gloss': 'man  house  build.PST.3SG.M',
            'translation': 'The man built a house.',
            'tree_bracket': ('[S [NP [N మనిషి|manishi]] '
                             '[VP [NP [N ఇల్లు|illu]] '
                             '[V కట్టాడు|kattadu]]]'),
            'notes': 'Verb ending *-āḍu* marks 3SG masculine. Feminine '
                     'would be *-indi*, plural *-ǟru*.',
            'source': 'illustrative',
            'citation': 'Krishnamurti & Gwynn (1985), *A Grammar of '
                        'Modern Telugu*.',
        }],
    ),

    # ═══════════════════════════════════════════════════════════════
    # SINO-TIBETAN — Burmese (expand beyond Chinese)
    # ═══════════════════════════════════════════════════════════════
    (
        {'slug': 'burmese', 'name': 'မြန်မာဘာသာ',
         'english_name': 'Burmese',
         'family': 'sino-tibetan', 'family_name': 'Sino-Tibetan',
         'subgroup': 'Burmish (Lolo-Burmese)',
         'region': 'Myanmar', 'macroarea': 'Eurasia',
         'iso639_3': 'mya', 'glottocode': 'nucl1310',
         'speakers': 33000000, 'word_order': 'sov', 'script': 'Burmese',
         'notes': 'SOV; tonal (4 tones including creaky + low); noun '
                  'classifiers obligatory with numerals; verb-final '
                  'with sentence-final TAM particles.'},
        [{
            'slug': 'mya-lu-ein-hsaukhte',
            'konso': 'လူ|lu အိမ်|ein ဆောက်|hsauk သည်|te',
            'gloss': 'man  house  build  REAL.DECL',
            'translation': 'The man builds a house.',
            'tree_bracket': ('[S [NP [N လူ|lu]] '
                             '[VP [NP [N အိမ်|ein]] '
                             '[VP [V ဆောက်|hsauk] '
                             '[Part သည်|te]]]]'),
            'notes': 'Sentence-final *သည်* marks realis declarative; '
                     'no overt article or number on bare NPs.',
            'source': 'illustrative',
            'citation': 'Okell (1969), *A Reference Grammar of '
                        'Colloquial Burmese*.',
        }],
    ),

    # ═══════════════════════════════════════════════════════════════
    # TAI-KADAI, AUSTRONESIAN (Indonesia / Philippines / Polynesia)
    # ═══════════════════════════════════════════════════════════════
    (
        {'slug': 'thai', 'name': 'ภาษาไทย',
         'english_name': 'Thai',
         'family': 'tai-kadai', 'family_name': 'Tai-Kadai',
         'subgroup': 'Tai (Southwestern)',
         'region': 'Thailand', 'macroarea': 'Eurasia',
         'iso639_3': 'tha', 'glottocode': 'thai1261',
         'speakers': 60000000, 'word_order': 'svo', 'script': 'Thai',
         'notes': 'Isolating SVO; five tones; serial verb constructions; '
                  'noun classifiers; no overt tense morphology — aspect '
                  'marked periphrastically.'},
        [{
            'slug': 'tha-phu-chai-sang-ban',
            'konso': 'ผู้ชาย|phu-chai สร้าง|sang บ้าน|ban',
            'gloss': 'man  build  house',
            'translation': 'The man builds / built a house.',
            'tree_bracket': ('[S [NP [N ผู้ชาย|phu-chai]] '
                             '[VP [V สร้าง|sang] '
                             '[NP [N บ้าน|ban]]]]'),
            'notes': 'No tense marking; temporal reference inferred '
                     'from context. Preverbal *ได้* would mark '
                     'completed past.',
            'source': 'illustrative',
            'citation': 'Iwasaki & Ingkaphirom (2005), *A Reference '
                        'Grammar of Thai*.',
        }],
    ),
    (
        {'slug': 'indonesian', 'name': 'Bahasa Indonesia',
         'english_name': 'Indonesian',
         'family': 'austronesian', 'family_name': 'Austronesian',
         'subgroup': 'Malayic',
         'region': 'Indonesia', 'macroarea': 'Papunesia',
         'iso639_3': 'ind', 'glottocode': 'indo1316',
         'speakers': 200000000, 'word_order': 'svo', 'script': 'Latin',
         'notes': 'SVO; reduplication is productive for plurality + '
                  'intensification; active *meN-* vs. passive *di-* '
                  'voice alternation marks focus.'},
        [{
            'slug': 'ind-lelaki-itu-membangun-rumah',
            'konso': 'lelaki itu membangun rumah',
            'gloss': 'man  DEM.DEF  AV-build  house',
            'translation': 'The man built a house.',
            'tree_bracket': ('[S [NP [N lelaki] [Dem itu]] '
                             '[VP [V membangun] [NP [N rumah]]]]'),
            'notes': 'Agent-voice prefix *meN-* signals the subject is '
                     'the actor; passive counterpart *dibangun lelaki '
                     'itu* would foreground the patient.',
            'source': 'illustrative',
            'citation': 'Sneddon et al. (2010), *Indonesian Reference '
                        'Grammar*.',
        }],
    ),
    (
        {'slug': 'javanese', 'name': 'Basa Jawa',
         'english_name': 'Javanese',
         'family': 'austronesian', 'family_name': 'Austronesian',
         'subgroup': 'Javanese',
         'region': 'Java, Indonesia', 'macroarea': 'Papunesia',
         'iso639_3': 'jav', 'glottocode': 'java1254',
         'speakers': 82000000, 'word_order': 'svo', 'script': 'Latin',
         'notes': 'Three main speech levels (ngoko / madya / krama) '
                  'enact social hierarchy — largely lexical substitution '
                  'rather than morphology.'},
        [{
            'slug': 'jav-wong-iku-mbangun-omah',
            'konso': 'wong iku mbangun omah',
            'gloss': 'person  DEM.DEF  AV-build  house',
            'translation': 'The man built a house.',
            'tree_bracket': ('[S [NP [N wong] [Dem iku]] '
                             '[VP [V mbangun] [NP [N omah]]]]'),
            'notes': 'Ngoko (plain) register. Krama (respectful) would '
                     'swap *wong* → *tiyang*, *omah* → *griya*.',
            'source': 'illustrative',
            'citation': 'Robson (2014), *Javanese Grammar for Students*.',
        }],
    ),
    (
        {'slug': 'tagalog', 'name': 'Tagalog',
         'english_name': 'Tagalog (Filipino)',
         'family': 'austronesian', 'family_name': 'Austronesian',
         'subgroup': 'Philippine (Central)',
         'region': 'Philippines', 'macroarea': 'Papunesia',
         'iso639_3': 'tgl', 'glottocode': 'taga1270',
         'speakers': 82000000, 'word_order': 'vso', 'script': 'Latin',
         'notes': 'Verb-initial; Philippine-type "focus" (symmetrical '
                  'voice) system — voice morphology + ang-phrase select '
                  'which argument is the pivot.'},
        [{
            'slug': 'tgl-nagtayo-ang-lalaki-ng-bahay',
            'konso': 'nagtayo ang lalaki ng bahay',
            'gloss': 'AV-build.PFV  PIVOT  man  GEN  house',
            'translation': 'The man built a house.',
            'tree_bracket': ('[S [V nagtayo] '
                             '[NP [Piv ang] [N lalaki]] '
                             '[NP [Gen ng] [N bahay]]]'),
            'notes': 'Agent voice *nag-* puts the builder in the pivot; '
                     'the house is a non-pivot genitive. Switch to '
                     '*Patient voice itinayo* to pivot the house.',
            'source': 'illustrative',
            'citation': 'Schachter & Otanes (1972), *Tagalog Reference '
                        'Grammar*.',
        }],
    ),
    (
        {'slug': 'hawaiian', 'name': 'ʻŌlelo Hawaiʻi',
         'english_name': 'Hawaiian',
         'family': 'austronesian', 'family_name': 'Austronesian',
         'subgroup': 'Polynesian (Eastern)',
         'region': 'Hawaiʻi', 'macroarea': 'Papunesia',
         'iso639_3': 'haw', 'glottocode': 'hawa1245',
         'speakers': 24000, 'word_order': 'vso', 'script': 'Latin',
         'notes': 'VSO; 13-phoneme inventory (smallest in the world); '
                  'two *a*/*o* possessive classes for alienable / '
                  'inalienable possession.'},
        [{
            'slug': 'haw-ua-kukulu-ke-kane-i-ka-hale',
            'konso': 'ua kūkulu ke kāne i ka hale',
            'gloss': 'PFV  build  DEF.M  man  DO  DEF.N  house',
            'translation': 'The man built the house.',
            'tree_bracket': ('[S [Asp ua] [V kūkulu] '
                             '[NP [Det ke] [N kāne]] '
                             '[PP [P i] [NP [Det ka] [N hale]]]]'),
            'notes': 'Perfective *ua* fronts the clause; direct-object '
                     'marker *i* — marking a core argument with a '
                     'preposition is Polynesian.',
            'source': 'illustrative',
            'citation': 'Elbert & Pukui (1979), *Hawaiian Grammar*.',
        }],
    ),
    (
        {'slug': 'maori', 'name': 'Te Reo Māori',
         'english_name': 'Māori',
         'family': 'austronesian', 'family_name': 'Austronesian',
         'subgroup': 'Polynesian (Eastern)',
         'region': 'New Zealand', 'macroarea': 'Papunesia',
         'iso639_3': 'mri', 'glottocode': 'maor1246',
         'speakers': 186000, 'word_order': 'vso', 'script': 'Latin',
         'notes': 'VSO; TAM particles precede the verb; a/o possessive '
                  'distinction like Hawaiian; revitalisation in schools '
                  'since the 1980s.'},
        [{
            'slug': 'mri-i-hanga-te-tangata-i-te-whare',
            'konso': 'i hanga te tangata i te whare',
            'gloss': 'PST  build  DEF  man  DO  DEF  house',
            'translation': 'The man built the house.',
            'tree_bracket': ('[S [T i] [V hanga] '
                             '[NP [Det te] [N tangata]] '
                             '[PP [P i] [NP [Det te] [N whare]]]]'),
            'notes': 'Past particle *i*; unmarked / zero is the default '
                     'aspect in Polynesian.',
            'source': 'illustrative',
            'citation': 'Bauer (1993), *Maori*, Routledge.',
        }],
    ),

    # ═══════════════════════════════════════════════════════════════
    # THE AMERICAS — Uto-Aztecan, Quechuan, Mayan, Na-Dene, Iroquoian, Algic, Eskimo-Aleut
    # ═══════════════════════════════════════════════════════════════
    (
        {'slug': 'nahuatl', 'name': 'Nāhuatlahtōlli',
         'english_name': 'Classical/Central Nahuatl',
         'family': 'uto-aztecan', 'family_name': 'Uto-Aztecan',
         'subgroup': 'Nahuan',
         'region': 'Central Mexico', 'macroarea': 'North America',
         'iso639_3': 'nci', 'glottocode': 'clas1250',
         'speakers': 1700000, 'word_order': 'vso', 'script': 'Latin',
         'notes': 'VSO default; polysynthetic; object incorporation; '
                  'rich applicative + directional morphology on verbs.'},
        [{
            'slug': 'nci-oquichichiuh-in-tlacatl-ce-calli',
            'konso': 'ōquichīuh in tlācatl cē calli',
            'gloss': 'PST-3SG.SBJ-make.PFV  DEF  man  one  house',
            'translation': 'The man built a house.',
            'tree_bracket': ('[S [V ōquichīuh] '
                             '[NP [Det in] [N tlācatl]] '
                             '[NP [Num cē] [N calli]]]'),
            'notes': 'Past prefix *ō-* + subject agreement *qui-* '
                     '+ root + perfective suffix. Definite article '
                     '*in* inherited across most Nahuatl varieties.',
            'source': 'illustrative',
            'citation': 'Launey (2011), *An Introduction to Classical '
                        'Nahuatl*.',
        }],
    ),
    (
        {'slug': 'quechua', 'name': 'Runasimi',
         'english_name': 'Quechua (Cuzco)',
         'family': 'quechuan', 'family_name': 'Quechuan',
         'subgroup': 'Quechua II (Southern)',
         'region': 'Peru, Bolivia, Ecuador', 'macroarea': 'South America',
         'iso639_3': 'quz', 'glottocode': 'cusc1236',
         'speakers': 8000000, 'word_order': 'sov', 'script': 'Latin',
         'notes': 'SOV; agglutinative; evidentiality marked on every '
                  'clause (direct *-mi*, reported *-si*, inferential '
                  '*-chá*); polite/familiar + inclusive/exclusive 1PL.'},
        [{
            'slug': 'quz-runa-wasita-rwarqan',
            'konso': 'runa wasita rwarqan',
            'gloss': 'man  house.ACC  build-PST.3SG',
            'translation': 'The man built a house.',
            'tree_bracket': ('[S [NP [N runa]] '
                             '[VP [NP [N wasita]] '
                             '[V rwarqan]]]'),
            'notes': 'Accusative *-ta* on the object; past suffix '
                     '*-rqa-*. Add *-mi* to assert first-hand '
                     'knowledge: *rwarqanmi*.',
            'source': 'illustrative',
            'citation': 'Cusihuamán (1976), *Gramática quechua: '
                        'Cuzco-Collao*.',
        }],
    ),
    (
        {'slug': 'kiche-maya', 'name': 'Kʼicheʼ',
         'english_name': "K'iche' Maya",
         'family': 'mayan', 'family_name': 'Mayan',
         'subgroup': 'Quichean-Mamean',
         'region': 'Guatemala', 'macroarea': 'North America',
         'iso639_3': 'quc', 'glottocode': 'kich1262',
         'speakers': 1100000, 'word_order': 'vos', 'script': 'Latin',
         'notes': 'VOS basic order; ergative (Set A) / absolutive '
                  '(Set B) cross-reference on the verb stem; voice '
                  'alternations reshape argument marking.'},
        [{
            'slug': 'quc-xuban-le-ja-le-achi',
            'konso': 'xuban le ja le achi',
            'gloss': '3SG.ERG-build.PFV  DEF  house  DEF  man',
            'translation': 'The man built the house.',
            'tree_bracket': ('[S [V xuban] '
                             '[NP [Det le] [N ja]] '
                             '[NP [Det le] [N achi]]]'),
            'notes': 'VOS — object precedes subject. Prefix *x-* marks '
                     'completive aspect + *u-* is 3SG ergative '
                     '(transitive subject).',
            'source': 'illustrative',
            'citation': 'Mondloch (1978), *Basic Quiché Grammar*.',
        }],
    ),
    (
        {'slug': 'navajo', 'name': 'Diné bizaad',
         'english_name': 'Navajo',
         'family': 'na-dene', 'family_name': 'Athabaskan-Eyak-Tlingit',
         'subgroup': 'Athabaskan (Apachean)',
         'region': 'SW United States', 'macroarea': 'North America',
         'iso639_3': 'nav', 'glottocode': 'nava1243',
         'speakers': 170000, 'word_order': 'sov', 'script': 'Latin',
         'notes': 'SOV; tonal; polysynthetic verb template with 10+ '
                  'slots (disjunct / conjunct prefixes + classifier + '
                  'stem); classificatory verbs for handling.'},
        [{
            'slug': 'nav-hastiin-kin-ayiilaa',
            'konso': 'hastiin kin ayiilaa',
            'gloss': 'man  house  3SG-3SG-build.PFV',
            'translation': 'The man built a house.',
            'tree_bracket': ('[S [NP [N hastiin]] '
                             '[VP [NP [N kin]] '
                             '[V ayiilaa]]]'),
            'notes': 'Verb *ayiilaa* is a single morphological word '
                     'with conjugated prefixes + perfective stem set.',
            'source': 'illustrative',
            'citation': 'Young & Morgan (1987), *The Navajo Language: '
                        'A Grammar and Colloquial Dictionary*.',
        }],
    ),
    (
        {'slug': 'cherokee', 'name': 'ᏣᎳᎩ',
         'english_name': 'Cherokee',
         'family': 'iroquoian', 'family_name': 'Iroquoian',
         'subgroup': 'Southern Iroquoian',
         'region': 'SE United States, Oklahoma',
         'macroarea': 'North America',
         'iso639_3': 'chr', 'glottocode': 'cher1273',
         'speakers': 2000, 'word_order': 'free', 'script': 'Cherokee syllabary',
         'notes': 'Polysynthetic; 85-symbol syllabary devised by '
                  'Sequoyah (c. 1821) — each glyph is one CV or V '
                  'syllable; pronominal prefixes bundle subject+object.'},
        [{
            'slug': 'chr-asgaya-galitsode-uwoduhi',
            'konso': 'ᎠᏍᎦᏯ|asgaya ᎦᎵᏦᏕ|galitsode ᎤᏬᏚᎯ|uwoduhi',
            'gloss': 'man  house  3SG.built-it',
            'translation': 'The man built a house.',
            'tree_bracket': ('[S [NP [N ᎠᏍᎦᏯ|asgaya]] '
                             '[VP [NP [N ᎦᎵᏦᏕ|galitsode]] '
                             '[V ᎤᏬᏚᎯ|uwoduhi]]]'),
            'notes': 'Sequoyah syllabary — each character represents a '
                     'full syllable (Ꭰaha, Ꭱꭱe, …). Word order '
                     'is relatively free; pronominal prefixes '
                     'do the agreement work.',
            'source': 'illustrative',
            'citation': 'Pulte & Feeling (1975), *Cherokee Reference '
                        'Grammar*.',
        }],
    ),
    (
        {'slug': 'ojibwe', 'name': 'Anishinaabemowin',
         'english_name': 'Ojibwe',
         'family': 'algic', 'family_name': 'Algic',
         'subgroup': 'Algonquian (Central)',
         'region': 'Great Lakes (Canada / USA)',
         'macroarea': 'North America',
         'iso639_3': 'oji', 'glottocode': 'ojib1241',
         'speakers': 90000, 'word_order': 'free', 'script': 'Latin/Syllabics',
         'notes': 'Polysynthetic; animate / inanimate gender drives '
                  'concord; direct vs. inverse voice disambiguates '
                  'actor/undergoer on a saliency hierarchy.'},
        [{
            'slug': 'oji-inini-ogii-ozhitoon-waakaaigan',
            'konso': 'inini ogii-ozhitoon waakaaʼigan',
            'gloss': 'man  3-PST-build.TI  house.INAN',
            'translation': 'The man built a house.',
            'tree_bracket': ('[S [NP [N inini]] '
                             '[VP [V ogii-ozhitoon] '
                             '[NP [N waakaaʼigan]]]]'),
            'notes': 'Prefix *o-* = 3rd person, *gii-* = past, '
                     '*-toon* is the final for inanimate objects (TI = '
                     '"transitive inanimate" stem class).',
            'source': 'illustrative',
            'citation': 'Valentine (2001), *Nishnaabemwin Reference '
                        'Grammar*.',
        }],
    ),
    (
        {'slug': 'kalaallisut', 'name': 'Kalaallisut',
         'english_name': 'Greenlandic (Kalaallisut)',
         'family': 'eskimo-aleut', 'family_name': 'Eskimo-Aleut',
         'subgroup': 'Inuit',
         'region': 'Greenland', 'macroarea': 'Eurasia',
         'iso639_3': 'kal', 'glottocode': 'kala1399',
         'speakers': 56000, 'word_order': 'sov', 'script': 'Latin',
         'notes': 'Polysynthetic + agglutinative; one word can be a '
                  'whole sentence; ergative-absolutive alignment; '
                  '~500 derivational suffixes documented.'},
        [{
            'slug': 'kal-angut-illuliortoq',
            'konso': 'angut illuliortoq',
            'gloss': 'man  house-make.PRES.3SG.INTR',
            'translation': 'The man is building a house.',
            'tree_bracket': ('[S [NP [N angut]] '
                             '[VP [V illuliortoq]]]'),
            'notes': 'Object incorporation: *illu-lior-toq* = '
                     '"house-make-3SG". What English expresses with a '
                     'separate object + verb is one polysynthetic word.',
            'source': 'illustrative',
            'citation': 'Fortescue (1984), *West Greenlandic*.',
        }],
    ),

    # ═══════════════════════════════════════════════════════════════
    # AUSTRALIA, PAPUA, PIDGIN/CREOLE BRIDGE
    # ═══════════════════════════════════════════════════════════════
    (
        {'slug': 'warlpiri', 'name': 'Warlpiri',
         'english_name': 'Warlpiri',
         'family': 'pama-nyungan', 'family_name': 'Pama-Nyungan',
         'subgroup': 'Ngumpin-Yapa',
         'region': 'Central Australia', 'macroarea': 'Australia',
         'iso639_3': 'wbp', 'glottocode': 'warl1254',
         'speakers': 2700, 'word_order': 'free', 'script': 'Latin',
         'notes': 'Non-configurational; ergative on transitive subjects; '
                  'auxiliary complex in second position carries TAM + '
                  'subject/object pronominal clitics; nominal words '
                  'can scatter freely.'},
        [{
            'slug': 'wbp-ngarrka-ngku-ka-yapa-nyanyi',
            'konso': 'ngarrka-ngku ka yapa nya-nyi',
            'gloss': 'man-ERG  PRES.AUX  person.ABS  see-NPST',
            'translation': 'The man sees a person.',
            'tree_bracket': ('[S [NP [N ngarrka-ngku]] '
                             '[Aux ka] '
                             '[NP [N yapa]] '
                             '[V nya-nyi]]'),
            'notes': 'Ergative *-ngku* on transitive subject; auxiliary '
                     '*ka* in 2nd position holds TAM. *Nya-nyi* "see" '
                     'is used here instead of "build" — Warlpiri perception '
                     'verbs are the canonical textbook example.',
            'source': 'illustrative',
            'citation': 'Hale (1983), *Warlpiri and the grammar of '
                        'non-configurational languages*.',
        }],
    ),
    (
        {'slug': 'tok-pisin', 'name': 'Tok Pisin',
         'english_name': 'Tok Pisin',
         'family': 'pidgin', 'family_name': 'Pidgin',
         'subgroup': 'Melanesian Pidgin (English-lexified)',
         'region': 'Papua New Guinea', 'macroarea': 'Papunesia',
         'iso639_3': 'tpi', 'glottocode': 'tokp1240',
         'speakers': 4000000, 'word_order': 'svo', 'script': 'Latin',
         'notes': 'English-lexified creole with Oceanic substrate; '
                  'SVO; predicate marker *i*; TAM particles *bai* '
                  '(future) / *bin* (past); inclusive *yumi* vs. '
                  'exclusive *mipela*.'},
        [{
            'slug': 'tpi-man-i-wokim-haus',
            'konso': 'man i wokim haus',
            'gloss': 'man  PRED  build.TRANS  house',
            'translation': 'The man built a house.',
            'tree_bracket': ('[S [NP [N man]] '
                             '[VP [Pred i] '
                             '[VP [V wokim] [NP [N haus]]]]]'),
            'notes': 'Predicate marker *i* obligatory with 3rd-person '
                     'subjects; transitive *-im* suffix distinguishes '
                     'transitive *wokim* "build X" from intransitive '
                     '*wok* "work".',
            'source': 'illustrative',
            'citation': 'Verhaar (1995), *Toward a Reference Grammar '
                        'of Tok Pisin*.',
        }],
    ),

    # ═══════════════════════════════════════════════════════════════
    # SIGN LANGUAGE — American Sign Language
    # ═══════════════════════════════════════════════════════════════
    (
        {'slug': 'asl', 'name': 'ASL',
         'english_name': 'American Sign Language',
         'family': 'sign-language', 'family_name': 'Sign Language',
         'subgroup': 'French Sign Language family',
         'region': 'USA, Anglophone Canada, parts of Asia / Africa via '
                   'education exports', 'macroarea': 'North America',
         'iso639_3': 'ase', 'glottocode': 'amer1248',
         'speakers': 500000, 'word_order': 'topic', 'script': 'none / gloss',
         'notes': 'Topic-comment organisation; simultaneous morphology '
                  '(handshape, location, movement, non-manual features); '
                  'no written form — we gloss in English SMALL-CAPS.'},
        [{
            'slug': 'ase-house-man-build-finish',
            'konso': 'HOUSE, MAN BUILD FINISH',
            'gloss': 'house.TOPIC  man  build  PFV',
            'translation': 'The man built the house.',
            'tree_bracket': ('[S [Topic HOUSE] '
                             '[Comment [NP MAN] '
                             '[VP [V BUILD] [Asp FINISH]]]]'),
            'notes': 'Topicalised object fronted with raised brows (a '
                     'non-manual marker); perfective aspect marked by '
                     'the sign FINISH at clause end.',
            'source': 'illustrative',
            'citation': 'Neidle et al. (2000), *The Syntax of American '
                        'Sign Language*.',
        }],
    ),

    # ═══════════════════════════════════════════════════════════════
    # CONSTRUCTED — Esperanto, Toki Pona
    # ═══════════════════════════════════════════════════════════════
    (
        {'slug': 'esperanto', 'name': 'Esperanto',
         'english_name': 'Esperanto',
         'family': 'constructed', 'family_name': 'Artificial Language',
         'subgroup': 'International auxiliary',
         'region': 'global (L. L. Zamenhof, 1887)',
         'macroarea': 'Eurasia',
         'iso639_3': 'epo', 'glottocode': 'espe1235',
         'speakers': 2000000, 'word_order': 'svo', 'script': 'Latin',
         'notes': 'Regular agglutinative morphology; two cases '
                  '(nom unmarked, acc *-n*); word class marked by '
                  'final vowel (-o noun, -a adj, -i infinitive, '
                  '-is/-as/-os past/present/future verb).'},
        [{
            'slug': 'epo-la-viro-konstruis-domon',
            'konso': 'la viro konstruis domon',
            'gloss': 'DEF  man  build.PST  house.ACC',
            'translation': 'The man built a house.',
            'tree_bracket': ('[S [NP [Det la] [N viro]] '
                             '[VP [V konstruis] '
                             '[NP [N domon]]]]'),
            'notes': 'Accusative *-n* on *domo* → *domon* disambiguates '
                     'object even under free word order.',
            'source': 'illustrative',
            'citation': 'Wennergren (2005), *Plena Manlibro de '
                        'Esperanta Gramatiko*.',
        }],
    ),
    (
        {'slug': 'toki-pona', 'name': 'toki pona',
         'english_name': 'Toki Pona',
         'family': 'constructed', 'family_name': 'Artificial Language',
         'subgroup': 'minimalist',
         'region': 'global (Sonja Lang, 2001)',
         'macroarea': 'Eurasia',
         'iso639_3': '', 'glottocode': 'toki1237',
         'speakers': 1000, 'word_order': 'svo', 'script': 'Latin',
         'notes': 'Only ~120 root words; analytic SVO; particles *li* '
                  '(predicate), *e* (direct object), *pi* (modifier '
                  'grouping). All meaning built by composition.'},
        [{
            'slug': 'toki-jan-li-pali-e-tomo',
            'konso': 'jan li pali e tomo',
            'gloss': 'person  PRED  make  OBJ  house',
            'translation': 'The person built a house.',
            'tree_bracket': ('[S [NP [N jan]] '
                             '[VP [Pred li] '
                             '[V pali] '
                             '[NP [Obj e] [N tomo]]]]'),
            'notes': 'Every transitive predicate: NP *li* V *e* NP. '
                     '*pali* covers make/do/work; *tomo* covers '
                     'house/building/room. Context narrows meaning.',
            'source': 'illustrative',
            'citation': 'Lang (2014), *Toki Pona: The Language of Good*.',
        }],
    ),
]


class Command(BaseCommand):
    help = ('Seed ~55 world languages (Tier 1 + Tier 2) across ~25 '
            'family slots — Slavic, Baltic, Celtic, Nordic, Romance, '
            'Indo-Aryan, Iranian, Uralic, Turkic, Koreanic, Kartvelian, '
            'Dravidian, Tai-Kadai, Sino-Tibetan, Austronesian, '
            'Uto-Aztecan, Mayan, Quechuan, Na-Dene, Iroquoian, Algic, '
            'Eskimo-Aleut, Pama-Nyungan, Pidgin, Sign Language, '
            'Constructed. One illustrative sentence each.')

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
