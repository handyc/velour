"""Pact-shared question → private external LLM response.

Generates a deterministic prompt from a spoeqi pact (via Phase 2a's
LoRA-perturbed CausalLM), then submits it to an OpenAI-compatible
``identity.LLMProvider``. Both parties holding the same pact
compute the same prompt; each gets their own private response.

Use ``--provider echo`` (or omit ``--provider``) to skip the
external call and just inspect the deterministic prompt.
"""

from __future__ import annotations

from django.core.management.base import BaseCommand, CommandError

from spoeqi.models import Pact


class Command(BaseCommand):
    help = ("Ask a pact-shared question of an external non-deterministic LLM. "
            "Both parties compute the same prompt; each gets their own answer.")

    def add_arguments(self, parser):
        parser.add_argument('pact_slug')
        parser.add_argument(
            '--provider', default=None,
            help='Name of an identity.LLMProvider to query. Omit (or pass '
                 '"echo") to skip the external call and only show the '
                 'deterministic prompt.')
        parser.add_argument(
            '--seed-prompt', default=None,
            help='Override the seed text fed to the deterministic LLM.')
        parser.add_argument(
            '--external-system-prompt', default=None,
            help='Override the system prompt sent to the external LLM.')
        parser.add_argument('--component', type=int, default=0)
        parser.add_argument('--generation', type=int, default=0)
        parser.add_argument('--model', default='distilgpt2',
                            help='Internal deterministic CausalLM.')
        parser.add_argument('--scale', type=float, default=0.1)
        parser.add_argument('--rank', type=int, default=4)
        parser.add_argument('--max-new-tokens', type=int, default=60,
                            help='Tokens to generate on the deterministic side.')
        parser.add_argument('--max-external-tokens', type=int, default=400,
                            help='Tokens cap for the external LLM response.')
        parser.add_argument('--target', default=None,
                            help='Dotted path to the deterministic-model weight to perturb.')

    def handle(self, *args, **opts):
        try:
            pact = Pact.objects.get(slug=opts['pact_slug'])
        except Pact.DoesNotExist:
            raise CommandError(f"No pact with slug {opts['pact_slug']!r}")

        from spoeqi.oracle import (
            ask_oracle,
            DEFAULT_SEED_PROMPT,
            DEFAULT_EXTERNAL_SYSTEM_PROMPT,
        )

        provider = opts['provider']
        if provider == 'echo':
            provider = None

        make_kwargs = dict(
            seed_prompt=opts['seed_prompt'] or DEFAULT_SEED_PROMPT,
            component=opts['component'],
            generation=opts['generation'],
            model_name=opts['model'],
            scale=opts['scale'],
            rank=opts['rank'],
            max_new_tokens=opts['max_new_tokens'],
            target_weight=opts['target'],
        )

        self.stdout.write(self.style.NOTICE(
            f"pact={pact.slug} provider={provider or '(echo)'} "
            f"internal-model={opts['model']} gen={opts['generation']}"))

        result = ask_oracle(
            pact,
            provider_slug=provider,
            external_system_prompt=opts['external_system_prompt']
                                    or DEFAULT_EXTERNAL_SYSTEM_PROMPT,
            max_external_tokens=opts['max_external_tokens'],
            **make_kwargs,
        )

        self.stdout.write(self.style.NOTICE('--- shared deterministic prompt ---'))
        self.stdout.write(result['prompt'])
        self.stdout.write('')

        if result['response']:
            self.stdout.write(self.style.NOTICE(
                f"--- external response "
                f"({result['model']}, {result['latency_ms']} ms, "
                f"{result['tokens_in']}/{result['tokens_out']} tok) ---"))
            self.stdout.write(result['response'])
        elif provider:
            raise CommandError(
                f"external call failed: {result['error']}")
        else:
            self.stdout.write(self.style.WARNING(
                'no provider queried; only the shared prompt is shown above'))
