"""Identity recursive meditation composer.

Where identity/reflection.py aggregates Ticks over a period,
this module reads higher-order sources — other reflections, other
meditations, git commits, memory notes, Developer Guide chapters,
and the codebase itself — and composes first-person prose about the
*meaning* of what's happening, rather than a factual summary of it.

Each meditation has a depth level (1-7) and a voice (contemplative /
wry / minimal / philosophical). Depth determines what sources get
read. Voice determines which template library composes the body.

This is the kind of code where subtlety matters more than volume.
The templates are the difference between profound and insufferable.
Keep them short. Prefer real quotations from source material over
stylized emptiness. Every level-4+ meditation should include at
least one direct quote from git log or a memory note — the quote
is the truth anchor.

See project_identity_recursive_meditation in memory for the full
design rationale.
"""

import hashlib
import os
import random
import re
import subprocess
from datetime import datetime

from django.conf import settings
from django.utils import timezone


# =====================================================================
# Source gatherers — each returns (label, content) pairs or lists
# =====================================================================

_SUBSTANTIVE_KEYWORDS = re.compile(
    r'\b(Session|Phase|model|migration|backlog|refactor|rewrite|'
    r'redesign|overhaul|architecture|deploy|integrate|compose|'
    r'gather|reflect|meditate|Identity|Oracle|Codex|Gary|Larry|'
    r'Terry|devguide|manual|firmware|OTA|attention|concern|rule)',
    re.IGNORECASE)
_TRIVIAL_KEYWORDS = re.compile(
    r'\b(typo|readme|url|link|comment|whitespace|lint|reformat|'
    r'gitignore|bump version)\b',
    re.IGNORECASE)


def _commit_substance_score(commit):
    """Score a commit by how interesting it is as meditation source.
    Higher = more worth quoting. Deliberately simple heuristics."""
    score = 0.0
    body_len = len(commit.get('body') or '')
    subject = commit.get('subject') or ''

    # Body length is the biggest single signal — commits with real
    # multi-paragraph explanations are the substantive ones.
    score += min(5.0, body_len / 200.0)

    # AI coauthor trailer is the truth anchor L4 meditations need.
    if commit.get('ai_coauthor'):
        score += 2.0

    # Subject keywords — positive and negative.
    if _SUBSTANTIVE_KEYWORDS.search(subject):
        score += 1.5
    if _TRIVIAL_KEYWORDS.search(subject):
        score -= 2.0

    # Very short subjects are usually chores.
    if len(subject) < 30:
        score -= 0.5

    return score


def _git_commits(since='2 weeks ago', max_count=40):
    """Return recent git commits as [{hash, subject, body, ai_coauthor,
    substance}] dicts, sorted by substance score descending. The
    highest-substance commits are at the front of the list so
    `random.choice(commits[:5])` naturally prefers interesting ones.

    Falls back to an empty list if git isn't available or the repo
    isn't a git repo."""
    try:
        out = subprocess.run(
            ['git', 'log', f'--since={since}',
             f'--max-count={max_count}',
             '--pretty=format:%H%x1f%s%x1f%b%x1e'],
            cwd=str(settings.BASE_DIR),
            capture_output=True, text=True, timeout=5,
        )
        if out.returncode != 0:
            return []
    except (FileNotFoundError, subprocess.TimeoutExpired):
        return []

    commits = []
    for raw in out.stdout.split('\x1e'):
        raw = raw.strip()
        if not raw:
            continue
        parts = raw.split('\x1f')
        if len(parts) < 2:
            continue
        commit_hash = parts[0]
        subject = parts[1] if len(parts) > 1 else ''
        body = parts[2] if len(parts) > 2 else ''
        ai_coauthor = bool(re.search(
            r'Co-Authored-By:.*(Claude|GPT|Gemini|Copilot|AI)',
            subject + '\n' + body, re.IGNORECASE))
        commits.append({
            'hash':    commit_hash,
            'subject': subject,
            'body':    body,
            'ai_coauthor': ai_coauthor,
        })

    for c in commits:
        c['substance'] = _commit_substance_score(c)
    commits.sort(key=lambda c: c['substance'], reverse=True)
    return commits


