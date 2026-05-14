"""Phase 2a end-to-end demo.

Loads a small CausalLM, applies a deterministic LoRA derived from a
pact's keystream at the chosen (component, generation), and greedy-
decodes the given prompt. Two parties running this with the same
pact see identical output.

Defaults to distilgpt2 (82M params, ~330 MB download on first use).
"""

from __future__ import annotations

from django.core.management.base import BaseCommand, CommandError

from spoeqi.models import Pact


class Command(BaseCommand):
    help = ("Greedy-decode a prompt with a model whose weights are "
            "perturbed by a spoeqi pact's keystream.")

    def add_arguments(self, parser):
        parser.add_argument('pact_slug')
        parser.add_argument('--prompt', required=True)
        parser.add_argument('--component', type=int, default=0)
        parser.add_argument('--generation', type=int, default=0)
        parser.add_argument('--model', default='distilgpt2')
        parser.add_argument('--rank', type=int, default=4)
        parser.add_argument('--scale', type=float, default=1e-3)
        parser.add_argument('--max-new-tokens', type=int, default=40)
        parser.add_argument(
            '--target',
            default='transformer.h.5.attn.c_proj.weight',
            help='Dotted path to the Parameter to perturb.')
        parser.add_argument(
            '--verify-determinism', action='store_true',
            help='Run generation twice; report whether outputs are byte-identical.')
        parser.add_argument(
            '--no-perturb', action='store_true',
            help='Skip LoRA application — sanity baseline.')

    def handle(self, *args, **opts):
        try:
            pact = Pact.objects.get(slug=opts['pact_slug'])
        except Pact.DoesNotExist:
            raise CommandError(f"No pact with slug {opts['pact_slug']!r}")

        from spoeqi.llm_lora import generate

        kwargs = dict(
            pact=pact,
            prompt=opts['prompt'],
            component=opts['component'],
            generation=opts['generation'],
            model_name=opts['model'],
            rank=opts['rank'],
            scale=0.0 if opts['no_perturb'] else opts['scale'],
            max_new_tokens=opts['max_new_tokens'],
            target_weight=opts['target'],
        )

        self.stdout.write(self.style.NOTICE(
            f"pact={pact.slug} comp={opts['component']} "
            f"gen={opts['generation']} model={opts['model']} "
            f"rank={opts['rank']} scale={kwargs['scale']}"))
        text1 = generate(**kwargs)
        self.stdout.write(text1)

        if opts['verify_determinism']:
            text2 = generate(**kwargs)
            if text1 == text2:
                self.stdout.write(self.style.SUCCESS(
                    '✓ deterministic — two runs identical'))
            else:
                self.stdout.write(self.style.ERROR(
                    '✗ NON-deterministic — runs diverged'))
                for i, (a, b) in enumerate(zip(text1, text2)):
                    if a != b:
                        self.stdout.write(
                            f'  first diff at offset {i}: {a!r} vs {b!r}')
                        break
