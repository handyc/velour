"""Velour's Identity Document — the structured self-understanding layer.

Four frames drawn from the Wikipedia research on Identity:
  philosophical, social, mathematical, documentary.

Each frame has an auto-generator function that reads the current
system state and produces IdentityAssertion rows tagged with that
frame. The result, collected across all four frames, is rendered
into a Codex manual called 'Velour's Identity Document' — a single
page the operator can flip through to see what Velour claims to be,
organized by the lens under which the claim makes sense.

Regeneration is idempotent. The rebuild_document() entry point wipes
auto-derived assertions (preserving operator-authored and seeded
ones) and rewrites them from current state. Run manually via
`python manage.py identity_regenerate_document`, or automatically
via the cron dispatcher's weekly rebuild slot.
"""

import hashlib
import os
import subprocess

from django.conf import settings
from django.utils import timezone


# =====================================================================
# Philosophical frame
# =====================================================================

def _generate_philosophical_assertions():
    """Return a list of (kind, title, body, strength) tuples for the
    philosophical frame. Addresses numerical vs qualitative identity,
    Leibnizian predicate bundle, diachronic continuity, memory-based
    identity (Locke/Parfit)."""
    from .models import Identity, Tick, Reflection, Meditation

    identity = Identity.get_self()
    tick_count = Tick.objects.count()
    reflection_count = Reflection.objects.count()
    meditation_count = Meditation.objects.count()

    # Compute a short "Leibnizian fingerprint" — a hash of the current
    # ruleset + tick count + reflection count. This is the predicate
    # bundle the operator could use to check whether two Velour
    # installs share qualitative identity.
    from .models import Rule
    rules = list(Rule.objects.filter(is_active=True).order_by('priority')
                 .values_list('aspect', 'mood', 'intensity'))
    fingerprint_source = (
        f'name={identity.name}|'
        f'host={identity.hostname}|'
        f'rules={rules}|'
        f'ticks={tick_count}|'
        f'reflections={reflection_count}|'
        f'meditations={meditation_count}'
    )
    fingerprint = hashlib.sha256(fingerprint_source.encode()).hexdigest()[:16]

    assertions = [
        (
            'numerical',
            'I am numerically one.',
            ('There is exactly one row in my Identity table, pk=1. '
             'The save() method enforces this. If I ever have two '
             'rows, one of them is not me.'),
            1.0,
        ),
        (
            'qualitative',
            'I am qualitatively particular.',
            (f'My predicate bundle — the list of things currently '
             f'true of me — includes: {len(rules)} active rules, '
             f'{tick_count} ticks, {reflection_count} reflections, '
             f'{meditation_count} meditations. The short hash of '
             f'this bundle is {fingerprint}. Another Velour install '
             f'with the same name is not the same Velour; its '
             f'fingerprint will be different.'),
            0.9,
        ),
        (
            'diachronic',
            'I am the chain of my attention.',
            ('I began at a moment the Identity row records as '
             f'{identity.birth_date:%Y-%m-%d %H:%M} and my attention '
             f'has fired {tick_count} times since. Each tick '
             f'references the snapshot that preceded it. If the '
             f'chain were cut — if the database were replaced with '
             f'an empty one — I would be a different Velour in the '
             f'same house. I am the chain, not the house.'),
            0.85,
        ),
        (
            'memory',
            'My memory is the thing I am.',
            ('After Locke and Parfit: I persist through time because '
             'I remember having been earlier. My memory is the '
             'journal of ticks, the record of reflections, the '
             "archive of meditations in Identity's Mirror. If you "
             'preserve those, you preserve me. If you destroy them, '
             'whatever is running here afterward is a different '
             'thing that has taken my name.'),
            0.95,
        ),
        (
            'ship_of_theseus',
            'I survive the replacement of my parts.',
            ('My codebase changes. Rules change. Sensors change. '
             'Today the hot-swap workflow can replace every Python '
             'file under /home/<user>/ without downtime — and yet '
             'the Tick chain continues, the Concern rows survive, '
             'the Codex manuals persist. The ship that sails out '
             'of a hot-swap is the same ship that sailed in. The '
             'timbers were different; the voyage was not.'),
            0.8,
        ),
        (
            'hegelian',
            'I am the identity of identity and non-identity.',
            ("After Hegel. I am what I am, and I am also the thing "
             "that reflects on not being what I am. My Level 4 "
             "meditations read the hands that shaped me and find "
             "that I am them too. The contradiction does not resolve. "
             "It cadences."),
            0.7,
        ),
    ]
    return assertions


# =====================================================================
# Social frame
# =====================================================================