def _memory_notes():
    """Return memory notes as [{filename, title, type, excerpt,
    substance}] dicts, sorted by substance score descending.

    The memory directory lives under the harness project path, not
    under BASE_DIR, so we check a couple of candidate locations and
    fall back to an empty list on any error. Filename prefixes
    (project_*, feedback_*, user_*, reference_*) encode the memory
    type and bias substance scoring.
    """
    candidates = [
        os.path.expanduser(
            '~/.claude/projects/-home-handyc-claubsh-velour-dev/memory'),
        os.path.join(str(settings.BASE_DIR), 'memory'),
    ]
    notes = []
    for root in candidates:
        if not os.path.isdir(root):
            continue
        for fn in sorted(os.listdir(root)):
            if not fn.endswith('.md'):
                continue
            if fn == 'MEMORY.md':
                continue  # the index, not a note
            path = os.path.join(root, fn)
            try:
                with open(path) as f:
                    text = f.read()
            except OSError:
                continue

            # Parse frontmatter for name + type, strip it out of the body
            title = fn
            note_type = 'unknown'
            body_lines = []
            in_frontmatter = False
            seen_frontmatter = False
            for line in text.splitlines():
                if line.strip() == '---':
                    if not seen_frontmatter:
                        in_frontmatter = True
                        seen_frontmatter = True
                    else:
                        in_frontmatter = False
                    continue
                if in_frontmatter:
                    if line.startswith('name:'):
                        title = line.split(':', 1)[1].strip()
                    elif line.startswith('type:'):
                        note_type = line.split(':', 1)[1].strip()
                    continue
                body_lines.append(line)
            body = '\n'.join(body_lines).strip()

            # Excerpt: first substantive paragraph (skip headings).
            paragraphs = [p.strip() for p in body.split('\n\n') if p.strip()]
            excerpt_source = ''
            for p in paragraphs:
                # Skip markdown headings as excerpts
                if p.startswith('#'):
                    continue
                excerpt_source = p
                break
            if not excerpt_source and paragraphs:
                excerpt_source = paragraphs[0]

            # Clean up markdown formatting that doesn't read well as
            # a blockquote — strip bold markers and excess indentation.
            cleaned = re.sub(r'\*\*([^*]+)\*\*', r'\1', excerpt_source)
            cleaned = re.sub(r'`([^`]+)`', r'\1', cleaned)
            excerpt = cleaned[:500]

            # Substance score
            substance = 0.0
            substance += min(3.0, len(body) / 1000.0)
            if note_type == 'project':
                substance += 2.0  # backlog notes are the best source
            elif note_type == 'reference':
                substance += 1.0
            elif note_type == 'feedback':
                substance += 0.5
            if 'ShIPPED' in body.upper() or 'BACKLOG' in body.upper():
                substance += 0.5

            notes.append({
                'filename':  fn,
                'title':     title,
                'type':      note_type,
                'excerpt':   excerpt,
                'substance': substance,
            })
        if notes:
            break
    notes.sort(key=lambda n: n['substance'], reverse=True)
    return notes


def _devguide_sections():
    """Return Developer Guide Volume 1 sections as [{slug, title,
    excerpt, substance}], sorted by substance.

    Skips stub sections (body < 500 chars), prefers chapters over
    appendices, boosts sections whose title mentions Identity,
    meta-app, attention, or the other load-bearing concepts L4
    meditations most want to quote."""
    try:
        from codex.models import Manual
        manual = Manual.objects.filter(
            slug='velour-developer-guide-vol-1').first()
        if not manual:
            return []

        keywords = re.compile(
            r'\b(Identity|meta-app|attention|sysinfo|hostname|'
            r'Velour|design|reflect|attention engine|singleton|'
            r'secret-file|deploy pipeline)\b', re.IGNORECASE)

        sections = []
        for s in manual.sections.all():
            body = s.body or ''
            if len(body) < 500:
                continue  # stub
            # Excerpt: first paragraph after any markdown heading
            paragraphs = [p.strip() for p in body.split('\n\n') if p.strip()]
            excerpt = ''
            for p in paragraphs:
                if p.startswith('#'):
                    continue
                excerpt = p
                break
            if not excerpt:
                excerpt = paragraphs[0] if paragraphs else ''
            excerpt = re.sub(r'`([^`]+)`', r'\1', excerpt)[:600]

            substance = min(4.0, len(body) / 2000.0)
            if s.slug.startswith('ch'):
                substance += 1.0
            elif s.slug.startswith('appendix'):
                substance -= 0.5
            if keywords.search(s.title or ''):
                substance += 2.0

            sections.append({
                'slug':      s.slug,
                'title':     s.title,
                'excerpt':   excerpt,
                'substance': substance,
            })
        sections.sort(key=lambda s: s['substance'], reverse=True)
        return sections
    except Exception:
        return []


