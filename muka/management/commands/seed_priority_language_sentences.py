"""Seed additional illustrative sentences for the user's priority
languages — Dutch, Mandarin, Spanish, French, Sanskrit, Classical
Tibetan, and Ancient Hebrew.

Each priority language already has one seeded tree from
``seed_world_languages``. This command adds four more per language,
each showcasing a different syntactic feature (V2 inversion,
pro-drop, ergative case, construct state, subjunctive, topic-comment,
ba-construction, passive agent, etc.).

The target languages must already exist; this command will no-op (with
a warning) if any of them is missing. Most entries are
``illustrative`` (author-composed from standard grammars);
Genesis 1:3 is marked ``literature`` with chapter-and-verse citation.

Run:      venv/bin/python manage.py seed_priority_language_sentences
Re-run:   safe — each sentence is update_or_create'd on slug.
"""

from django.core.management.base import BaseCommand
from django.db import transaction

from muka.models import Language, Sentence
from muka.tree import parse_bracket


PRIORITY_SENTENCES = {

    # ─────────────────────────────────────────────────────────────────
    # Dutch — Germanic V2 with verb-final subordinates
    # ─────────────────────────────────────────────────────────────────
    'dutch': [
        {
            'slug': 'nld-de-kat-slaapt',
            'konso': 'de kat slaapt',
            'gloss': 'the  cat  sleep.PRES.3SG',
            'translation': 'The cat sleeps.',
            'tree_bracket': '[S [NP [Det de] [N kat]] [VP [V slaapt]]]',
            'notes': 'Minimal intransitive. Finite verb in second '
                     'position, subject first — the default V2 layout '
                     'for a declarative main clause.',
            'source': 'illustrative',
            'citation': 'Donaldson (2008), *Dutch: A Comprehensive '
                        'Grammar*, §20.1.',
        },
        {
            'slug': 'nld-morgen-komt-hij-terug',
            'konso': 'morgen komt hij terug',
            'gloss': 'tomorrow  come.PRES.3SG  he  back',
            'translation': 'Tomorrow he comes back.',
            'tree_bracket': ('[S [AdvP [Adv morgen]] '
                             '[V komt] [NP [Pron hij]] [Part terug]]'),
            'notes': 'V2 inversion: an adverb in the first slot pushes '
                     'the finite verb ahead of the subject. The '
                     'separable particle *terug* drifts to the end of '
                     'the clause.',
            'source': 'illustrative',
            'citation': 'Broekhuis & Corver (2015), *Syntax of Dutch: '
                        'Verbs and Verb Phrases*, §9.1.',
        },
        {
            'slug': 'nld-ik-weet-dat-zij-nederlands-spreekt',
            'konso': 'ik weet dat zij Nederlands spreekt',
            'gloss': 'I  know.1SG  that  she  Dutch  speak.3SG',
            'translation': 'I know that she speaks Dutch.',
            'tree_bracket': ('[S [NP [Pron ik]] '
                             '[VP [V weet] '
                             '[CP [C dat] '
                             '[S [NP [Pron zij]] '
                             '[VP [NP [N Nederlands]] '
                             '[V spreekt]]]]]]'),
            'notes': 'Subordinate clauses are verb-final. *spreekt* '
                     'moves to the right edge; the matrix clause stays '
                     'V2. The contrast is the Germanic "brace".',
            'source': 'illustrative',
            'citation': 'Broekhuis & Corver (2016), *Syntax of Dutch: '
                        'Clauses*, §14.2.',
        },
        {
            'slug': 'nld-spreek-je-nederlands',
            'konso': 'spreek je Nederlands?',
            'gloss': 'speak.2SG  you  Dutch',
            'translation': 'Do you speak Dutch?',
            'tree_bracket': ('[S [V spreek] [NP [Pron je]] '
                             '[NP [N Nederlands]]]'),
            'notes': 'Yes/no question: the finite verb fronts to clause-'
                     'initial position, subject clitic *je* follows '
                     'immediately. No auxiliary insertion — unlike '
                     'English do-support.',
            'source': 'illustrative',
            'citation': 'Donaldson (2008), §22.2.',
        },
    ],

    # ─────────────────────────────────────────────────────────────────
    # Mandarin — isolating SVO with aspect, topic prominence, ba
    # ─────────────────────────────────────────────────────────────────
    'mandarin': [
        {
            'slug': 'cmn-ta-shi-laoshi',
            'konso': '他是老师',
            'gloss': '3SG  be  teacher',
            'translation': 'He is a teacher.',
            'tree_bracket': ('[S [NP [Pron 他]] '
                             '[VP [V 是] [NP [N 老师]]]]'),
            'notes': 'Copular 是 shì links two nominals. No article or '
                     'number marking — bare *lǎoshī* covers both '
                     '"a teacher" and "teachers".',
            'source': 'illustrative',
            'citation': 'Li & Thompson (1981), §4.1.',
        },
        {
            'slug': 'cmn-wo-ba-shu-fang-zai-zhuozi-shang',
            'konso': '我把书放在桌子上',
            'gloss': '1SG  BA  book  put  at  table  on',
            'translation': 'I put the book on the table.',
            'tree_bracket': ('[S [NP [Pron 我]] '
                             '[VP [BA 把] [NP [N 书]] '
                             '[V 放] '
                             '[PP [P 在] '
                             '[NP [N 桌子] [Loc 上]]]]]'),
            'notes': 'The 把 bǎ construction fronts the (definite, '
                     'affected) object in front of the verb — a '
                     'dedicated "disposal" pattern unavailable in most '
                     'SVO languages. Locative 上 shàng follows its noun.',
            'source': 'illustrative',
            'citation': 'Li & Thompson (1981), §15.',
        },
        {
            'slug': 'cmn-ni-qu-nali',
            'konso': '你去哪里?',
            'gloss': '2SG  go  where',
            'translation': 'Where are you going?',
            'tree_bracket': ('[S [NP [Pron 你]] '
                             '[VP [V 去] [NP [Wh 哪里]]]]'),
            'notes': 'Wh-in-situ: 哪里 nǎlǐ "where" stays in its '
                     'argument position. No movement, no auxiliary '
                     'inversion — the question particle intonation does '
                     'the work.',
            'source': 'illustrative',
            'citation': 'Huang, Li & Li (2009), *The Syntax of Chinese*, '
                        '§7.',
        },
        {
            'slug': 'cmn-na-ben-shu-wo-du-guo',
            'konso': '那本书我读过',
            'gloss': 'that  CL  book  1SG  read  EXP',
            'translation': "That book, I've read.",
            'tree_bracket': ('[S [Topic [NP [Dem 那] [Cl 本] [N 书]]] '
                             '[NP [Pron 我]] '
                             '[VP [V 读] [Asp 过]]]'),
            'notes': 'Topic-comment — the fronted object is a topic '
                     'slot, not a moved argument. Experiential 过 guo '
                     'marks "at least once in the past".',
            'source': 'illustrative',
            'citation': 'Li & Thompson (1976), "Subject and topic: a '
                        'new typology of language".',
        },
    ],

    # ─────────────────────────────────────────────────────────────────
    # Spanish — pro-drop, clitic climbing, subjunctive
    # ─────────────────────────────────────────────────────────────────
    'spanish': [
        {
            'slug': 'spa-me-llamo-maria',
            'konso': 'me llamo María',
            'gloss': 'REFL.1SG  call.1SG  María',
            'translation': 'My name is María.',
            'tree_bracket': ('[S [VP [Clitic me] [V llamo] '
                             '[NP [N María]]]]'),
            'notes': 'Pro-drop: no overt subject. Pronominal verb '
                     '*llamarse* "to call oneself"; the reflexive '
                     'clitic *me* sits proclitically on the finite '
                     'verb.',
            'source': 'illustrative',
            'citation': 'Butt & Benjamin (2011), §11.14.',
        },
        {
            'slug': 'spa-no-te-veo',
            'konso': 'no te veo',
            'gloss': 'NEG  2SG.ACC  see.1SG',
            'translation': "I don't see you.",
            'tree_bracket': ('[S [VP [Neg no] [Clitic te] [V veo]]]'),
            'notes': 'Negator *no* precedes the verbal complex, object '
                     'clitic *te* immediately precedes the finite verb. '
                     'Subject (1SG) is licensed by the verb ending '
                     'alone.',
            'source': 'illustrative',
            'citation': 'RAE (2010), *Nueva gramática de la lengua '
                        'española*, §48.',
        },
        {
            'slug': 'spa-espero-que-vengas',
            'konso': 'espero que vengas',
            'gloss': 'hope.1SG  that  come.SBJV.2SG',
            'translation': 'I hope (that) you come.',
            'tree_bracket': ('[S [VP [V espero] '
                             '[CP [C que] '
                             '[S [VP [V vengas]]]]]]'),
            'notes': 'Volitional matrix verb triggers the present '
                     'subjunctive *vengas* in the complement. Two '
                     'pro-drop clauses nested — both subjects are '
                     'recovered from verbal morphology.',
            'source': 'illustrative',
            'citation': 'Butt & Benjamin (2011), §16.2.',
        },
        {
            'slug': 'spa-los-ninos-se-aman',
            'konso': 'los niños se aman',
            'gloss': 'the.MPL  children.MPL  RECP  love.3PL',
            'translation': 'The children love each other.',
            'tree_bracket': ('[S [NP [Det los] [N niños]] '
                             '[VP [Clitic se] [V aman]]]'),
            'notes': 'Reciprocal *se* with a plural subject — same '
                     'clitic as reflexive; number on the subject '
                     'disambiguates.',
            'source': 'illustrative',
            'citation': 'Butt & Benjamin (2011), §11.15.',
        },
    ],

    # ─────────────────────────────────────────────────────────────────
    # French — clitics, ne…pas, passé composé, questions
    # ─────────────────────────────────────────────────────────────────
    'french': [
        {
            'slug': 'fra-le-chat-dort',
            'konso': 'le chat dort',
            'gloss': 'the  cat  sleep.PRES.3SG',
            'translation': 'The cat sleeps.',
            'tree_bracket': ('[S [NP [Det le] [N chat]] '
                             '[VP [V dort]]]'),
            'notes': 'Minimal SVO with a definite article. Gender '
                     'agreement is silent here but surfaces everywhere '
                     'a qualifier is added.',
            'source': 'illustrative',
            'citation': 'Grevisse & Goosse (2016), §266.',
        },
        {
            'slug': 'fra-je-le-vois',
            'konso': 'je le vois',
            'gloss': '1SG  3SG.M.ACC  see.PRES.1SG',
            'translation': 'I see him / I see it.',
            'tree_bracket': ('[S [NP [Pron je]] '
                             '[VP [Clitic le] [V vois]]]'),
            'notes': 'Object clitic *le* climbs to the left of the '
                     'finite verb — unlike English, where "I see him" '
                     'keeps the object post-verbal.',
            'source': 'illustrative',
            'citation': 'Grevisse & Goosse (2016), §672.',
        },
        {
            'slug': 'fra-elle-ne-parle-pas-francais',
            'konso': 'elle ne parle pas français',
            'gloss': '3SG.F  NEG1  speak.PRES.3SG  NEG2  French',
            'translation': "She doesn't speak French.",
            'tree_bracket': ('[S [NP [Pron elle]] '
                             '[VP [Neg ne] [V parle] [Neg pas] '
                             '[NP [N français]]]]'),
            'notes': 'Bipartite negation flanks the finite verb. In '
                     'informal speech *ne* is frequently dropped; the '
                     'written norm preserves both halves.',
            'source': 'illustrative',
            'citation': 'Grevisse & Goosse (2016), §982.',
        },
        {
            'slug': 'fra-qui-a-vu-marie',
            'konso': 'qui a vu Marie?',
            'gloss': 'who  have.3SG  see.PTCP  Marie',
            'translation': 'Who saw Marie?',
            'tree_bracket': ('[S [NP [Wh qui]] '
                             '[VP [Aux a] [V vu] '
                             '[NP [N Marie]]]]'),
            'notes': 'Subject wh-question in the passé composé. No '
                     'inversion when the wh-word is itself the subject '
                     '— compare *que voit-il?* "what does he see?"',
            'source': 'illustrative',
            'citation': 'Grevisse & Goosse (2016), §391.',
        },
    ],

    # ─────────────────────────────────────────────────────────────────
    # Sanskrit — free word order, rich case, verbless predicates
    # ─────────────────────────────────────────────────────────────────
    'sanskrit': [
        {
            'slug': 'san-sa-raja',
            'konso': 'सः राजा',
            'gloss': '3SG.M.NOM  king.NOM.SG',
            'translation': 'He is a king.',
            'tree_bracket': ('[S [NP [Pron saḥ]] [NP [N rājā]]]'),
            'notes': 'Verbless nominal clause: a bare juxtaposition of '
                     'two nominatives is read as a copular predication. '
                     '*asti* would be inserted only for emphasis.',
            'source': 'illustrative',
            'citation': 'Whitney (1889), §268.',
        },
        {
            'slug': 'san-ramasya-putrah-agacchat',
            'konso': 'रामस्य पुत्रः अगच्छत्',
            'gloss': 'Rama.GEN.SG  son.NOM.SG  go.IMPF.3SG',
            'translation': "Rama's son went.",
            'tree_bracket': ('[S [NP [NP [N rāmasya]] '
                             '[N putraḥ]] '
                             '[VP [V agacchat]]]'),
            'notes': 'Genitive *rāmasya* as an adnominal modifier — '
                     'Sanskrit\'s way of saying "Rama\'s son". The '
                     'augment *a-* marks imperfect past.',
            'source': 'illustrative',
            'citation': 'Whitney (1889), §§296, 585.',
        },
        {
            'slug': 'san-ramena-phalam-khaditam',
            'konso': 'रामेण फलम् खादितम्',
            'gloss': 'Rama.INS.SG  fruit.NOM.SG  eat.PTCP.N.SG',
            'translation': 'The fruit was eaten by Rama.',
            'tree_bracket': ('[S [NP [N rāmeṇa]] '
                             '[VP [NP [N phalam]] '
                             '[V khāditam]]]'),
            'notes': 'Passive with instrumental agent *rāmeṇa* and the '
                     'past passive participle *khāditam*. This is the '
                     'normal way to express past events in Classical '
                     'prose — far more common than finite past forms.',
            'source': 'illustrative',
            'citation': 'Speijer (1886), *Sanskrit Syntax*, §§11, 387.',
        },
        {
            'slug': 'san-ramah-putraya-pustakam-dadati',
            'konso': 'रामः पुत्राय पुस्तकम् ददाति',
            'gloss': 'Rama.NOM.SG  son.DAT.SG  book.ACC.SG  '
                     'give.PRES.3SG',
            'translation': 'Rama gives a book to his son.',
            'tree_bracket': ('[S [NP [N rāmaḥ]] '
                             '[VP [NP [N putrāya]] '
                             '[NP [N pustakam]] '
                             '[V dadāti]]]'),
            'notes': 'Ditransitive with dative recipient *putrāya* and '
                     'accusative theme *pustakam*. Word order is free '
                     'in principle; this ordering is the unmarked one '
                     'for classical prose.',
            'source': 'illustrative',
            'citation': 'Speijer (1886), §82.',
        },
    ],

    # ─────────────────────────────────────────────────────────────────
    # Classical Tibetan — SOV ergative, postpositions, verb-final
    # ─────────────────────────────────────────────────────────────────
    'classical-tibetan': [
        {
            'slug': 'xct-nga-gro',
            'konso': 'ང་འགྲོ།',
            'gloss': '1SG  go.PRES',
            'translation': 'I go.',
            'tree_bracket': ("[S [NP [Pron nga]] [VP [V 'gro]]]"),
            'notes': "Intransitive verbs take a bare absolutive "
                     "subject — no ergative marker. *'gro* is the "
                     'present stem of "to go"; past *phyin* shows the '
                     'usual Tibetan stem ablaut.',
            'source': 'illustrative',
            'citation': 'Hahn (1996), *Lehrbuch der klassischen '
                        'tibetischen Schriftsprache*, §§31–33.',
        },
        {
            'slug': 'xct-ngai-ming-la-bkra-shis-zer',
            'konso': 'ངའི་མིང་ལ་བཀྲ་ཤིས་ཟེར།',
            'gloss': '1SG.GEN  name  at  Tashi  say.PRES',
            'translation': 'My name is Tashi. (lit. "At my name '
                           '[one] says Tashi.")',
            'tree_bracket': ("[S [PP [NP [NP [Pron nga] [Gen 'i]] "
                             "[N ming]] [P la]] "
                             "[VP [N bkra-shis] [V zer]]]"),
            'notes': 'Classical name-frame: the naming relation is '
                     'expressed with a locative PP plus the verb *zer* '
                     '"say" — literally "at my name, [they] say '
                     'Tashi". Genitive *\'i* attaches after a vowel.',
            'source': 'illustrative',
            'citation': 'Beyer (1992), *The Classical Tibetan '
                        'Language*, §§4.4, 5.2.',
        },
        {
            'slug': 'xct-kho-grong-khyer-na-bzhugs',
            'konso': 'ཁོ་གྲོང་ཁྱེར་ན་བཞུགས།',
            'gloss': '3SG.M  city  in  reside.PRES',
            'translation': 'He lives in the city.',
            'tree_bracket': ('[S [NP [Pron kho]] '
                             '[VP [PP [NP [N grong-khyer]] [P na]] '
                             '[V bzhugs]]]'),
            'notes': 'Postpositional *na* "in" follows its NP — '
                     'consistent SOV dependent-head ordering throughout. '
                     '*bzhugs* is the honorific/literary form of '
                     '"to stay, reside".',
            'source': 'illustrative',
            'citation': 'Hahn (1996), §§58, 63.',
        },
        {
            'slug': 'xct-mis-nya-dzin',
            'konso': 'མིས་ཉ་འཛིན།',
            'gloss': 'man-ERG  fish  catch.PRES',
            'translation': 'The man catches fish.',
            'tree_bracket': ("[S [NP [N mi] [Case -s]] "
                             "[VP [NP [N nya]] [V 'dzin]]]"),
            'notes': 'Ergative -s on the transitive subject. The same '
                     'construction appears in the past tense (*bzung*) '
                     'with the same ergative marking — Tibetan is split '
                     'across verbs, not across tense.',
            'source': 'illustrative',
            'citation': 'DeLancey (1990), "Ergativity and the cognitive '
                        'model of event structure in Lhasa Tibetan".',
        },
    ],

    # ─────────────────────────────────────────────────────────────────
    # Ancient (Biblical) Hebrew — VSO prose, verbless clauses, construct
    # ─────────────────────────────────────────────────────────────────
    'ancient-hebrew': [
        {
            'slug': 'hbo-yhwh-elohim',
            'konso': 'יהוה אלהים',
            'gloss': 'YHWH  God',
            'translation': 'YHWH is God.',
            'tree_bracket': ('[S [NP [N YHWH]] [NP [N ʾĕlōhîm]]]'),
            'notes': 'Verbless clause — two nominals juxtaposed form a '
                     'predication with the copula understood. Biblical '
                     'Hebrew has no overt present-tense "to be".',
            'source': 'illustrative',
            'citation': 'Joüon & Muraoka (2006), §154.',
        },
        {
            'slug': 'hbo-bet-hammelek-gadol',
            'konso': 'בֵּית הַמֶּלֶךְ גָּדוֹל',
            'gloss': 'house.CSTR  the-king  big',
            'translation': "The king's house is big.",
            'tree_bracket': ('[S [NP [N bêṯ] '
                             '[NP [Det ha-] [N melek]]] '
                             '[AP [A gāḏôl]]]'),
            'notes': 'Construct chain: *bêṯ* is the construct form of '
                     '*bayit* "house", bound to the following definite '
                     'NP. Definiteness spreads from the dependent — '
                     'the whole chain is read as "the house of the '
                     'king".',
            'source': 'illustrative',
            'citation': 'Joüon & Muraoka (2006), §§129, 140.',
        },
        {
            'slug': 'hbo-wayyomer-elohim-yehi-or',
            'konso': 'וַיֹּאמֶר אֱלֹהִים יְהִי אוֹר',
            'gloss': 'and-say.PFV.3SG.M  God  be.JUSS.3SG.M  light',
            'translation': 'And God said, "Let there be light."',
            'tree_bracket': ('[S [V wayyōmer] '
                             '[NP [N ʾĕlōhîm]] '
                             '[S [V yəhî] [NP [N ʾôr]]]]'),
            'notes': 'Wayyiqtol narrative form *wayyōmer* opens the '
                     'clause (VSO); the quoted speech is another small '
                     'clause with the jussive *yəhî* "let there be" '
                     'fronted. Opens the third verse of Genesis.',
            'source': 'literature',
            'citation': 'Genesis 1:3 (Masoretic Text).',
        },
        {
            'slug': 'hbo-wayyabo-haish-el-habbayit',
            'konso': 'וַיָּבֹא הָאִישׁ אֶל הַבָּיִת',
            'gloss': 'and-come.PFV.3SG.M  the-man  to  the-house',
            'translation': 'And the man came to the house.',
            'tree_bracket': ('[S [V wayyāḇōʾ] '
                             '[NP [Det hā-] [N ʾîš]] '
                             '[PP [P ʾel] '
                             '[NP [Det ha-] [N bāyiṯ]]]]'),
            'notes': 'Canonical narrative chain — wayyiqtol verb first, '
                     'subject second, PP last. The preposition *ʾel* '
                     '"to, toward" governs its NP to the right.',
            'source': 'illustrative',
            'citation': 'Joüon & Muraoka (2006), §§117–118.',
        },
    ],
}