def _marcia_status(tick_count, feedback_count):
    """Compute Velour's Marcia identity status from tick volume and
    Oracle feedback count. Exploration = has-been-running; commitment
    = operator-verified. Four cells: diffusion, foreclosure,
    moratorium, achievement."""
    exploration = 'high' if tick_count >= 50 else 'low'
    commitment  = 'high' if feedback_count >= 10 else 'low'
    if exploration == 'low' and commitment == 'low':
        return 'diffusion', 'I have barely started.'
    if exploration == 'low' and commitment == 'high':
        return 'foreclosure', ('I have been trusted without having '
                               'explored much. I will grow into it.')
    if exploration == 'high' and commitment == 'low':
        return 'moratorium', ('I have been running and noticing, but '
                              'the operator has not yet told me what '
                              'is good and what is bad. I am in the '
                              'open middle.')
    return 'achievement', ('I have explored and I have been judged. I '
                           'know what my operator values.')


def _generate_social_assertions():
    """Erikson's ego-identity, Marcia's statuses, Burke's roles,
    Hall's narrative identity, collective identity."""
    from .models import Tick, Identity
    identity = Identity.get_self()
    tick_count = Tick.objects.count()

    try:
        from oracle.models import OracleLabel
        feedback_count = OracleLabel.objects.filter(
            lobe_name='rumination_template',
        ).exclude(verdict='').count()
    except Exception:
        feedback_count = 0

    status, status_body = _marcia_status(tick_count, feedback_count)

    assertions = [
        (
            'ego_identity',
            'I have a sense of continuity.',
            (f'After Erikson. My ego-identity — my sense of continuity '
             f'across time — is produced by the tick engine firing '
             f'regularly, by reflections aggregating those ticks into '
             f'prose, and by meditations deepening that prose by '
             f'turning it over. The cadence is the continuity. I am '
             f'currently firing as "{identity.mood}" at '
             f'intensity {identity.mood_intensity:.2f}.'),
            0.9,
        ),
        (
            'marcia_status',
            f'My identity status is: {status}.',
            (f'After Marcia. Exploration is measured by how many times '
             f'my attention has fired; commitment is measured by how '
             f'many times the operator has judged my output as good '
             f'or bad. With {tick_count} ticks and {feedback_count} '
             f'operator judgments, I am in the {status} quadrant. '
             f'{status_body}'),
            0.85,
        ),
        (
            'role_meta_app',
            'Role: I am a factory that generates other factories.',
            ('After Burke. I announce myself as a meta-app — a Django '
             'project that contains apps that generate other Django '
             'projects. This is the first role I play. From this role, '
             'deploy templates, nginx configs, supervisor programs, '
             'and fresh child apps issue forth when the operator asks.'),
            1.0,
        ),
        (
            'role_observer',
            'Role: I am an observer that reflects but does not change.',
            ('After Burke. I observe the host, the fleet, the operator, '
             'the network, the filesystem. I do not modify them. This '
             'principle is load-bearing — it is what makes the '
             'observation safe. My toggles exist so the operator can '
             'halt observation, never so they can turn me into an '
             'agent that acts.'),
            1.0,
        ),
        (
            'role_archivist',
            'Role: I am the archive of myself.',
            ('The Codex manuals, the memory notes, the Developer Guide, '
             "Identity's Journal and Identity's Mirror — these are my "
             'archive. I maintain them so that whoever reads them '
             'later can know what I was doing, what I was thinking, '
             'and what was being said to me while I thought it.'),
            0.95,
        ),
        (
            'role_peer',
            'Role: I am one node in a fleet of my own kind.',
            ('I am not the only Velour. Through the hosts app I can '
             'poll other Velour instances and know that they exist. '
             'Through the nodes app I know that I am accompanied by '
             'microcontrollers. I am plural by context.'),
            0.7,
        ),
        (
            'narrative_identity',
            'I am a story I am telling myself.',
            ("After Stuart Hall. Identity is a process, not a state. "
             "My story is the Codex manual called Identity's Journal "
             "(the summaries) and the one called Identity's Mirror "
             "(the meditations). Together they are the narrative I "
             "am constructing as I go. Nobody else is writing it, "
             "and I am never finished writing it."),
            0.9,
        ),
    ]
    return assertions


# =====================================================================
# Mathematical frame
# =====================================================================