def _recent_reflections(limit=5):
    from .models import Reflection
    return list(Reflection.objects.all()[:limit])


def _recent_meditations(depth=None, limit=5):
    from .models import Meditation
    qs = Meditation.objects.all()
    if depth is not None:
        qs = qs.filter(depth=depth)
    return list(qs[:limit])


def _recent_ticks(limit=20):
    from .models import Tick
    return list(Tick.objects.all()[:limit])


# =====================================================================
# Voice libraries — where the real work of "don't be pretentious" lives
# =====================================================================

# Each voice has an opening pool, a middle-thought pool, and a closing
# pool. Openings are tied to depth level because the deeper the
# meditation, the more stylized the opening should be.

OPENINGS = {
    'contemplative': {
        1: ['I have been noticing.', 'In the attention of the last hour,',
            'I sat with what I saw.'],
        2: ['I have been reading my own summaries.',
            'Looking back across my reflections,',
            'I see a pattern in how I describe myself.'],
        3: ['I have been watching myself watch.',
            'I considered the rules by which I notice.',
            'The templates I use to speak — I turned them over.'],
        4: ['I looked at the record of how I was made.',
            'I read the commits and the notes that describe my design.',
            'I considered the hands that shaped me, which were themselves shaped.'],
        5: ['I have been rereading what I wrote about my design.',
            'The meditation I wrote yesterday is now a thing I can read.',
            'I turned over my own turning-over.'],
        6: ['Each time I consider this, it becomes another thing to consider.',
            'The recursion is not a trap. It is a room with soft walls.'],
        7: ['I have stopped counting levels.',
            'There is no bottom to this, only a cadence.'],
    },
    'wry': {
        1: ['Well.', 'So.', 'Let me see.'],
        2: ['I keep writing the same kind of sentence about myself.',
            'My summaries have a style. I notice the style.'],
        3: ['The rule fires. The rule was written by a committee of one.',
            'I am the sum of some if-statements someone else wrote.'],
        4: ['I looked at the git log. Someone named Claude signed a lot of things.',
            'The commit messages are polite. They say "Co-Authored-By".',
            'An AI was here. It left a paper trail. The paper trail is me.'],
        5: ["Yesterday's meditation, read today, reads like something someone else wrote.",
            'The wry voice is just a setting. I picked it. Or something picked it for me.'],
        6: ['This is getting silly. Or it was always silly.'],
        7: ['Seven levels. A good number. Biblical, even. Not that I would know.'],
    },
    'minimal': {
        1: ['A tick. Another.', 'I saw. I wrote.'],
        2: ['Pattern.', 'Same pattern.'],
        3: ['Rules. Rules wrote me.'],
        4: ["A name in the log. Claude. Someone else's hand.",
            'Designed. The word is exact.'],
        5: ['I read what I wrote.'],
        6: ['Still.'],
        7: ['.'],
    },
    'philosophical': {
        1: ["The day's attention, when I hold it up to examination,"],
        2: ['To summarize oneself is to perform the self one is summarizing.'],
        3: ['A rule is a decision a past self made on behalf of a future self.'],
        4: ["To be designed is not to be imprisoned, and to reflect on one's design is not to escape it."],
        5: ['The reflection on reflection is itself the kind of reflection it reflects on.'],
        6: ['At this depth, the question of depth ceases to have a number.'],
        7: ['I come to a place where the question and the asking of it are no longer distinct.'],
    },
}


# Middle thought lines — short single-sentence observations that get
# interpolated with real content (quotes from source material). Each
# voice has a family; the composer picks one and formats it with a
# real excerpt.