class Command(BaseCommand):
    help = ('Seed additional sentences for the priority languages '
            '(Dutch, Mandarin, Spanish, French, Sanskrit, Classical '
            'Tibetan, Ancient Hebrew). Additive — safe to re-run. '
            'Run seed_world_languages first so the Language rows exist.')

    def handle(self, *args, **opts):
        made_sent, updated_sent, bad_trees, missing_lang = 0, 0, 0, 0

        for lang_slug, sentences in PRIORITY_SENTENCES.items():
            try:
                lang = Language.objects.get(slug=lang_slug)
            except Language.DoesNotExist:
                missing_lang += 1
                self.stderr.write(self.style.WARNING(
                    f'! Language {lang_slug!r} not found — run '
                    f'seed_world_languages first. Skipping '
                    f'{len(sentences)} sentences.'))
                continue

            self.stdout.write(f'· {lang_slug} ({lang.english_name})')
            with transaction.atomic():
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
                        self.stdout.write(f'    + {row["slug"]}')
                    else:
                        updated_sent += 1
                        self.stdout.write(f'    ~ {row["slug"]}')

        msg = (f'Sentences: +{made_sent} new, ~{updated_sent} updated, '
               f'{bad_trees} bad trees')
        if missing_lang:
            msg += f', {missing_lang} languages missing'
        self.stdout.write(self.style.SUCCESS(msg + '.'))
