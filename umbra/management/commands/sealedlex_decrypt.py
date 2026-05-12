"""Stage 3 of the SealedLex protocol: decrypt the results on the
researcher's laptop using the local secret-keys file.

Needs three things:
  - the original .sealedpack (for the client specs in server.zip)
  - the .sealedresult that came back from the compute provider
  - the local secret-keys file from the encrypt stage

Output: a CSV.  Optionally overlays results onto the original source
CSV (so untouched columns survive); otherwise emits a minimal
two-column CSV with row index + value.
"""
import json

from django.core.management.base import BaseCommand, CommandError

from umbra import sealedlex_protocol


class Command(BaseCommand):
    help = ('Decrypt a .sealedresult into a plaintext CSV using the '
            'researcher\'s local secret-keys file.')

    def add_arguments(self, parser):
        parser.add_argument('package_path',
            help='the .sealedpack used to produce the results '
                 '(needed for client specs)')
        parser.add_argument('results_path',
            help='the .sealedresult coming back from the compute provider')
        parser.add_argument('--keys', required=True,
            help='path to the local secret-keys file from encrypt')
        parser.add_argument('--original-csv',
            help='optional: original source CSV.  When supplied, '
                 'untouched columns survive; otherwise emits a minimal '
                 'row,value CSV.')
        parser.add_argument('-o', '--output', required=True,
            help='where to write the decrypted CSV')

    def handle(self, *args, **opts):
        with open(opts['package_path'], 'rb') as fp:
            pkg_bytes = fp.read()
        with open(opts['results_path'], 'rb') as fp:
            res_bytes = fp.read()
        with open(opts['keys'], 'rb') as fp:
            keys_bytes = fp.read()
        original_csv = None
        if opts['original_csv']:
            with open(opts['original_csv'], 'r', encoding='utf-8') as fp:
                original_csv = fp.read()

        try:
            out = sealedlex_protocol.decrypt(
                package_bytes=pkg_bytes,
                results_bytes=res_bytes,
                keys_bytes=keys_bytes,
                original_csv=original_csv,
            )
        except ValueError as exc:
            raise CommandError(str(exc))

        with open(opts['output'], 'w', encoding='utf-8') as fp:
            fp.write(out['output_csv'])

        self.stdout.write(self.style.SUCCESS(
            f'wrote {opts["output"]}  ({len(out["output_csv"])} B)'
        ))
        self.stdout.write(f'  decoded {sum(len(c) for c in out["plain_chunks"])} '
                          f'cells across {len(out["plain_chunks"])} chunks')