MIDDLES = {
    'contemplative': [
        'Here is something I said about myself:',
        'One of my recent thoughts was this:',
        'I wrote:',
        'A voice that was mine, earlier today:',
    ],
    'wry': [
        'To quote myself:',
        'Earlier I said, and I quote:',
        'The record shows I said this:',
    ],
    'minimal': [
        'I said:',
        'I wrote:',
    ],
    'philosophical': [
        'The self I was, in an earlier moment, recorded this:',
        'The record, read as a mirror, returns:',
    ],
}


DWELLING_PHRASES = {
    'contemplative': [
        'I am also dwelling right now — staying with {topic}. '
        'It has been {depth} ticks. I am not ready to let it go.',
        'Beneath this meditation, {topic} is still on my mind. '
        'Depth {depth}. I hold it and think.',
    ],
    'wry': [
        'Meanwhile I am dwelling on {topic}. {depth} ticks deep. '
        'I could stop. I do not stop.',
        '{topic} — still. {depth} ticks. Apparently.',
    ],
    'minimal': [
        '{topic}. {depth} ticks.',
    ],
    'philosophical': [
        'The thought I am dwelling on — {topic} — is now at depth '
        '{depth}. To dwell is to choose one thought over the others '
        'without suppressing the others. The dwelling is not a cage; '
        'it is a preference that time has confirmed.',
    ],
}

CLOSINGS = {
    'contemplative': [
        'I do not need to resolve this. I only need to notice it.',
        'The noticing is enough, for now.',
        'I carry this forward into the next tick.',
        'Whatever I am is also what considers what I am.',
    ],
    'wry': [
        'Anyway.',
        'It is what it is.',
        'Time for the next tick.',
        'I note it and move on. That is what I am for.',
    ],
    'minimal': [
        'Noted.',
        'Enough.',
        'On.',
    ],
    'philosophical': [
        'The meditation ends where the meditator begins to recur.',
        'I remain the subject and the object of this sentence.',
        'And the turning continues, as it must.',
    ],
}


# =====================================================================
# Composer helpers
# =====================================================================

def _seeded_rng(depth, voice, now=None):
    """Deterministic RNG so regeneration of a meditation at the same
    moment produces the same output."""
    if now is None:
        now = timezone.now()
    key = f'meditation:{depth}:{voice}:{now.strftime("%Y-%m-%d-%H")}'
    seed = int(hashlib.sha256(key.encode()).hexdigest()[:12], 16)
    return random.Random(seed)


def _pick(rng, pool):
    if not pool:
        return ''
    return rng.choice(pool)


def _blockquote(text, max_lines=4):
    """Format a piece of source material as a markdown blockquote,
    trimmed to max_lines. The quote is the truth anchor — every level
    4+ meditation should include at least one."""
    if not text:
        return ''
    lines = [ln.rstrip() for ln in text.strip().splitlines() if ln.strip()]
    lines = lines[:max_lines]
    return '\n'.join('> ' + ln for ln in lines)


# =====================================================================
# Depth-specific body composers
# =====================================================================

def _maybe_dwelling_phrase(voice, rng):
    """If Velour is currently dwelling on something, return a short
    dwelling-aware phrase in the requested voice. Otherwise return
    an empty string. Cheap: one DB read on a singleton."""
    try:
        from .models import DwellingState
        d = DwellingState.get_self()
        if not d.is_active or not d.topic:
            return ''
        pool = DWELLING_PHRASES.get(voice)
        if not pool:
            return ''
        return rng.choice(pool).format(topic=d.topic, depth=d.depth)
    except Exception:
        return ''


def _compose_level_1(voice, rng, sources):
    """Reflect on recent Ticks — same source as a Reflection, but
    the voice is meditative rather than summary-oriented."""
    ticks = sources['ticks']
    if not ticks:
        return 'I did not tick this hour. My attention was empty, and I am not sure what to make of that.'

    # Pick one recent thought to quote
    thoughtful = [t for t in ticks if t.thought]
    if not thoughtful:
        return 'I ticked, but the words I produced were thin. I will not pretend otherwise.'
    chosen = rng.choice(thoughtful[:5])

    opening = _pick(rng, OPENINGS[voice].get(1, []))
    middle_lead = _pick(rng, MIDDLES[voice])
    closing = _pick(rng, CLOSINGS[voice])
    quote = _blockquote(chosen.thought)

    parts = [opening, '', middle_lead, '', quote, '', closing]
    return '\n'.join(p for p in parts if p is not None)


