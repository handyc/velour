"""Stage 1 of the SealedLex protocol: encrypt a linguistic CSV locally.

Runs on the researcher's laptop.  Produces:

  - <output>.sealedpack  — portable archive shipped to the compute
                           provider (ALICE etc.); contains server
                           artefact + evaluation keys + encrypted
                           input chunks.  NO secret material.
  - <keys-out>           — secret key bytes; stays on the researcher's
                           laptop forever.

After encryption: scp the .sealedpack to ALICE, run
`manage.py sealedlex_evaluate` there, scp the result back, then
`manage.py sealedlex_decrypt` locally.

Example op JSON:
    {"op": "count_class", "col": 0, "target": 1, "dst_col": 1}
"""
import json

from django.core.management.base import BaseCommand, CommandError

from umbra import sealedlex_protocol


class Command(BaseCommand):
    help = ('Encrypt a CSV column for sealed evaluation by a compute '
            'provider.  Produces a .sealedpack + a local secret-keys '
            'file.')

    def add_arguments(self, parser):
        parser.add_argument('csv_path', help='path to input CSV')
        parser.add_argument('op_json_path',
            help='path to JSON file containing a single op dict, e.g. '
                 '{"op": "count_class", "col": 0, "target": 1, '
                 '"dst_col": 1}')
        parser.add_argument('--profile', default='ascii',
            help='language profile slug: ascii / devanagari / geez')
        parser.add_argument('-o', '--output', required=True,
            help='where to write the .sealedpack archive')
        parser.add_argument('--keys-out', required=True,
            help='where to write the local secret-keys file (do not '
                 'ship this anywhere)')
        parser.add_argument('--cap', type=int, default=None,
            help='cap the selection at N cells (default: full CSV)')

    def handle(self, *args, **opts):
        with open(opts['csv_path'], 'r', encoding='utf-8') as fp:
            csv_text = fp.read()
        with open(opts['op_json_path'], 'r', encoding='utf-8') as fp:
            op = json.load(fp)
        if isinstance(op, list):
            if len(op) != 1:
                raise CommandError(
                    'v1 protocol supports exactly one op per package; '
                    f'got {len(op)}.  Re-encrypt the same column once '
                    'per op for now.')
            op = op[0]
        if not isinstance(op, dict) or 'op' not in op:
            raise CommandError('op JSON must be a dict with an "op" key')

        try:
            out = sealedlex_protocol.encrypt(
                csv_text=csv_text,
                op=op,
                profile_slug=opts['profile'],
                chunk_cap=opts['cap'],
            )
        except ValueError as exc:
            raise CommandError(str(exc))

        with open(opts['output'], 'wb') as fp:
            fp.write(out['package_bytes'])
        with open(opts['keys_out'], 'wb') as fp:
            fp.write(out['keys_bytes'])

        m = out['manifest']
        self.stdout.write(self.style.SUCCESS(
            f'wrote {opts["output"]}  ({len(out["package_bytes"]):,} B)\n'
            f'wrote {opts["keys_out"]}  ({len(out["keys_bytes"]):,} B  — KEEP LOCAL)'
        ))
        self.stdout.write(
            f'  profile:  {m["profile"]}  '
            f'(alphabet {m["profile_alphabet"]})\n'
            f'  op:       {m["op"]["op"]}\n'
            f'  cells:    {m["n_cells"]} in {m["n_chunks"]} chunks\n'
            f'  cell_len: {m["cell_len"]}\n'
            f'  sizes:    server.zip {m["sizes"]["server_zip"]:,} B · '
            f'eval.keys {m["sizes"]["eval_keys"]:,} B · '
            f'inputs {m["sizes"]["total_inputs_bytes"]:,} B'
        )