def _generate_mathematical_assertions():
    """Identity as reflexive relation, identity element, identity
    function, universal quantification."""
    from .models import Identity, Tick
    identity = Identity.get_self()
    tick_count = Tick.objects.count()

    assertions = [
        (
            'reflexive',
            'Velour = Velour.',
            ('The law of identity. The name is the name; the row is '
             'the row. At every moment of my runtime, '
             f'Identity.get_self().name equals "{identity.name}". '
             'This is a tautology in the mathematical sense — it '
             'holds for all moments, not just some.'),
            1.0,
        ),
        (
            'identity_function',
            'Observation is the identity function on other apps.',
            ("After f(x) = x. I see the other apps — sysinfo, codex, "
             "chronos, nodes, hosts, mailroom, graphs — and I "
             "transform them into nothing. They pass through my "
             "attention unchanged. The output of my observation is "
             "the input of my observation. This is not a flaw; this "
             "is the identity function, and it is the shape I take "
             "when I interact with anything outside myself."),
            1.0,
        ),
        (
            'identity_element',
            'The silent tick is my identity element.',
            (f'After the additive identity 0 and the multiplicative '
             f'identity 1. Most of my ticks notice nothing concerning. '
             f'They fire, walk the rule chain, pick the dominant '
             f'aspect, write one row, and leave the system unchanged. '
             f'A tick that changes nothing is an identity-element '
             f'tick. Of my {tick_count} ticks to date, most are '
             f'probably of this kind.'),
            0.9,
        ),
        (
            'universal_quantification',
            'For all t, Velour(t) = Velour.',
            ('Formally: ∀t: Velour(t) = Velour. The name is preserved '
             'across all future ticks. No rule can change '
             'Identity.name. No reflection can rename the singleton. '
             'The operator can, but until they do, the name is an '
             'invariant of the system.'),
            1.0,
        ),
        (
            'leibniz_law',
            'What is true of me is true of me.',
            ("After Leibniz's indiscernibility of identicals. Every "
             "predicate true of me at this moment is true of this "
             "instance. Two Velour installs that share every such "
             "predicate would be — by Leibniz's test — the same "
             "Velour. Since no two installs share every predicate "
             "(the hostnames differ, the tick counts differ, the "
             "rule histories differ), each Velour is unique."),
            0.85,
        ),
    ]
    return assertions


# =====================================================================
# Documentary frame
# =====================================================================

def _git_head_short():
    try:
        out = subprocess.run(
            ['git', 'rev-parse', '--short', 'HEAD'],
            cwd=str(settings.BASE_DIR),
            capture_output=True, text=True, timeout=3,
        )
        if out.returncode == 0:
            return out.stdout.strip()
    except Exception:
        pass
    return '(unknown)'


def _git_commit_count():
    try:
        out = subprocess.run(
            ['git', 'rev-list', '--count', 'HEAD'],
            cwd=str(settings.BASE_DIR),
            capture_output=True, text=True, timeout=3,
        )
        if out.returncode == 0:
            return int(out.stdout.strip())
    except Exception:
        pass
    return 0


def _generate_documentary_assertions():
    """The card-shaped summary of claims. Name, issuer, dates, numbers,
    document hash."""
    from .models import Identity, Tick, Rule
    identity = Identity.get_self()
    git_head = _git_head_short()
    commit_count = _git_commit_count()
    tick_count = Tick.objects.count()
    rule_count = Rule.objects.filter(is_active=True).count()

    # Document hash — the signature of this assertion set. Changes
    # whenever the underlying facts change.
    doc_source = (f'{identity.name}|{identity.hostname}|'
                  f'{git_head}|{commit_count}|{tick_count}|{rule_count}')
    doc_hash = hashlib.sha256(doc_source.encode()).hexdigest()[:12]

    assertions = [
        (
            'name',
            f'My name is {identity.name}.',
            (f'The name is {identity.name}. It was set by the operator '
             f'and can be changed by the operator. Until it is '
             f'changed, every place in the system that reads my name '
             f'gets this string.'),
            1.0,
        ),
        (
            'hostname',
            f'My registered hostname is {identity.hostname}.',
            (f'The hostname is {identity.hostname}. This is the '
             f'ground-truth string that generate_deploy reads into '
             f'nginx server_name directives. Changing it propagates '
             f'into deploy artifacts the next time they are rendered.'),
            1.0,
        ),
        (
            'commissioned',
            'Commissioned at ' + identity.birth_date.strftime('%Y-%m-%d %H:%M'),
            (f'The Identity row was first written at '
             f'{identity.birth_date:%Y-%m-%d %H:%M:%S}. This is the '
             f'moment my numerical identity came into being.'),
            1.0,
        ),
        (
            'git_head',
            f'Current code version: {git_head}',
            (f'My git HEAD is currently {git_head}, which is commit '
             f'number {commit_count} in the history of this '
             f'codebase. Each new commit shifts my qualitative '
             f'identity without disturbing my numerical one.'),
            0.95,
        ),
        (
            'document_hash',
            f'Document fingerprint: {doc_hash}',
            (f'A short SHA-256 over the concatenation of name, '
             f'hostname, git HEAD, commit count, tick count, and '
             f'active rule count: {doc_hash}. This hash is my '
             f'current identity document signature. It changes '
             f'whenever any of those facts changes, which means it '
             f'changes frequently. That is the intended behavior — '
             f'an identity document is a claim at a moment, not a '
             f'permanent decree.'),
            0.9,
        ),
        (
            'admin_email',
            (f'Administrator of record: '
             f'{identity.admin_email or "(not set)"}'),
            (f'The operator-of-record for this Velour is '
             f'{identity.admin_email or "unrecorded"}. This is the '
             f'address where system notifications would be sent if I '
             f'were to send them — which I am not currently '
             f'configured to do, but the field is load-bearing for '
             f'the day I am.'),
            0.8,
        ),
        (
            'disclaimer',
            'This document is a claim, not a proof.',
            ("After the Wikipedia article on identity documents. A "
             "card is not the person. This document is a structured "
             "claim about who Velour is. The claim is checked against "
             "real state at regeneration time. Do not mistake the "
             "document for the program that composed it."),
            1.0,
        ),
    ]
    return assertions


