"""Wang-tile + class-4 hex CA buffer-band prototype (CLI front-end).

Exercises the experiment in `taxon.wang.run_experiment` and prints
results to stdout. The same logic powers the in-browser lab at
`/taxon/wang/`.

    venv/bin/python manage.py wang_proto
    venv/bin/python manage.py wang_proto --sha 349fd4ca336d --tile 16 \\
        --buffer 2 --steps 20 --candidates 200
    venv/bin/python manage.py wang_proto --sha 0447aa52f220 \\
        --stable-color 1 --density 0.10
    venv/bin/python manage.py wang_proto --pin-buffer            # pin outer
    venv/bin/python manage.py wang_proto --pin-buffer --pin-seams # pin all

Re-run with the same seed to reproduce. --png writes a side-by-side
comparison image to wang_proto_<sha>.png.
"""
from __future__ import annotations

import os

import numpy as np
from django.core.management.base import BaseCommand, CommandError

from automaton.packed import PackedRuleset
from taxon.models import Classification, Rule
from taxon.wang import Params, run_experiment


def _ascii_grid(g: np.ndarray) -> str:
    chars = '.+*#'
    rows = []
    for r in range(g.shape[0]):
        offset = ' ' if (r % 2) else ''
        rows.append(offset + ' '.join(chars[int(c) & 3] for c in g[r]))
    return '\n'.join(rows)


def _save_png(path: str, frames: list[tuple[str, np.ndarray]]) -> None:
    import matplotlib
    matplotlib.use('Agg')
    import matplotlib.pyplot as plt
    n = len(frames)
    fig, axes = plt.subplots(1, n, figsize=(3 * n, 3.2))
    if n == 1:
        axes = [axes]
    cmap = matplotlib.colors.ListedColormap(
        ['#101010', '#2a8c5b', '#d8a93a', '#c04a4a'])
    for ax, (title, g) in zip(axes, frames):
        ax.imshow(g, cmap=cmap, vmin=0, vmax=3, interpolation='nearest')
        ax.set_title(title, fontsize=9)
        ax.set_xticks([])
        ax.set_yticks([])
    fig.tight_layout()
    fig.savefig(path, dpi=110)
    plt.close(fig)


class Command(BaseCommand):
    help = 'Wang-tile + CA buffer-band composition prototype.'

    def add_arguments(self, parser):
        parser.add_argument('--sha', default='349fd4ca336d')
        parser.add_argument('--tile', type=int, default=16)
        parser.add_argument('--buffer', type=int, default=2)
        parser.add_argument('--steps', type=int, default=20)
        parser.add_argument('--candidates', type=int, default=200)
        parser.add_argument('--density', type=float, default=0.35)
        parser.add_argument('--seed', type=int, default=42)
        parser.add_argument('--stable-color', type=int, default=None)
        parser.add_argument('--pin-buffer', action='store_true')
        parser.add_argument('--pin-seams', action='store_true')
        parser.add_argument('--png', action='store_true')

    def handle(self, *args, **opts):
        rule = Rule.objects.filter(sha1__startswith=opts['sha']).first()
        if rule is None:
            raise CommandError(f'No rule with sha1 prefix "{opts["sha"]}".')
        cl = (Classification.objects.filter(rule=rule)
              .order_by('-confidence').first())
        packed = PackedRuleset(n_colors=rule.n_colors, data=bytes(rule.genome))

        if opts['pin_buffer'] and opts['pin_seams']:
            mode = 'pin_all'
        elif opts['pin_buffer']:
            mode = 'pin_outer'
        else:
            mode = 'natural'

        params = Params(
            size=opts['tile'], buffer=opts['buffer'], steps=opts['steps'],
            candidates=opts['candidates'], density=opts['density'],
            seed=opts['seed'], stable_color=opts['stable_color'], mode=mode,
        )

        self.stdout.write(self.style.NOTICE(
            f'Rule {rule.sha1[:12]}  K={rule.n_colors}  '
            f'class={cl.wolfram_class if cl else "?"} '
            f'(conf={cl.confidence:.2f})' if cl else ''))
        self.stdout.write(
            f'mode={mode}  tile={params.size}x{params.size}  '
            f'buffer={params.buffer}  T={params.steps}  '
            f'candidates={params.candidates}  density={params.density:.2f}')

        try:
            res = run_experiment(packed, params)
        except ValueError as exc:
            raise CommandError(str(exc))

        self.stdout.write(self.style.SUCCESS(
            f'Buffer-clean candidates: {res["clean"]} / {res["candidates"]}'))
        if not res['ok']:
            self.stdout.write(self.style.WARNING(res['reason']))
            return

        for slot, t in enumerate(res['tiles']):
            self.stdout.write(
                f'  tile {slot} = candidate #{t["candidate_id"]},  '
                f'interior motion={t["motion"]}')

        self.stdout.write('')
        self.stdout.write(self.style.NOTICE('Composition check:'))
        labels = ['top-left', 'top-right', 'bot-left', 'bot-right']
        for i, (label, d) in enumerate(zip(labels, res['diffs'])):
            sum_d = sum(d)
            verdict = 'IDENTICAL' if sum_d == 0 else f'DRIFT (Σ={sum_d})'
            self.stdout.write(
                f'  {label:9s}  per-step diffs={d}  → {verdict}')

        self.stdout.write('')
        self.stdout.write(
            f'Total non-zero cells on internal seams across {res["steps"]+1}'
            f' steps: {res["seam_total"]}')

        self.stdout.write('')
        if res['verdict'] == 'identical':
            self.stdout.write(self.style.SUCCESS(
                'VERDICT: composition theorem HOLDS — each tile inside the '
                '2×2 join behaves identically to the standalone tile and '
                'the seam stays at substrate.'))
        elif res['verdict'] == 'identical-with-seam-traffic':
            self.stdout.write(self.style.WARNING(
                'VERDICT: tiles match standalone bit-for-bit but seam '
                'carries traffic — protocol-band approach would be valid '
                'with a non-zero edge protocol.'))
        else:
            self.stdout.write(self.style.ERROR(
                'VERDICT: composition theorem FAILS — buffer-clean alone '
                'is not sufficient for this rule + mode.'))

        if opts['png']:
            png_path = f'wang_proto_{rule.sha1[:12]}.png'
            tiles = [np.array(t['initial'], dtype=np.uint8)
                     for t in res['tiles']]
            standalone_last = np.array(
                res['tiles'][0]['traj'][-1], dtype=np.uint8)
            joined0 = np.array(res['joined']['initial'], dtype=np.uint8)
            joinedT = np.array(res['joined']['traj'][-1], dtype=np.uint8)
            _save_png(png_path, [
                ('tile 0  t=0', tiles[0]),
                (f'tile 0  t={params.steps}', standalone_last),
                ('joined  t=0', joined0),
                (f'joined  t={params.steps}', joinedT),
            ])
            self.stdout.write(
                f'Wrote {png_path} ({os.path.getsize(png_path)} bytes)')

        self.stdout.write('')
        self.stdout.write(self.style.NOTICE(
            f'Joined grid at t={params.steps} (.=0, +=1, *=2, #=3):'))
        joinedT = np.array(res['joined']['traj'][-1], dtype=np.uint8)
        self.stdout.write(_ascii_grid(joinedT))
