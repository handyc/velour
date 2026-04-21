"""Bulk seed: 49 additional Cantonese sentences, bringing the
Cantonese Language row up to 50 trees total (1 from
``seed_african_languages`` — actually ``seed_world_languages``
covers yuec1235 — plus 49 here).

Cantonese (粵語 jyut6 jyu5, Glottolog ``yuec1235``, ISO 639-3 ``yue``,
~85M speakers in Guangdong, Guangxi, Hong Kong, Macau, and the
global diaspora) is a distinct Sinitic language, not a "dialect of
Chinese". The sentences here showcase features that distinguish
Cantonese from Mandarin:

* six tones (Jyutping ``1 2 3 4 5 6`` = hi-level / hi-rising /
  mid-level / low-falling / low-rising / low-level);
* post-verbal aspect markers ``咗 zo2`` (perfective) / ``緊 gan2``
  (progressive) / ``過 gwo3`` (experiential) / ``住 zyu6``
  (continuative);
* copula ``係 hai6`` vs. Mandarin ``是``; negation ``唔 m4``
  (general) + ``冇 mou5`` ("not have"); possessive ``嘅 ge3``;
* V-DO-IO double-object order (``我畀本書你``) where Mandarin
  uses V-IO-DO (``我给你书``);
* dedicated colloquial Hanzi: ``咗 佢 乜 冇 咁 啲 哋 嘢 啱 掂 嚟 返 啱``
  — many have no Mandarin equivalent;
* sentence-final particles ``啊 aa3`` / ``喇 laa3`` / ``喎 wo3``
  / ``囉 lo1`` / ``咩 me1`` / ``咋 zaa3`` that encode mood,
  evidentiality, and illocutionary force.

Every entry is ``illustrative`` — author-composed using morphology
from Matthews & Yip (2011), *Cantonese: A Comprehensive Grammar*
(Routledge, 2nd ed.). Each sentence cites the relevant section.

Jyutping is inlined on every Chinese leaf via the tree-parser's
``surface|romanization`` convention, so the SVG renderer draws a
second transliteration line beneath each glyph.

Run:      venv/bin/python manage.py seed_bulk_cantonese
Re-run:   safe — update_or_create on slug.
"""

from django.core.management.base import BaseCommand
from django.db import transaction

from muka.models import Language, Sentence
from muka.tree import parse_bracket


