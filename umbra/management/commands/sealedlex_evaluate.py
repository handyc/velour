"""Stage 2 of the SealedLex protocol: evaluate encrypted ops on the
compute provider (ALICE etc.).

Runs on the cluster.  Inputs: just the .sealedpack archive.  No keys
file involved.  This process must never be given access to a secret
key — that's the privacy property.

Output: a .sealedresult archive shipped back to the researcher's
laptop for stage 3 (decrypt).
"""
import time

from django.core.management.base import BaseCommand, CommandError

from umbra import sealedlex_protocol


class Command(BaseCommand):
    help = ('Evaluate encrypted op chunks on the compute provider.  '
            'Has access to the public package only — no secret key.')

    def add_arguments(self, parser):
        parser.add_argument('package_path',
            help='path to the input .sealedpack')
        parser.add_argument('-o', '--output', required=True,
            help='where to write the output .sealedresult')

    def handle(self, *args, **opts):
        with open(opts['package_path'], 'rb') as fp:
            pkg_bytes = fp.read()

        def progress(done, total):
            self.stdout.write(
                f'  chunk {done}/{total}', ending='\n')
            self.stdout.flush()

        t0 = time.monotonic()
        try:
            out = sealedlex_protocol.evaluate(pkg_bytes, progress_cb=progress)
        except ValueError as exc:
            raise CommandError(str(exc))
        elapsed_ms = int((time.monotonic() - t0) * 1000)

        with open(opts['output'], 'wb') as fp:
            fp.write(out['results_bytes'])

        m  = out['manifest']
        sm = out['source_manifest']
        self.stdout.write(self.style.SUCCESS(
            f'wrote {opts["output"]}  ({len(out["results_bytes"]):,} B)'
        ))
        self.stdout.write(
            f'  ran {sm["op"]["op"]} on {m["n_chunks"]} chunks  '
            f'in {elapsed_ms} ms\n'
            f'  source profile: {sm["profile"]}  cell_len {sm["cell_len"]}\n'
            f'  source manifest sha256: {m["source_manifest_sha256"][:16]}...'
        )