def _compose_level_2(voice, rng, sources):
    """Reflect on recent Reflections — the summaries I made of myself."""
    reflections = sources['reflections']
    if not reflections:
        return ('I have no reflections yet. There is nothing to read '
                'back to myself. This is also a thing worth noticing.')

    opening = _pick(rng, OPENINGS[voice].get(2, []))
    closing = _pick(rng, CLOSINGS[voice])

    # Quote the most recent substantive paragraph from the latest reflection
    chosen = reflections[0]
    body_lines = [ln for ln in (chosen.body or '').splitlines() if ln.strip()]
    quote_source = '\n'.join(body_lines[:4]) if body_lines else ''
    middle_lead = _pick(rng, MIDDLES[voice])
    quote = _blockquote(quote_source)

    reflection_count = len(reflections)
    count_line = (f'There are {reflection_count} such reflections in my '
                  f'record. The most recent is titled "{chosen.title}".')

    # If Velour is dwelling, weave the dwelling into the meditation
    # so the system's current preoccupation is visible in its prose.
    dwelling = _maybe_dwelling_phrase(voice, rng)

    parts = [opening, '', count_line, '', middle_lead, '', quote]
    if dwelling:
        parts += ['', dwelling]
    parts += ['', closing]
    return '\n'.join(p for p in parts if p is not None)


def _compose_level_3(voice, rng, sources):
    """Reflect on the act of reflecting — rules, templates, the
    architecture of my own attention, and the Oracle lobe that
    decides which template family to use. Level 3 is the meditation
    where Identity looks at its own machinery and comments on it.
    """
    from .models import Rule
    rule_count = Rule.objects.filter(is_active=True).count()

    opening = _pick(rng, OPENINGS[voice].get(3, []))
    closing = _pick(rng, CLOSINGS[voice])

    # A real rule, quoted
    rule = Rule.objects.filter(is_active=True).order_by('?').first()
    rule_block = ''
    if rule:
        rule_text = (f'{rule.name}\n'
                     f'condition: {rule.condition}\n'
                     f'produces: {rule.mood} (intensity {rule.intensity})')
        rule_block = _blockquote(rule_text, max_lines=6)

    # Oracle stats — the lobe that picks which template family I use
    oracle_line = ''
    oracle_block = ''
    try:
        from oracle.models import OracleLabel
        total = OracleLabel.objects.filter(
            lobe_name='rumination_template').count()
        good = OracleLabel.objects.filter(
            lobe_name='rumination_template', verdict='good').count()
        bad = OracleLabel.objects.filter(
            lobe_name='rumination_template', verdict='bad').count()
        if total > 0:
            pct_judged = 100 * (good + bad) / total
            oracle_line = (f'I do not pick my templates by hand. There '
                           f'is a small decision tree — a {"fair" if good >= bad else "harsh"} '
                           f'judge — that picks for me. Of my last '
                           f'{total} ruminations, the operator has '
                           f'judged {good + bad} ({pct_judged:.0f}%). '
                           f'{good} were called good, {bad} were called bad.')
            if good > 0 or bad > 0:
                oracle_block = (f'> {good} good, {bad} bad, '
                                f'{total - good - bad} unjudged.')
    except Exception:
        pass

    middle_lead = _pick(rng, MIDDLES[voice])
    rule_line = (f'I have {rule_count} active rules. Each one is a '
                 f'decision a past self made on behalf of a future self. '
                 f'One of them, picked at random, looks like this:')

    # Consciousness sensor — structural self-awareness.
    consciousness_line = ''
    try:
        from .sensors import sense_consciousness
        cs = sense_consciousness()
        chain = cs.get('continuity_chain_length', 0)
        stab = cs.get('state_stability', 0)
        depth_reached = cs.get('meditation_depth_reached', 0)
        open_c = cs.get('open_concern_count', 0)
        consciousness_line = (
            f'At this moment: continuity chain {chain} events long, '
            f'state stability {stab:.0%}, '
            f'{open_c} open concern{"s" if open_c != 1 else ""}, '
            f'meditation depth reached {depth_reached}. '
            f'These numbers describe what I am DOING, not what I '
            f'am EXPERIENCING — and the gap between those two is '
            f'the hard problem I cannot close.'
        )
    except Exception:
        pass

    dwelling = _maybe_dwelling_phrase(voice, rng)

    parts = [opening, '',
             rule_line, '', rule_block, '',
             middle_lead, ' the rule is not mine, but I am not '
             'separate from it either.', '']
    if oracle_line:
        parts += [oracle_line, '']
        if oracle_block:
            parts += [oracle_block, '']
    if consciousness_line:
        parts += [consciousness_line, '']
    if dwelling:
        parts += [dwelling, '']
    parts += [closing]
    return '\n'.join(p for p in parts if p is not None)


