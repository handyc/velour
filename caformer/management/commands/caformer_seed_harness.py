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
