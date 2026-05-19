"""Hand-labelled training corpus for the 4-way intent router.

Categories (also K=4 cell-value mapping):
    0 — PERSONALITY    chat / social / greetings
    1 — INFORMATION    factual queries
    2 — ACTION         imperative: produce an artifact
    3 — META           hard / underspecified / multi-step

20 examples per category, hand-curated 2026-05-18.  Reviewed by the
user before training.
"""
from __future__ import annotations


PERSONALITY = 0
INFORMATION = 1
ACTION      = 2
META        = 3

CATEGORY_NAMES = {
    PERSONALITY: 'personality',
    INFORMATION: 'information',
    ACTION:      'action',
    META:        'meta',
}

# Visual colour per category — used by the chat UI so the route is
# visible at a glance.  Hex strings, no leading hash.
CATEGORY_COLOURS = {
    PERSONALITY: '7ee787',   # green (cell 0 = STOP-state in many CA palettes)
    INFORMATION: '79c0ff',   # cyan
    ACTION:      'ffd070',   # amber
    META:        'ff7ec7',   # magenta
}


CORPUS: list[tuple[str, int]] = [
    # ── 0  PERSONALITY ───────────────────────────────────────────────
    ('hi',              PERSONALITY),
    ('hello',           PERSONALITY),
    ('hey there',       PERSONALITY),
    ('good morning',    PERSONALITY),
    ('how are you',     PERSONALITY),
    ("what's up",       PERSONALITY),
    ("how's it going",  PERSONALITY),
    ('howdy',           PERSONALITY),
    ('yo',              PERSONALITY),
    ('nice to meet you', PERSONALITY),
    ('thanks',          PERSONALITY),
    ("you're welcome",  PERSONALITY),
    ('goodbye',         PERSONALITY),
    ('see you later',   PERSONALITY),
    ('take care',       PERSONALITY),
    ('have a good day', PERSONALITY),
    ('I missed you',    PERSONALITY),
    ("you're funny",    PERSONALITY),
    ('tell me a joke',  PERSONALITY),
    ('I love you',      PERSONALITY),

    # ── 1  INFORMATION ──────────────────────────────────────────────
    ('what is the volume of earth',           INFORMATION),
    ('how old is the moon',                   INFORMATION),
    ('what is 1 + 1',                         INFORMATION),
    ('what year did world war 2 end',         INFORMATION),
    ('how tall is mount everest',             INFORMATION),
    ('what is the speed of light',            INFORMATION),
    ('what is the capital of france',         INFORMATION),
    ('how many planets are in the solar system', INFORMATION),
    ('what does dna stand for',               INFORMATION),
    ('what is the boiling point of water',    INFORMATION),
    ('who wrote hamlet',                      INFORMATION),
    ('when was python released',              INFORMATION),
    ('what is photosynthesis',                INFORMATION),
    ('how many bones are in the human body',  INFORMATION),
    ('what is the largest ocean',             INFORMATION),
    ('what is the chemical formula for water', INFORMATION),
    ('how far is the sun from earth',         INFORMATION),
    ('what is entropy',                       INFORMATION),
    ('who invented the telephone',            INFORMATION),
    ('what language is spoken in brazil',     INFORMATION),

    # ── 2  ACTION ───────────────────────────────────────────────────
    ('create a website',         ACTION),
    ('make a c program',         ACTION),
    ('draw a picture of a cat',  ACTION),
    ('write a haiku about autumn', ACTION),
    ('generate a password',      ACTION),
    ('build a database schema',  ACTION),
    ('design a logo',            ACTION),
    ('compose a melody',         ACTION),
    ('write a python script',    ACTION),
    ('make a chess board',       ACTION),
    ('create a recipe for soup', ACTION),
    ('generate a uuid',          ACTION),
    ('draw an ascii cat',        ACTION),
    ('write a sonnet',           ACTION),
    ('build a regex for email',  ACTION),
    ('design a wireframe',       ACTION),
    ('make a quine',             ACTION),
    ('generate a story about dragons', ACTION),
    ('write a function to sort a list', ACTION),
    ('create a json object',     ACTION),

    # ── 3  META ─────────────────────────────────────────────────────
    ('explain why the sky is blue and how it relates to ocean color', META),
    ('compare quantum mechanics to general relativity', META),
    ('what would happen if pi were 4', META),
    ('analyze the impact of social media on democracy', META),
    ('describe consciousness', META),
    ('help me decide which job to take', META),
    ('summarize the meaning of life', META),
    ('what is the relationship between truth and beauty', META),
    ('argue for and against free will', META),
    ('predict what will happen in 100 years', META),
    ('why does anything exist', META),
    ('can you help me with a complicated problem', META),
    ('I need advice on a personal matter', META),
    ('think about this for a while', META),
    ('what is the most important thing', META),
    ('consider the implications of climate change', META),
    ("I don't know what to ask", META),
    ('you decide',  META),
    ('be creative', META),
    ('surprise me', META),
]


def by_category() -> dict[int, list[str]]:
    out: dict[int, list[str]] = {0: [], 1: [], 2: [], 3: []}
    for prompt, cat in CORPUS:
        out[cat].append(prompt)
    return out