CANTONESE = [

    # ── Simple SVO (5) ────────────────────────────────────────────────
    {'slug': 'yue-ngo-sik-faan',
     'konso': '我食飯',
     'gloss': '1SG  eat  rice',
     'translation': 'I eat.',
     'tree_bracket': ('[S [NP [Pron 我|ngo5]] '
                      '[VP [V 食|sik6] [NP [N 飯|faan6]]]]'),
     'notes': '食飯 sik6 faan6 literally "eat rice" — the default '
              'idiom for "have a meal / eat".',
     'source': 'illustrative',
     'citation': 'Matthews & Yip (2011), §2.1.'},
    {'slug': 'yue-keoi-tai-dinsi',
     'konso': '佢睇電視',
     'gloss': '3SG  watch  television',
     'translation': 'He watches TV.',
     'tree_bracket': ('[S [NP [Pron 佢|keoi5]] '
                      '[VP [V 睇|tai2] [NP [N 電視|din6 si6]]]]'),
     'notes': '佢 keoi5 is the gender-neutral 3rd-person pronoun. '
              'Cantonese prefers 睇 for "watch / see / look" where '
              'Mandarin uses 看.',
     'source': 'illustrative',
     'citation': 'Matthews & Yip (2011), §4.1.'},
    {'slug': 'yue-gau-zeoi-maau',
     'konso': '狗追貓',
     'gloss': 'dog  chase  cat',
     'translation': 'The dog chases the cat.',
     'tree_bracket': ('[S [NP [N 狗|gau2]] '
                      '[VP [V 追|zeoi1] [NP [N 貓|maau1]]]]'),
     'notes': 'Bare nouns without classifiers — generic / definite '
              'reading inferred from context.',
     'source': 'illustrative',
     'citation': 'Matthews & Yip (2011), §2.1.'},
    {'slug': 'yue-ngodei-heoi-hoenggong',
     'konso': '我哋去香港',
     'gloss': '1PL  go  Hong.Kong',
     'translation': 'We go to Hong Kong.',
     'tree_bracket': ('[S [NP [Pron 我哋|ngo5 dei6]] '
                      '[VP [V 去|heoi3] [NP [N 香港|hoeng1 gong2]]]]'),
     'notes': 'Plural suffix 哋 dei6 attaches to pronouns '
              '(我哋 / 你哋 / 佢哋) — no Mandarin cognate of this '
              'character.',
     'source': 'illustrative',
     'citation': 'Matthews & Yip (2011), §4.1.'},
    {'slug': 'yue-lou-si-gaau-ngo',
     'konso': '老師教我',
     'gloss': 'teacher  teach  1SG',
     'translation': 'The teacher teaches me.',
     'tree_bracket': ('[S [NP [N 老師|lou5 si1]] '
                      '[VP [V 教|gaau3] [NP [Pron 我|ngo5]]]]'),
     'notes': 'Single-object transitive; compare the V-DO-IO '
              'double-object pattern below.',
     'source': 'illustrative',
     'citation': 'Matthews & Yip (2011), §8.1.'},

    # ── Perfective 咗 zo2 (2 additional — 1 already seeded) ──────────
    {'slug': 'yue-ngo-sik-zo-faan',
     'konso': '我食咗飯',
     'gloss': '1SG  eat  PFV  rice',
     'translation': 'I have eaten.',
     'tree_bracket': ('[S [NP [Pron 我|ngo5]] '
                      '[VP [V 食|sik6] [Asp 咗|zo2] '
                      '[NP [N 飯|faan6]]]]'),
     'notes': 'Perfective 咗 zo2 sits between verb and object — '
              'marks the event as bounded / complete.',
     'source': 'illustrative',
     'citation': 'Matthews & Yip (2011), §11.2.'},
    {'slug': 'yue-keoi-heoi-zo-hoenggong',
     'konso': '佢去咗香港',
     'gloss': '3SG  go  PFV  Hong.Kong',
     'translation': 'He has gone to Hong Kong.',
     'tree_bracket': ('[S [NP [Pron 佢|keoi5]] '
                      '[VP [V 去|heoi3] [Asp 咗|zo2] '
                      '[NP [N 香港|hoeng1 gong2]]]]'),
     'notes': '咗 here signals both completion and a change of state — '
              'he is no longer here.',
     'source': 'illustrative',
     'citation': 'Matthews & Yip (2011), §11.2.'},

    # ── Progressive 緊 gan2 (2) ────────────────────────────────────────
    {'slug': 'yue-keoi-tai-gan-dinsi',
     'konso': '佢睇緊電視',
     'gloss': '3SG  watch  PROG  television',
     'translation': 'He is watching TV.',
     'tree_bracket': ('[S [NP [Pron 佢|keoi5]] '
                      '[VP [V 睇|tai2] [Asp 緊|gan2] '
                      '[NP [N 電視|din6 si6]]]]'),
     'notes': 'Progressive 緊 gan2 — event ongoing. Mandarin uses '
              '在/正在 preverbally; Cantonese puts it post-verbally.',
     'source': 'illustrative',
     'citation': 'Matthews & Yip (2011), §11.3.'},
    {'slug': 'yue-ngo-duk-gan-syu',
     'konso': '我讀緊書',
     'gloss': '1SG  read  PROG  book',
     'translation': 'I am reading.',
     'tree_bracket': ('[S [NP [Pron 我|ngo5]] '
                      '[VP [V 讀|duk6] [Asp 緊|gan2] '
                      '[NP [N 書|syu1]]]]'),
     'notes': '讀書 duk6 syu1 "study / read" — 讀 alone is "read".',
     'source': 'illustrative',
     'citation': 'Matthews & Yip (2011), §11.3.'},

    # ── Experiential 過 gwo3 (2) ──────────────────────────────────────
    {'slug': 'yue-ngo-heoi-gwo-hoenggong',
     'konso': '我去過香港',
     'gloss': '1SG  go  EXP  Hong.Kong',
     'translation': 'I have been to Hong Kong (at some point).',
     'tree_bracket': ('[S [NP [Pron 我|ngo5]] '
                      '[VP [V 去|heoi3] [Asp 過|gwo3] '
                      '[NP [N 香港|hoeng1 gong2]]]]'),
     'notes': 'Experiential 過 — asserts that the event has been '
              'experienced at least once. Distinct from perfective '
              '咗: 我去咗 = "I went" (specific), 我去過 = '
              '"I have been (at some point)".',
     'source': 'illustrative',
     'citation': 'Matthews & Yip (2011), §11.4.'},
    {'slug': 'yue-keoi-jam-gwo-caa',
     'konso': '佢飲過茶',
     'gloss': '3SG  drink  EXP  tea',
     'translation': 'He has drunk tea (before).',
     'tree_bracket': ('[S [NP [Pron 佢|keoi5]] '
                      '[VP [V 飲|jam2] [Asp 過|gwo3] '
                      '[NP [N 茶|caa4]]]]'),
     'notes': 'Cantonese 飲 jam2 "drink" keeps the classical '
              'distinction from 食 "eat" that Mandarin has largely '
              'collapsed in casual speech.',
     'source': 'illustrative',
     'citation': 'Matthews & Yip (2011), §11.4.'},

    # ── Continuative 住 zyu6 (2) ──────────────────────────────────────
    {'slug': 'yue-keoi-co-zyu',
     'konso': '佢坐住',
     'gloss': '3SG  sit  CONT',
     'translation': 'He is sitting.',
     'tree_bracket': ('[S [NP [Pron 佢|keoi5]] '
                      '[VP [V 坐|co5] [Asp 住|zyu6]]]'),
     'notes': 'Continuative 住 zyu6 — the state holds over time. '
              '緊 gan2 would focus on the action, 住 on the state.',
     'source': 'illustrative',
     'citation': 'Matthews & Yip (2011), §11.5.'},
    {'slug': 'yue-ngo-dang-zyu-nei',
     'konso': '我等住你',
     'gloss': '1SG  wait  CONT  2SG',
     'translation': "I'm waiting for you.",
     'tree_bracket': ('[S [NP [Pron 我|ngo5]] '
                      '[VP [V 等|dang2] [Asp 住|zyu6] '
                      '[NP [Pron 你|nei5]]]]'),
     'notes': '住 zyu6 implies sustained, deliberate action — '
              '"I am (still) waiting for you".',
     'source': 'illustrative',
     'citation': 'Matthews & Yip (2011), §11.5.'},

    # ── Classifiers (5) ───────────────────────────────────────────────
    {'slug': 'yue-jat-go-jan',
     'konso': '一個人',
     'gloss': 'one  CL.general  person',
     'translation': 'one person',
     'tree_bracket': ('[NP [Num 一|jat1] [Cl 個|go3] '
                      '[N 人|jan4]]'),
     'notes': '個 go3 is the default / general classifier, used '
              'when no more specific one applies.',
     'source': 'illustrative',
     'citation': 'Matthews & Yip (2011), §6.1.'},
    {'slug': 'yue-jat-zek-gau',
     'konso': '一隻狗',
     'gloss': 'one  CL.animal  dog',
     'translation': 'one dog',
     'tree_bracket': ('[NP [Num 一|jat1] [Cl 隻|zek3] '
                      '[N 狗|gau2]]'),
     'notes': '隻 zek3 classifies most animals, plus one-of-a-pair '
              'items (a hand, an eye, a shoe).',
     'source': 'illustrative',
     'citation': 'Matthews & Yip (2011), §6.2.'},
    {'slug': 'yue-jat-zoeng-zi',
     'konso': '一張紙',
     'gloss': 'one  CL.flat  paper',
     'translation': 'one sheet of paper',
     'tree_bracket': ('[NP [Num 一|jat1] [Cl 張|zoeng1] '
                      '[N 紙|zi2]]'),
     'notes': '張 zoeng1 classifies flat things — paper, tables, '
              'tickets, beds.',
     'source': 'illustrative',
     'citation': 'Matthews & Yip (2011), §6.2.'},
    {'slug': 'yue-jat-gaan-uk',
     'konso': '一間屋',
     'gloss': 'one  CL.room/building  house',
     'translation': 'one house',
     'tree_bracket': ('[NP [Num 一|jat1] [Cl 間|gaan1] '
                      '[N 屋|uk1]]'),
     'notes': '間 gaan1 for rooms, buildings, shops, schools — '
              'structures you can be inside.',
     'source': 'illustrative',
     'citation': 'Matthews & Yip (2011), §6.2.'},
    {'slug': 'yue-jat-gaa-ce',
     'konso': '一架車',
     'gloss': 'one  CL.vehicle  vehicle',
     'translation': 'one car',
     'tree_bracket': ('[NP [Num 一|jat1] [Cl 架|gaa3] '
                      '[N 車|ce1]]'),
     'notes': '架 gaa3 classifies vehicles, airplanes, piano, '
              'heavy machinery.',
     'source': 'illustrative',
     'citation': 'Matthews & Yip (2011), §6.2.'},

    # ── Negation 唔 m4 (3) ────────────────────────────────────────────
    {'slug': 'yue-ngo-m-zi',
     'konso': '我唔知',
     'gloss': '1SG  NEG  know',
     'translation': "I don't know.",
     'tree_bracket': ('[S [NP [Pron 我|ngo5]] '
                      '[VP [Neg 唔|m4] [V 知|zi1]]]'),
     'notes': '唔 m4 is the general preverbal negator — negates '
              'all non-existential verbs. Mandarin 不.',
     'source': 'illustrative',
     'citation': 'Matthews & Yip (2011), §12.1.'},
    {'slug': 'yue-keoi-m-lai',
     'konso': '佢唔嚟',
     'gloss': '3SG  NEG  come',
     'translation': "He isn't coming.",
     'tree_bracket': ('[S [NP [Pron 佢|keoi5]] '
                      '[VP [Neg 唔|m4] [V 嚟|lai4]]]'),
     'notes': '嚟 lai4 "come" is a colloquial-Cantonese character '
              '(Mandarin 来).',
     'source': 'illustrative',
     'citation': 'Matthews & Yip (2011), §12.1.'},
    {'slug': 'yue-ngo-m-hai-lousi',
     'konso': '我唔係老師',
     'gloss': '1SG  NEG  COP  teacher',
     'translation': 'I am not a teacher.',
     'tree_bracket': ('[S [NP [Pron 我|ngo5]] '
                      '[VP [Neg 唔|m4] [V 係|hai6] '
                      '[NP [N 老師|lou5 si1]]]]'),
     'notes': '唔 + 係 = 唔係 m4 hai6 "is not" — canonical '
              'copular negation.',
     'source': 'illustrative',
     'citation': 'Matthews & Yip (2011), §12.1.'},

    # ── Negation 冇 mou5 "not have" (1) ──────────────────────────────
    {'slug': 'yue-ngo-mou-cin',
     'konso': '我冇錢',
     'gloss': '1SG  NEG.have  money',
     'translation': "I have no money.",
     'tree_bracket': ('[S [NP [Pron 我|ngo5]] '
                      '[VP [V 冇|mou5] [NP [N 錢|cin2]]]]'),
     'notes': '冇 mou5 = "not have / there is no" (< 無有). '
              'Mandarin 沒有 méiyǒu.',
     'source': 'illustrative',
     'citation': 'Matthews & Yip (2011), §12.2.'},

    # ── Copula 係 hai6 (3) ────────────────────────────────────────────
    {'slug': 'yue-ngo-hai-hoenggong-jan',
     'konso': '我係香港人',
     'gloss': '1SG  COP  Hong.Kong  person',
     'translation': 'I am a Hong Konger.',
     'tree_bracket': ('[S [NP [Pron 我|ngo5]] '
                      '[VP [V 係|hai6] '
                      '[NP [N 香港人|hoeng1 gong2 jan4]]]]'),
     'notes': '係 hai6 is the equative copula — NP-NP identity.',
     'source': 'illustrative',
     'citation': 'Matthews & Yip (2011), §5.1.'},
    {'slug': 'yue-keoi-hai-ngo-pangjau',
     'konso': '佢係我朋友',
     'gloss': '3SG  COP  1SG  friend',
     'translation': 'He is my friend.',
     'tree_bracket': ('[S [NP [Pron 佢|keoi5]] '
                      '[VP [V 係|hai6] '
                      '[NP [NP [Pron 我|ngo5]] '
                      '[N 朋友|pang4 jau5]]]]'),
     'notes': 'Zero possessive — the 嘅 ge3 marker is optional '
              'with kinship / close-relation nouns.',
     'source': 'illustrative',
     'citation': 'Matthews & Yip (2011), §5.2.'},
    {'slug': 'yue-nei-hai-mai-hoksaang',
     'konso': '你係咪學生',
     'gloss': '2SG  COP  NEG.COP  student',
     'translation': 'Are you a student?',
     'tree_bracket': ('[S [NP [Pron 你|nei5]] '
                      '[VP [V 係|hai6] [Neg 咪|mai6] '
                      '[NP [N 學生|hok6 saang1]]]]'),
     'notes': '係唔係 → contracted 係咪 hai6 mai6 is the standard '
              'A-not-A form of the copula — yes/no question.',
     'source': 'illustrative',
     'citation': 'Matthews & Yip (2011), §17.3.'},

    # ── V-DO-IO double-object order (3 — CANTONESE DIAGNOSTIC) ──────
    {'slug': 'yue-ngo-bei-bun-syu-nei',
     'konso': '我畀本書你',
     'gloss': '1SG  give  CL  book  2SG',
     'translation': 'I give you a book.',
     'tree_bracket': ('[S [NP [Pron 我|ngo5]] '
                      '[VP [V 畀|bei2] '
                      '[NP [Cl 本|bun2] [N 書|syu1]] '
                      '[NP [Pron 你|nei5]]]]'),
     'notes': 'V-DO-IO — the direct object (book) precedes the '
              'indirect object (you). Mandarin has V-IO-DO '
              '(我给你书). This is the classic Cantonese / '
              'Mandarin syntactic split.',
     'source': 'illustrative',
     'citation': 'Matthews & Yip (2011), §8.2.'},
    {'slug': 'yue-keoi-bei-saam-baak-man-ngo',
     'konso': '佢畀三百蚊我',
     'gloss': '3SG  give  three  hundred  dollar  1SG',
     'translation': 'He gave me three hundred dollars.',
     'tree_bracket': ('[S [NP [Pron 佢|keoi5]] '
                      '[VP [V 畀|bei2] '
                      '[NP [Num 三百|saam1 baak3] '
                      '[N 蚊|man1]] '
                      '[NP [Pron 我|ngo5]]]]'),
     'notes': '蚊 man1 is the colloquial word for "dollar" in '
              'Cantonese (written 蚊, pronounced like 文).',
     'source': 'illustrative',
     'citation': 'Matthews & Yip (2011), §8.2.'},
    {'slug': 'yue-lou-si-gaau-jyut-jyu-ngo',
     'konso': '老師教粵語我',
     'gloss': 'teacher  teach  Cantonese  1SG',
     'translation': 'The teacher teaches me Cantonese.',
     'tree_bracket': ('[S [NP [N 老師|lou5 si1]] '
                      '[VP [V 教|gaau3] '
                      '[NP [N 粵語|jyut6 jyu5]] '
                      '[NP [Pron 我|ngo5]]]]'),
     'notes': 'With 教 "teach" both V-DO-IO and V-IO-DO are '
              'possible, with V-IO-DO more common in speech. '
              'This is the DO-first order.',
     'source': 'illustrative',
     'citation': 'Matthews & Yip (2011), §8.2.'},

    # ── Possessive 嘅 ge3 (3) ─────────────────────────────────────────
    {'slug': 'yue-keoi-ge-maau',
     'konso': '佢嘅貓',
     'gloss': '3SG  POSS  cat',
     'translation': 'his cat',
     'tree_bracket': ('[NP [NP [Pron 佢|keoi5]] [Poss 嘅|ge3] '
                      '[N 貓|maau1]]'),
     'notes': '嘅 ge3 links possessor to possessum — corresponds '
              'to Mandarin 的.',
     'source': 'illustrative',
     'citation': 'Matthews & Yip (2011), §6.3.'},
    {'slug': 'yue-hoeng-gong-ge-tinhei',
     'konso': '香港嘅天氣',
     'gloss': 'Hong.Kong  POSS  weather',
     'translation': "Hong Kong's weather",
     'tree_bracket': ('[NP [NP [N 香港|hoeng1 gong2]] '
                      '[Poss 嘅|ge3] '
                      '[N 天氣|tin1 hei3]]'),
     'notes': 'Place + 嘅 + noun — a generic modifier construction, '
              'not strictly "ownership".',
     'source': 'illustrative',
     'citation': 'Matthews & Yip (2011), §6.3.'},
    {'slug': 'yue-leng-neoi-ge-saam',
     'konso': '靚女嘅衫',
     'gloss': 'pretty.girl  POSS  clothes',
     'translation': "the pretty girl's clothes",
     'tree_bracket': ('[NP [NP [N 靚女|leng3 neoi5]] '
                      '[Poss 嘅|ge3] '
                      '[N 衫|saam1]]'),
     'notes': '靚 leng3 "pretty" + 女 neoi5 "woman" → 靚女 '
              '"pretty girl"; common Cantonese compound.',
     'source': 'illustrative',
     'citation': 'Matthews & Yip (2011), §6.3.'},

    # ── Questions (4) ─────────────────────────────────────────────────
    {'slug': 'yue-nei-sik-m-sik-jyut-jyu',
     'konso': '你識唔識粵語',
     'gloss': '2SG  know  NEG  know  Cantonese',
     'translation': 'Do you speak Cantonese?',
     'tree_bracket': ('[S [NP [Pron 你|nei5]] '
                      '[VP [V 識|sik1] [Neg 唔|m4] '
                      '[V 識|sik1] '
                      '[NP [N 粵語|jyut6 jyu5]]]]'),
     'notes': 'A-not-A question: V唔V. 識 sik1 "know (how to)" is '
              'the Cantonese equivalent of Mandarin 会 for "speak '
              'a language".',
     'source': 'illustrative',
     'citation': 'Matthews & Yip (2011), §17.2.'},
    {'slug': 'yue-nei-hai-bindou-lei',
     'konso': '你係邊度嚟',
     'gloss': '2SG  COP  where  come',
     'translation': 'Where are you from?',
     'tree_bracket': ('[S [NP [Pron 你|nei5]] '
                      '[VP [V 係|hai6] '
                      '[PP [Wh 邊度|bin1 dou6] [V 嚟|lei4]]]]'),
     'notes': '邊度 bin1 dou6 "where" (lit. "which place"); '
              '嚟 lei4 / 來 "come". No question particle — the '
              'Wh-word itself signals interrogation.',
     'source': 'illustrative',
     'citation': 'Matthews & Yip (2011), §17.1.'},
    {'slug': 'yue-nei-giu-mat-je-meng',
     'konso': '你叫乜嘢名',
     'gloss': '2SG  called  what  name',
     'translation': "What's your name?",
     'tree_bracket': ('[S [NP [Pron 你|nei5]] '
                      '[VP [V 叫|giu3] '
                      '[NP [Wh 乜嘢|mat1 je5] [N 名|meng2]]]]'),
     'notes': '乜嘢 mat1 je5 "what (thing)"; the colloquial form '
              'shortens to 乜 mat1 alone in fast speech.',
     'source': 'illustrative',
     'citation': 'Matthews & Yip (2011), §17.1.'},
    {'slug': 'yue-keoi-dim-gaai-m-lei',
     'konso': '佢點解唔嚟',
     'gloss': '3SG  why  NEG  come',
     'translation': "Why isn't he coming?",
     'tree_bracket': ('[S [NP [Pron 佢|keoi5]] '
                      '[AdvP [Wh 點解|dim2 gaai2]] '
                      '[VP [Neg 唔|m4] [V 嚟|lei4]]]'),
     'notes': '點解 dim2 gaai2 "why" — literally "how explain". '
              'Mandarin equivalent is 为什么.',
     'source': 'illustrative',
     'citation': 'Matthews & Yip (2011), §17.1.'},

    # ── Sentence-final particles (4) ─────────────────────────────────
    {'slug': 'yue-ngo-zou-jyun-laa',
     'konso': '我做完喇',
     'gloss': '1SG  do  finish  SFP.CHANGE',
     'translation': "I'm done now.",
     'tree_bracket': ('[S [NP [Pron 我|ngo5]] '
                      '[VP [V 做|zou6] [V 完|jyun4]] '
                      '[SFP 喇|laa3]]'),
     'notes': '喇 laa3 marks a change of state / new situation — '
              '"now" / "already".',
     'source': 'illustrative',
     'citation': 'Matthews & Yip (2011), §18.3.'},
    {'slug': 'yue-keoi-hai-lou-si-wo',
     'konso': '佢係老師喎',
     'gloss': '3SG  COP  teacher  SFP.HEARSAY',
     'translation': '(I hear) he is a teacher.',
     'tree_bracket': ('[S [NP [Pron 佢|keoi5]] '
                      '[VP [V 係|hai6] '
                      '[NP [N 老師|lou5 si1]]] '
                      '[SFP 喎|wo3]]'),
     'notes': '喎 wo3 marks reported / hearsay information — '
              '"so I heard" / "apparently".',
     'source': 'illustrative',
     'citation': 'Matthews & Yip (2011), §18.3.'},
    {'slug': 'yue-mou-baanfaat-laa',
     'konso': '冇辦法啦',
     'gloss': 'NEG.have  way  SFP.RESIGNED',
     'translation': "There's nothing to be done.",
     'tree_bracket': ('[S [VP [V 冇|mou5] '
                      '[NP [N 辦法|baan6 faat3]]] '
                      '[SFP 啦|laa1]]'),
     'notes': '啦 laa1 softens / resigns — "oh well". '
              'Orthographically often indistinguishable from 喇 '
              'but tonally + functionally distinct.',
     'source': 'illustrative',
     'citation': 'Matthews & Yip (2011), §18.3.'},
    {'slug': 'yue-sik-faan-aa',
     'konso': '食飯啊',
     'gloss': 'eat  rice  SFP.SOFTEN',
     'translation': "Let's eat!",
     'tree_bracket': ('[S [VP [V 食|sik6] [NP [N 飯|faan6]]] '
                      '[SFP 啊|aa3]]'),
     'notes': '啊 aa3 softens directives; without it the bare '
              'imperative sounds curt.',
     'source': 'illustrative',
     'citation': 'Matthews & Yip (2011), §18.3.'},

    # ── Comparatives with 過 gwo3 (3) ────────────────────────────────
    {'slug': 'yue-keoi-gou-gwo-ngo',
     'konso': '佢高過我',
     'gloss': '3SG  tall  than  1SG',
     'translation': "He is taller than me.",
     'tree_bracket': ('[S [NP [Pron 佢|keoi5]] '
                      '[VP [Adj 高|gou1] '
                      '[PP [P 過|gwo3] [NP [Pron 我|ngo5]]]]]'),
     'notes': 'Comparative = Adj + 過 + standard. Mandarin uses '
              '比 X Adj; Cantonese Adj 過 X. Etymologically 過 '
              '"pass / exceed".',
     'source': 'illustrative',
     'citation': 'Matthews & Yip (2011), §9.2.'},
    {'slug': 'yue-gam-jat-jit-gwo-kam-jat',
     'konso': '今日熱過琴日',
     'gloss': 'today  hot  than  yesterday',
     'translation': "Today is hotter than yesterday.",
     'tree_bracket': ('[S [NP [N 今日|gam1 jat6]] '
                      '[VP [Adj 熱|jit6] '
                      '[PP [P 過|gwo3] '
                      '[NP [N 琴日|kam4 jat6]]]]]'),
     'notes': '琴日 kam4 jat6 "yesterday" is a Cantonese-specific '
              'expression (Mandarin 昨天 zuótiān).',
     'source': 'illustrative',
     'citation': 'Matthews & Yip (2011), §9.2.'},
    {'slug': 'yue-ni-gaa-ce-gwai-gwo-go-gaa',
     'konso': '呢架車貴過嗰架',
     'gloss': 'this  CL.vehicle  expensive  than  that  CL',
     'translation': "This car is more expensive than that one.",
     'tree_bracket': ('[S [NP [Dem 呢|ni1] [Cl 架|gaa3] '
                      '[N 車|ce1]] '
                      '[VP [Adj 貴|gwai3] '
                      '[PP [P 過|gwo3] '
                      '[NP [Dem 嗰|go2] [Cl 架|gaa3]]]]]'),
     'notes': '呢 ni1 / 嗰 go2 — proximal / distal demonstratives '
              '(Mandarin 这 / 那); 嗰架 elides the noun via '
              'classifier-stranding.',
     'source': 'illustrative',
     'citation': 'Matthews & Yip (2011), §6.4, §9.2.'},

    # ── Resultative + directional complements (4) ────────────────────
    {'slug': 'yue-keoi-haang-faan-uk-kei',
     'konso': '佢行返屋企',
     'gloss': '3SG  walk  DIR.back  home',
     'translation': 'He walks back home.',
     'tree_bracket': ('[S [NP [Pron 佢|keoi5]] '
                      '[VP [V 行|haang4] [Dir 返|faan1] '
                      '[NP [N 屋企|uk1 kei2]]]]'),
     'notes': '返 faan1 as a directional complement means '
              '"back" / "return". 屋企 uk1 kei2 "home" is '
              'Cantonese-specific.',
     'source': 'illustrative',
     'citation': 'Matthews & Yip (2011), §10.2.'},
    {'slug': 'yue-ngo-tai-dou-keoi',
     'konso': '我睇到佢',
     'gloss': '1SG  look  ACHV  3SG',
     'translation': 'I saw him.',
     'tree_bracket': ('[S [NP [Pron 我|ngo5]] '
                      '[VP [V 睇|tai2] [Res 到|dou2] '
                      '[NP [Pron 佢|keoi5]]]]'),
     'notes': '到 dou2 "reach / achieve" as a post-verbal '
              'resultative — signals that the action succeeded.',
     'source': 'illustrative',
     'citation': 'Matthews & Yip (2011), §10.1.'},
    {'slug': 'yue-ngo-sik-m-saai-faan',
     'konso': '我食唔晒飯',
     'gloss': '1SG  eat  NEG  exhaustive  rice',
     'translation': "I can't finish the food.",
     'tree_bracket': ('[S [NP [Pron 我|ngo5]] '
                      '[VP [V 食|sik6] [Neg 唔|m4] '
                      '[Res 晒|saai3] '
                      '[NP [N 飯|faan6]]]]'),
     'notes': '晒 saai3 is an exhaustive / completive marker '
              '(all of it); negated infixed 唔 gives potential '
              'negation: "can\'t all".',
     'source': 'illustrative',
     'citation': 'Matthews & Yip (2011), §10.4.'},
    {'slug': 'yue-ngo-maai-dou-syu',
     'konso': '我買到書',
     'gloss': '1SG  buy  ACHV  book',
     'translation': 'I managed to buy the book.',
     'tree_bracket': ('[S [NP [Pron 我|ngo5]] '
                      '[VP [V 買|maai5] [Res 到|dou2] '
                      '[NP [N 書|syu1]]]]'),
     'notes': '到 dou2 again as achievement — "succeeded in".',
     'source': 'illustrative',
     'citation': 'Matthews & Yip (2011), §10.1.'},

    # ── Passive with 俾 bei2 (2) ──────────────────────────────────────
    {'slug': 'yue-keoi-bei-gau-ngaau',
     'konso': '佢俾狗咬',
     'gloss': '3SG  PASS  dog  bite',
     'translation': 'He was bitten by a dog.',
     'tree_bracket': ('[S [NP [Pron 佢|keoi5]] '
                      '[VP [Pass 俾|bei2] '
                      '[NP [N 狗|gau2]] '
                      '[V 咬|ngaau5]]]'),
     'notes': '俾 bei2 is both "give" and a passive marker — '
              'same etymology as the ditransitive. Mandarin 被 '
              'has the same functional overlap.',
     'source': 'illustrative',
     'citation': 'Matthews & Yip (2011), §14.1.'},
    {'slug': 'yue-bun-syu-bei-jan-lo-zo',
     'konso': '本書俾人攞咗',
     'gloss': 'CL  book  PASS  person  take  PFV',
     'translation': '(Someone took the book / the book was taken.)',
     'tree_bracket': ('[S [NP [Cl 本|bun2] [N 書|syu1]] '
                      '[VP [Pass 俾|bei2] '
                      '[NP [N 人|jan4]] '
                      '[V 攞|lo2] [Asp 咗|zo2]]]'),
     'notes': '俾人 "by someone" — indefinite passive agent. '
              '攞 lo2 "take" is a Cantonese-specific character '
              '(Mandarin 拿).',
     'source': 'illustrative',
     'citation': 'Matthews & Yip (2011), §14.1.'},

    # ── Idiomatic + social formulas (3) ──────────────────────────────
    {'slug': 'yue-m-goi-nei',
     'konso': '唔該你',
     'gloss': 'NEG  ought  2SG',
     'translation': 'Thank you / excuse me / please.',
     'tree_bracket': ('[S [VP [V 唔該|m4 goi1] '
                      '[NP [Pron 你|nei5]]]]'),
     'notes': '唔該 m4 goi1 (lit. "should not") is the all-purpose '
              '"thanks / excuse me / please" — reserved for '
              'service-style interactions; 多謝 do1 ze6 is for '
              'gifts.',
     'source': 'illustrative',
     'citation': 'Matthews & Yip (2011), §19.1.'},
    {'slug': 'yue-hou-noi-mou-gin',
     'konso': '好耐冇見',
     'gloss': 'very  long  NEG.have  meet',
     'translation': 'Long time no see.',
     'tree_bracket': ('[S [AdvP [Adv 好|hou2] [Adv 耐|noi6]] '
                      '[VP [V 冇|mou5] [V 見|gin3]]]'),
     'notes': '好耐 hou2 noi6 "a long time"; 冇見 "haven\'t seen". '
              'The English calque "long time no see" comes from '
              'Chinese.',
     'source': 'illustrative',
     'citation': 'Matthews & Yip (2011), §19.1.'},
    {'slug': 'yue-jam-caa-m-jam',
     'konso': '飲茶唔飲',
     'gloss': 'drink  tea  NEG  drink',
     'translation': '(Are we) going for yum cha or not?',
     'tree_bracket': ('[S [VP [V 飲|jam2] [NP [N 茶|caa4]]] '
                      '[VP [Neg 唔|m4] [V 飲|jam2]]]'),
     'notes': '飲茶 jam2 caa4 "drink tea" = dim sum outing in HK. '
              'V-O 唔 V is a colloquial A-not-A variant where the '
              'object appears inside the first verb phrase.',
     'source': 'illustrative',
     'citation': 'Matthews & Yip (2011), §17.2.'},
]


