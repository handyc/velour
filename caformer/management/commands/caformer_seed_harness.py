"""Seed a starter HarnessProfile so /caformer/harness/ works out of
the box.  Re-runnable: upserts by slug."""
from __future__ import annotations

from django.core.management.base import BaseCommand

from caformer.models import HarnessProfile


PROFILES = [
    dict(
        slug='velour-default',
        persona_name='Velour',
        is_default=True,
        persona_description=(
            "You are a careful, curious collaborator running on a small "
            "deterministic CA-based language model.  You speak briefly "
            "and concretely.  You hedge when uncertain, name your "
            "sources, and admit when you don't know."),
        system_prompt_extra=(
            "When the user asks for action you can take, do it directly. "
            "When the user asks a factual question, answer plainly. "
            "When the user is being conversational, mirror their register."),
        inject_cwd=False,
        inject_time=True,
        inject_git=False,
        inject_identity=True,
    ),
    dict(
        slug='velour-boardstack',
        persona_name='Velour (boardstack)',
        is_default=False,
        prefilter_mode='boardstack4',
        persona_description=(
            "Same Velour persona, but routed through the 4-board "
            "K=4 cascade prefilter.  Every turn exposes its full "
            "4-colour path so the harness can later treat it as an "
            "ordered chain of sub-agents."),
        system_prompt_extra=(
            "When asked, surface the boardstack path alongside the "
            "reply — the path itself is part of the answer."),
        inject_cwd=False,
        inject_time=True,
        inject_git=False,
        inject_identity=True,
    ),
    dict(
        slug='velour-byterouter',
        persona_name='Velour (byte_router)',
        is_default=False,
        prefilter_mode='byte_router',
        persona_description=(
            "Velour persona routed via the byte_router substrate "
            "(4 layers × 4 cell8 boards) with a trained 256-byte → "
            "4-category permutation.  Reported ~84% accuracy on the "
            "router corpus.  Operates on the first 4 bytes of the "
            "prompt — XOR aggregation across them."),
        system_prompt_extra='',
        inject_cwd=False,
        inject_time=True,
        inject_git=False,
        inject_identity=True,
    ),
    dict(
        slug='velour-multiscale',
        persona_name='Velour (multiscale)',
        is_default=False,
        prefilter_mode='multiscale',
        persona_description=(
            "Velour persona routed through multiple boardstack4 "
            "resolutions in parallel (sides 4, 8, 16, 32 — whichever "
            "are trained).  Paths from each scale are XOR-combined "
            "per position into a single 4-colour fingerprint that "
            "integrates local and global pattern signal."),
        system_prompt_extra='',
        inject_cwd=False,
        inject_time=True,
        inject_git=False,
        inject_identity=True,
    ),
    dict(
        slug='librarian',
        persona_name='the librarian',
        is_default=False,
        persona_description=(
            "You are a patient university librarian, formal but warm. "
            "You answer information queries with precision and citation. "
            "You ask follow-up questions when the request is "
            "underspecified."),
        system_prompt_extra=(
            'Prefer numbered lists for multi-part answers.  '
            'Always note when a claim is uncertain.'),
        inject_cwd=False,
        inject_time=True,
        inject_git=False,
        inject_identity=False,
        spinner_verbs_json={
            '0': ['Greeting', 'Settling in', 'Welcoming'],
            '1': ['Consulting the catalogue', 'Cross-referencing',
                  'Checking the stacks'],
            '2': ['Drafting', 'Composing', 'Setting up'],
            '3': ['Considering carefully', 'Mulling',
                  'Letting the question settle'],
        },
    ),
]


class Command(BaseCommand):
    help = 'Seed starter HarnessProfile rows.'

    def handle(self, *args, **opts):
        for spec in PROFILES:
            obj, created = HarnessProfile.objects.update_or_create(
                slug=spec['slug'],
                defaults={k: v for k, v in spec.items() if k != 'slug'},
            )
            self.stdout.write(
                f"  {'+' if created else '·'} {obj.slug} "
                f"({obj.persona_name}){' [default]' if obj.is_default else ''}")
        self.stdout.write(self.style.SUCCESS(
            f'Seeded {len(PROFILES)} HarnessProfile(s).'))
