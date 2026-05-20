"""manage.py alice_bundle_qrpair_vocab — emit a Slurm bundle that
trains one positional QRPair per word across an sbatch array.

Examples:

  # Smoke test: 8-word echo, 4 array tasks
  manage.py alice_bundle_qrpair_vocab --slug vocab-smoke-8 \\
        --vocab-words 'hi,hey,yo,sup,hello,bye,thanks,please' \\
        --strategy echo --array-size 4

  # Real run: 65,536 echo pairs, 128 array tasks (512 pairs each)
  manage.py alice_bundle_qrpair_vocab --slug vocab-65k-echo \\
        --vocab-file /path/to/words.txt --vocab-limit 65536 \\
        --strategy echo --array-size 128 --time 04:00:00

  # Hand-curated pairs (one per line, prompt<TAB>expected)
  manage.py alice_bundle_qrpair_vocab --slug greetings-tsv \\
        --pairs-tsv pairs.tsv --array-size 8
"""
from __future__ import annotations

from pathlib import Path

from django.conf import settings
from django.core.management.base import BaseCommand, CommandError


class Command(BaseCommand):
    help = 'Generate a Slurm bundle for QRPair-per-word vocabulary training.'

    def add_arguments(self, parser):
        parser.add_argument('--slug', required=True,
                            help='bundle slug — also the sbatch job name')
        parser.add_argument('--vocab-file', type=str, default='',
                            help='one word per line; comments # OK')
        parser.add_argument('--vocab-words', type=str, default='',
                            help='inline comma-separated words')
        parser.add_argument('--vocab-limit', type=int, default=0,
                            help='cap vocab at this size (0 = all)')
        parser.add_argument('--pairs-tsv', type=str, default='',
                            help='TSV file: prompt<TAB>expected (one per line). '
                                 'When provided, --strategy is ignored.')
        parser.add_argument('--strategy', type=str, default='echo',
                            help='echo|hello|reverse|first3|upper|lower|synonym — '
                                 'response generator when no --pairs-tsv given. '
                                 '`synonym` uses a lookup table; see '
                                 '--synonyms-file.')
        parser.add_argument('--synonyms-file', type=str, default='',
                            help='TSV lookup for the `synonym` strategy. '
                                 'Default: conduit/alice/data/mini_thesaurus.tsv')
        parser.add_argument('--array-size', type=int, default=32,
                            help='sbatch array task count')
        parser.add_argument('--pop', type=int, default=32)
        parser.add_argument('--gens', type=int, default=24)
        parser.add_argument('--polish', type=int, default=200)
        parser.add_argument('--bonus', type=float, default=4.0)
        parser.add_argument('--n-blocks', type=int, default=1)
        parser.add_argument('--time', dest='time_limit',
                            default='04:00:00',
                            help='per-task wall time')
        parser.add_argument('--mem', dest='mem_per_task', default='2G')
        parser.add_argument('--cpus-per-task', type=int, default=1)
        parser.add_argument('--seed-base', type=lambda x: int(x, 0),
                            default=0xCA1B5E11)
        parser.add_argument('--ssh-user', type=str, default='username',
                            help='operator overrides this at gen time')
        parser.add_argument('--ssh-host', type=str,
                            default='alice')

    def handle(self, **opts):
        from conduit.alice.qrpair_vocab import (BundleParams,
                                                    generate_bundle)
        vocab: list[str] = []
        explicit: list[tuple[str, str]] = []
        if opts['pairs_tsv']:
            tsv = Path(opts['pairs_tsv'])
            if not tsv.exists():
                raise CommandError(f'pairs-tsv not found: {tsv}')
            for ln in tsv.read_text().splitlines():
                if not ln.strip() or ln.startswith('#'):
                    continue
                if '\t' not in ln:
                    raise CommandError(f'TSV missing tab on line: {ln!r}')
                p, e = ln.split('\t', 1)
                explicit.append((p.strip(), e.strip()))
        else:
            if opts['vocab_file']:
                path = Path(opts['vocab_file'])
                if not path.exists():
                    raise CommandError(f'vocab-file not found: {path}')
                for ln in path.read_text().splitlines():
                    w = ln.strip()
                    if not w or w.startswith('#'):
                        continue
                    vocab.append(w)
            if opts['vocab_words']:
                vocab.extend(w.strip() for w in
                                opts['vocab_words'].split(',')
                                if w.strip())
            if not vocab:
                raise CommandError(
                    'no vocabulary — supply --vocab-file, --vocab-words, '
                    'or --pairs-tsv')
            if opts['vocab_limit']:
                vocab = vocab[:opts['vocab_limit']]
            # Deduplicate while preserving order
            seen = set()
            vocab = [w for w in vocab if not (w in seen or seen.add(w))]

        params = BundleParams(
            slug=opts['slug'], vocab=vocab,
            response_strategy=opts['strategy'],
            explicit_pairs=explicit,
            synonyms_tsv=opts.get('synonyms_file', '') or '',
            array_size=max(1, opts['array_size']),
            pop=opts['pop'], gens=opts['gens'],
            polish=opts['polish'], bonus=opts['bonus'],
            n_blocks=opts['n_blocks'],
            time_limit=opts['time_limit'],
            mem_per_task=opts['mem_per_task'],
            cpus_per_task=opts['cpus_per_task'],
            seed_base=opts['seed_base'],
            ssh_user=opts['ssh_user'],
            ssh_host=opts['ssh_host'])

        bundles_dir = (Path(settings.BASE_DIR) / 'conduit' / 'alice'
                          / 'bundles' / opts['slug'])
        out = generate_bundle(bundles_dir, params)
        self.stdout.write(self.style.SUCCESS(
            f'wrote bundle: {out}\n'
            f'  pairs: {len(explicit) or len(vocab)}  '
            f'array: {params.array_size}\n'
            f'next:  bash {out}/push.sh'))