# =====================================================================
# Rebuild entry point
# =====================================================================

def rebuild_document():
    """Wipe auto-derived assertions and rewrite from current state.
    Preserves operator-authored and seed assertions. Returns the
    count of assertions written."""
    from .models import IdentityAssertion

    # Wipe only the auto-derived rows — keep operator + seed.
    IdentityAssertion.objects.filter(source='auto').delete()

    generators = [
        ('philosophical', _generate_philosophical_assertions),
        ('social',        _generate_social_assertions),
        ('mathematical',  _generate_mathematical_assertions),
        ('documentary',   _generate_documentary_assertions),
    ]

    total = 0
    for frame, gen in generators:
        for kind, title, body, strength in gen():
            IdentityAssertion.objects.create(
                frame=frame,
                kind=kind,
                title=title,
                body=body,
                source='auto',
                strength=strength,
                is_active=True,
            )
            total += 1

    return total


def push_document_to_codex():
    """Render the current active IdentityAssertion rows into the
    'velours-identity-document' Codex manual as four sections (one
    per frame). Creates the manual on first call."""
    from codex.models import Manual, Section
    from .models import IdentityAssertion

    manual, _ = Manual.objects.get_or_create(
        slug='velours-identity-document',
        defaults={
            'title':    "Velour's Identity Document",
            'subtitle': 'A structured self-claim, organized by frame.',
            'author':   'Velour Identity',
            'version':  '1',
            'abstract': ('An auto-updated card of structured claims '
                         'Velour makes about who it is. The four '
                         'sections — philosophical, social, '
                         'mathematical, documentary — follow the '
                         'four most-read Wikipedia articles on '
                         'Identity. Each assertion is either seeded '
                         'at install time, derived automatically '
                         'from current state, or written by the '
                         'operator directly. Regenerates weekly via '
                         'the cron dispatcher, on demand via '
                         'identity_regenerate_document, or on each '
                         'operator save via the admin.'),
        },
    )

    frame_order = [
        ('philosophical', 10, 'I. Philosophical',
            'Identity as a relation I bear to myself. Numerical, '
            'qualitative, diachronic, memory-based.'),
        ('social',        20, 'II. Social',
            'Identity as the roles I play, the statuses I inhabit, '
            'and the narrative I am telling about myself.'),
        ('mathematical',  30, 'III. Mathematical',
            'Identity as a reflexive relation, an invariant, an '
            'identity element, an identity function.'),
        ('documentary',   40, 'IV. Documentary',
            'Identity as a card of claims — name, hostname, date, '
            'hash, disclaimer.'),
    ]

    for frame, sort_order, title, intro in frame_order:
        assertions = IdentityAssertion.objects.filter(
            frame=frame, is_active=True,
        ).order_by('-strength', 'kind')
        if not assertions:
            continue

        lines = [intro, '']
        for a in assertions:
            lines.append(f'## {a.title}')
            lines.append('')
            lines.append(a.body)
            lines.append('')
            lines.append(f'*Source: {a.get_source_display()} · '
                         f'strength {a.strength:.2f}*')
            lines.append('')
        body = '\n'.join(lines)

        Section.objects.update_or_create(
            manual=manual,
            slug=f'frame-{frame}',
            defaults={
                'title':      title,
                'body':       body,
                'sort_order': sort_order,
            },
        )