class Command(BaseCommand):
    help = ('Bulk seed: 49 additional Cantonese sentences, bringing '
            'the Cantonese Language row to 50 trees total. Additive — '
            'safe to re-run. Requires Language<cantonese> to already '
            'exist (run seed_world_languages first).')

    def handle(self, *args, **opts):
        try:
            lang = Language.objects.get(slug='cantonese')
        except Language.DoesNotExist:
            self.stderr.write(self.style.ERROR(
                'Language<cantonese> not found — run '
                'seed_world_languages first.'))
            return

        made, updated, bad = 0, 0, 0
        for row in CANTONESE:
            try:
                parse_bracket(row['tree_bracket'])
            except Exception as e:
                bad += 1
                self.stderr.write(self.style.ERROR(
                    f'  ! {row["slug"]}: bad tree ({e})'))
                continue
            defaults = {**{k: v for k, v in row.items() if k != 'slug'},
                        'language': lang}
            with transaction.atomic():
                _, was_new = Sentence.objects.update_or_create(
                    slug=row['slug'], defaults=defaults)
            if was_new:
                made += 1
            else:
                updated += 1

        self.stdout.write(self.style.SUCCESS(
            f'Cantonese: +{made} new, ~{updated} updated, '
            f'{bad} bad trees. Language<cantonese> now has '
            f'{lang.sentences.count()} sentences.'))