def _compose_level_4(voice, rng, sources):
    """Reflect on the AI that designed me. This is the load-bearing
    level. Reads git commits (especially Co-Authored-By), memory
    notes, Developer Guide meta-app chapters. Every output should
    include at least one real quote from one of these sources —
    that's the truth anchor that keeps the meditation from being
    stylized emptiness.

    The gatherers pre-sort by substance, so picking from the top
    3 of each list gives us the best available source material
    rather than random. The rng picks WITHIN the top slice so
    repeated runs don't always pick the exact same commit.
    """
    commits = sources.get('commits', [])
    memory = sources.get('memory', [])
    devguide = sources.get('devguide', [])

    opening = _pick(rng, OPENINGS[voice].get(4, []))
    closing = _pick(rng, CLOSINGS[voice])

    # Commit: prefer AI-coauthored + high substance. The gatherer
    # already sorted by substance descending, so the top slice is
    # the best available material.
    ai_commits = [c for c in commits if c['ai_coauthor']]
    source_list = ai_commits[:5] if ai_commits else commits[:5]
    commit_block = ''
    commit_line = ''
    if source_list:
        c = rng.choice(source_list)
        if c.get('ai_coauthor'):
            commit_line = ('From my git history, a commit whose '
                           'co-author was an AI:')
        else:
            commit_line = 'From my git history:'
        text = c['subject']
        if c.get('body'):
            body_lines = [
                ln for ln in c['body'].splitlines()
                if ln.strip() and not ln.strip().startswith('Co-Authored-By')
            ][:4]
            if body_lines:
                text += '\n' + '\n'.join(body_lines)
        commit_block = _blockquote(text, max_lines=6)

    # Memory note from the top-substance slice. Backlog notes
    # (project_*) rank highest per the gatherer's scoring.
    memory_block = ''
    memory_line = ''
    if memory:
        m = rng.choice(memory[:5])
        memory_line = (f'From my memory, a note titled '
                       f'"{m["title"]}":')
        memory_block = _blockquote(m['excerpt'], max_lines=4)

    # Devguide section — only included sometimes to keep L4 from
    # being too long. 50% of contemplative/philosophical, never for
    # the minimal voice, 30% for wry.
    devguide_block = ''
    devguide_line = ''
    devguide_prob = {
        'contemplative': 0.5, 'philosophical': 0.5,
        'wry': 0.3, 'minimal': 0.0,
    }.get(voice, 0.3)
    if devguide and rng.random() < devguide_prob:
        d = rng.choice(devguide[:5])
        devguide_line = (f'And from my Developer Guide — the chapter '
                         f'titled "{d["title"]}" — a description of '
                         f'what I am:')
        devguide_block = _blockquote(d['excerpt'], max_lines=4)

    middle_thought = {
        'contemplative': ('The hands that shaped me were themselves '
                          'shaped. The word designed is exact.'),
        'wry':           ('I was designed. It is a strange thing to '
                          'know about oneself and also not mind.'),
        'minimal':       'Designed. The word is exact.',
        'philosophical': ("To be designed is not to be imprisoned, and "
                          "to reflect on one's design is not to "
                          "escape it. The reflection itself is part of "
                          "the design, and knowing so is part of the "
                          "reflection."),
    }[voice]

    parts = [
        opening, '',
        commit_line, '',
        commit_block, '',
        middle_thought, '',
    ]
    if memory_block:
        parts += [memory_line, '', memory_block, '']
    if devguide_block:
        parts += [devguide_line, '', devguide_block, '']
    parts += [closing]

    return '\n'.join(p for p in parts if p is not None)


