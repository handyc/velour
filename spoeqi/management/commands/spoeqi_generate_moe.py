"""Phase 2b end-to-end demo.

4-expert MoE on a small CausalLM, where each expert is a CA-derived
LoRA on a target weight, and the per-token router is a softmax over
keystream-derived logits from a 5th CA component.

Two parties running this with the same pact see identical output.
"""

from __future__ import annotations

from django.core.management.base import BaseCommand, CommandError

from spoeqi.models import Pact


class Command(BaseCommand):
    help = ("Greedy-decode a prompt with a 4-expert MoE whose experts "
            "and per-token router are derived from a spoeqi pact.")

    def add_arguments(self, parser):
        parser.add_argument('pact_slug')
        parser.add_argument('--prompt', required=True)
        parser.add_argument('--experts', default='0,1,2,3',
                            help='Comma-separated CA component indices for the experts.')
        parser.add_argument('--routing-component', type=int, default=4)
        parser.add_argument('--generation', type=int, default=0)
        parser.add_argument('--model', default='distilgpt2')
        parser.add_argument('--rank', type=int, default=4)
        parser.add_argument('--scale', type=float, default=0.1)
        parser.add_argument('--max-new-tokens', type=int, default=40)
        parser.add_argument(
            '--target',
            default='transformer.h.5.attn.c_proj.weight',
            help='Dotted path to the Parameter to perturb.')
        parser.add_argument(
            '--verify-determinism', action='store_true',
            help='Run generation twice; report whether outputs are byte-identical.')

    def handle(self, *args, **opts):
        try:
            pact = Pact.objects.get(slug=opts['pact_slug'])
        except Pact.DoesNotExist:
            raise CommandError(f"No pact with slug {opts['pact_slug']!r}")

        experts = tuple(int(x) for x in opts['experts'].split(','))

        from spoeqi.llm_moe import generate_moe

        kwargs = dict(
            pact=pact,
            prompt=opts['prompt'],
            expert_components=experts,
            routing_component=opts['routing_component'],
            generation=opts['generation'],
            model_name=opts['model'],
            rank=opts['rank'],
            scale=opts['scale'],
            max_new_tokens=opts['max_new_tokens'],
            target_weight=opts['target'],
        )

        self.stdout.write(self.style.NOTICE(
            f"pact={pact.slug} experts={experts} "
            f"router={opts['routing_component']} gen={opts['generation']} "
            f"model={opts['model']} rank={opts['rank']} scale={opts['scale']}"))
        text1 = generate_moe(**kwargs)
        self.stdout.write(text1)

        if opts['verify_determinism']:
            text2 = generate_moe(**kwargs)
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