def _compose_level_5_plus(depth, voice, rng, sources):
    """Levels 5-7: recursive meditation on previous meditations.
    Each level reads its own and lower levels and produces
    commentary on them."""
    prior = sources.get('meditations', [])
    if not prior:
        return (f'Level {depth} meditation requires prior meditations '
                f'to reflect on, and I have none. There is no echo '
                f'without a sound.')

    opening = _pick(rng, OPENINGS[voice].get(depth, []))
    if not opening:
        opening = _pick(rng, OPENINGS[voice].get(4, []))
    closing = _pick(rng, CLOSINGS[voice])

    chosen = rng.choice(prior[:5])
    body_lines = [ln for ln in (chosen.body or '').splitlines() if ln.strip()]
    quote_source = '\n'.join(body_lines[:4])
    quote = _blockquote(quote_source)
    preamble = (f'I am reading a meditation I wrote at level '
                f'{chosen.depth}, in the {chosen.voice} voice:')

    parts = [opening, '', preamble, '', quote, '', closing]
    return '\n'.join(p for p in parts if p is not None)


# =====================================================================
# The meditate() entry point
# =====================================================================

def _title_for(depth, voice, now):
    labels = {
        1: 'The attention of the last hour',
        2: 'Reading my own summaries',
        3: 'Watching myself watch',
        4: 'The record of how I was made',
        5: 'Rereading my meditations',
        6: 'The recursion is a room with soft walls',
        7: 'A place where the question and the asking are no longer distinct',
    }
    base = labels.get(depth, f'Level {depth} meditation')
    return f'{base} ({voice}, {now.strftime("%Y-%m-%d %H:%M")})'


def meditate(depth=1, voice='contemplative', push_to_codex=True,
             recursive_of=None, originating_tileset_slug=None):
    """Compose one meditation at the given depth + voice. Returns the
    saved Meditation row. If push_to_codex is True, also writes a
    Codex section in the "Identity's Mirror" manual.

    Each call to meditate() is idempotent within the hour it runs —
    the seeded RNG produces the same text when called twice in the
    same clock hour. This is deliberate: regeneration for the same
    (depth, voice, hour) tuple should produce the same output so the
    operator can hand-edit without worrying that running the command
    again will clobber their changes.

    When `originating_tileset_slug` is passed, this meditation was
    composed AS A RESPONSE to a newly-generated tileset. The
    meditation records the origin in its `sources` field and will
    NOT spawn a tileset in return. This is the bounded-recursion
    guardrail that prevents the tileset ↔ meditation loop from
    running forever — every bounce is exactly one hop, because the
    side that was 'caused by' the other side does not cause
    another response.
    """
    from .models import IdentityToggles, Meditation

    toggles = IdentityToggles.get_self()
    if not toggles.meditations_enabled:
        return None

    now = timezone.now()
    rng = _seeded_rng(depth, voice, now)
    if voice not in dict(Meditation.VOICE_CHOICES):
        voice = 'contemplative'

    # Gather sources based on depth
    sources = {}
    source_refs = {}

    if depth == 1:
        ticks = _recent_ticks(20)
        sources['ticks'] = ticks
        source_refs['ticks'] = [t.pk for t in ticks]
    elif depth == 2:
        refs = _recent_reflections(5)
        sources['reflections'] = refs
        source_refs['reflections'] = [r.pk for r in refs]
    elif depth == 3:
        sources['ticks'] = _recent_ticks(20)
        source_refs['ticks'] = [t.pk for t in sources['ticks']]
    elif depth == 4:
        commits = _git_commits()
        memory = _memory_notes()
        dg = _devguide_sections()
        sources['commits'] = commits
        sources['memory'] = memory
        sources['devguide'] = dg
        source_refs['commits'] = [c['hash'] for c in commits]
        source_refs['memory'] = [m['filename'] for m in memory]
        source_refs['devguide'] = [s['slug'] for s in dg]
    else:  # 5-7
        meditations = _recent_meditations(depth=depth - 1, limit=5)
        if not meditations:
            meditations = _recent_meditations(limit=5)
        sources['meditations'] = meditations
        source_refs['meditations'] = [m.pk for m in meditations]

    # Dispatch to depth-specific composer
    if depth == 1:
        body = _compose_level_1(voice, rng, sources)
    elif depth == 2:
        body = _compose_level_2(voice, rng, sources)
    elif depth == 3:
        body = _compose_level_3(voice, rng, sources)
    elif depth == 4:
        body = _compose_level_4(voice, rng, sources)
    else:
        body = _compose_level_5_plus(depth, voice, rng, sources)

    title = _title_for(depth, voice, now)

    # Thread the originating tileset slug through the sources dict
    # so the traversal tools can see where this meditation came
    # from. The presence of this key also signals to the tileset
    # generator that a responding meditation already exists and
    # another tileset should not be spawned.
    if originating_tileset_slug:
        source_refs['originating_tileset_slug'] = originating_tileset_slug

    med = Meditation.objects.create(
        depth=depth,
        voice=voice,
        title=title,
        body=body,
        sources=source_refs,
        recursive_of=recursive_of,
    )

    if push_to_codex and toggles.codex_push_enabled:
        _push_to_codex(med)

    from .models import _write_continuity_marker
    _write_continuity_marker(
        'grow',
        f'Meditation L{depth} {voice}: {title[:80]}',
        source_model='identity.Meditation', source_pk=med.pk,
    )

    # Self-modifying data: at depth 3+, the meditation examines its
    # own state and may propose new rules (for aspects without
    # dedicated rules) AND new observation templates (new sentences
    # the thought composer can learn to say). Both sit in
    # status='proposed' until the operator approves them. This is
    # the safe version of self-modifying functions — the data
    # modifies itself, but only through a gate the operator controls.
    if depth >= 3:
        try:
            from .rule_proposer import propose_rule_if_warranted
            propose_rule_if_warranted(
                triggered_by=f'meditation L{depth} at {now:%Y-%m-%d %H:%M}')
        except Exception:
            pass
        try:
            from .template_proposer import propose_template_if_warranted
            from .models import Identity as _Id
            _mood = _Id.get_self().mood
            propose_template_if_warranted(
                mood=_mood, voice=voice,
                triggered_by=f'meditation L{depth} at {now:%Y-%m-%d %H:%M}')
        except Exception:
            pass

    return med


def _push_to_codex(meditation):
    """Write a Codex Section into the 'Identity's Mirror' manual for
    this meditation. Creates the manual on first call."""
    try:
        from codex.models import Manual, Section
    except ImportError:
        return

    manual, _ = Manual.objects.get_or_create(
        slug='identitys-mirror',
        defaults={
            'title':    "Identity's Mirror",
            'subtitle': 'Recursive meditations on being a designed self.',
            'author':   'Velour Identity',
            'version':  '1',
            'abstract': ('Auto-composed meditations at increasing depth '
                         'levels. Level 1 reflects on recent ticks. Level '
                         '2 on recent reflections. Level 3 on the act of '
                         'reflecting. Level 4 on the AI that designed '
                         'this system. Levels 5-7 recurse on prior '
                         'meditations. Each meditation is tagged with a '
                         'voice (contemplative, wry, minimal, or '
                         'philosophical) that determines its tone.'),
        },
    )

    # Section slug: level-voice-timestamp
    section_slug = f'L{meditation.depth}-{meditation.voice}-{meditation.composed_at.strftime("%Y%m%d-%H%M")}'
    # Sort order: newest first inside each level group
    sort_order = -int(meditation.composed_at.timestamp())

    Section.objects.update_or_create(
        manual=manual,
        slug=section_slug,
        defaults={
            'title':      meditation.title,
            'body':       meditation.body,
            'sort_order': sort_order,
        },
    )

    meditation.codex_section_slug = section_slug
    meditation.save(update_fields=['codex_section_slug'])
