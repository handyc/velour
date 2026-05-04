"""Wang-tile + class-4 hex CA buffer-band prototype.

Tests the composition theorem proposed by handyz:

    If every Wang tile maintains a clean (all-zero) buffer band along
    its edges over T simulation steps, then any 2x2 (or larger) join
    of those tiles also has a clean seam, and each tile's interior
    dynamics inside the join are bit-for-bit identical to the same
    tile run standalone.

The prototype:

  1. Loads a class-4 quiescent K=4 hex CA rule from the taxon DB.
  2. Generates random tile interiors with a 2-cell all-zero buffer band.
  3. Filters to "buffer-clean" tiles — ones whose buffer stays 0 over T steps.
  4. Composes 2x2 of those tiles into a 32x32 hex grid.
  5. Simulates the joined grid for T steps.
  6. Compares each tile's standalone trajectory against the joined trajectory.
  7. Reports leak rates and the verdict (theorem holds / fails).

    venv/bin/python manage.py wang_proto
    venv/bin/python manage.py wang_proto --sha 349fd4ca336d --tile 16 --buffer 2
                                        --steps 20 --candidates 200

Re-run with the same seed to reproduce. Optional --png writes a side-by-side
comparison image per tile to wang_proto_<sha>.png.
"""
from __future__ import annotations

import os

import numpy as np
from django.core.management.base import BaseCommand, CommandError

from automaton.packed import PackedRuleset
from taxon.engine import _step
from taxon.models import Classification, Rule


def _step_grid(grid: np.ndarray, packed: PackedRuleset) -> np.ndarray:
    """One CA tick. Thin wrapper around taxon.engine._step."""
    return _step(grid, packed)


def _make_tile(rng: np.random.Generator, size: int, buffer: int,
               density: float = 0.35,
               n_colors: int = 4,
               stable_color: int | None = None) -> np.ndarray:
    """Build a tile = `size`x`size` hex grid with a `buffer`-cell wide
    all-zero border and a random interior at the given non-zero density.

    If ``stable_color`` is given, the interior only ever contains 0 or
    that color — useful for rules with a single-cell still life on that
    color (the only color that won't immediately seed runaway dynamics).
    """
    g = np.zeros((size, size), dtype=np.uint8)
    inner = size - 2 * buffer
    if inner <= 0:
        return g
    if stable_color is None:
        interior = rng.integers(0, n_colors, size=(inner, inner), dtype=np.uint8)
    else:
        interior = (rng.random((inner, inner)) < density).astype(np.uint8) * stable_color
        g[buffer:buffer + inner, buffer:buffer + inner] = interior
        return g
    # Sparsify — class-4 rules behave better with low initial density.
    mask = rng.random((inner, inner)) > density
    interior[mask] = 0
    g[buffer:buffer + inner, buffer:buffer + inner] = interior
    return g


def _buffer_mask(size: int, buffer: int) -> np.ndarray:
    """Boolean mask of the buffer-band cells (True on the band)."""
    m = np.zeros((size, size), dtype=bool)
    m[:buffer, :] = True
    m[-buffer:, :] = True
    m[:, :buffer] = True
    m[:, -buffer:] = True
    return m


def _simulate(grid: np.ndarray, packed: PackedRuleset,
              steps: int,
              pin_mask: np.ndarray | None = None) -> np.ndarray:
    """Return the full trajectory: shape (steps+1, H, W).

    If ``pin_mask`` is given, after every step the cells where the mask
    is True are forced back to 0. Models a Dirichlet-zero buffer band.
    """
    traj = np.zeros((steps + 1,) + grid.shape, dtype=np.uint8)
    traj[0] = grid
    g = grid
    for t in range(steps):
        g = _step_grid(g, packed)
        if pin_mask is not None:
            g = g.copy()
            g[pin_mask] = 0
        traj[t + 1] = g
    return traj


def _max_buffer_leak(traj: np.ndarray, mask: np.ndarray) -> int:
    """Max non-zero count on the buffer band across all timesteps."""
    leak = 0
    for t in range(traj.shape[0]):
        n = int(((traj[t] != 0) & mask).sum())
        if n > leak:
            leak = n
    return leak


def _compose_2x2(tiles: list[np.ndarray]) -> np.ndarray:
    """Stack four tiles as [[A, B], [C, D]] into a single grid."""
    a, b, c, d = tiles
    top = np.concatenate([a, b], axis=1)
    bot = np.concatenate([c, d], axis=1)
    return np.concatenate([top, bot], axis=0)


def _ascii_grid(g: np.ndarray) -> str:
    chars = '.+*#'
    rows = []
    for r in range(g.shape[0]):
        offset = ' ' if (r % 2) else ''
        rows.append(offset + ' '.join(chars[int(c) & 3] for c in g[r]))
    return '\n'.join(rows)


def _save_png(path: str, frames: list[tuple[str, np.ndarray]]) -> None:
    """Optional matplotlib output — only imported on demand."""
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
        parser.add_argument('--sha', default='349fd4ca336d',
                            help='sha1 prefix of the rule to test (default: '
                                 'a high-confidence class-4 quiescent K=4 rule).')
        parser.add_argument('--tile', type=int, default=16,
                            help='Tile side in cells (default 16).')
        parser.add_argument('--buffer', type=int, default=2,
                            help='Buffer-band thickness in cells (default 2).')
        parser.add_argument('--steps', type=int, default=20,
                            help='Simulation horizon T (default 20).')
        parser.add_argument('--candidates', type=int, default=200,
                            help='Random tile candidates to evaluate.')
        parser.add_argument('--density', type=float, default=0.35,
                            help='Non-zero density of the random interior.')
        parser.add_argument('--seed', type=int, default=42)
        parser.add_argument('--stable-color', type=int, default=None,
                            help='Restrict interior cells to this single '
                                 'colour (must be one whose isolated cell is '
                                 'a still life under the rule).')
        parser.add_argument('--pin-buffer', action='store_true',
                            help='After every step, force the OUTER buffer '
                                 'band of standalone tiles + joined grid '
                                 'back to zero. Internal seams of the join '
                                 'are NOT pinned (tiles still see neighbours'
                                 ' through them). Shows that naive pinning '
                                 'lets joined dynamics drift from standalone.')
        parser.add_argument('--pin-seams', action='store_true',
                            help='Combined with --pin-buffer, also pin the '
                                 'internal seams of the join. Restores '
                                 'standalone-=-joined identity, but '
                                 'eliminates all cross-tile communication.')
        parser.add_argument('--png', action='store_true',
                            help='Write a side-by-side PNG to '
                                 'wang_proto_<sha>.png.')

    def handle(self, *args, **opts):
        sha_pref = opts['sha']
        rule = Rule.objects.filter(sha1__startswith=sha_pref).first()
        if rule is None:
            raise CommandError(f'No rule with sha1 prefix "{sha_pref}".')
        cl = Classification.objects.filter(rule=rule).order_by('-confidence').first()

        packed = PackedRuleset(n_colors=rule.n_colors, data=bytes(rule.genome))
        # Sanity check the quiescent property.
        q = packed.get(0, [0, 0, 0, 0, 0, 0])
        if q != 0:
            raise CommandError(
                f'Rule {rule.sha1[:12]} is not quiescent on zero (q={q}).')

        size = opts['tile']
        buffer = opts['buffer']
        steps = opts['steps']
        n_cand = opts['candidates']
        density = opts['density']
        rng = np.random.default_rng(opts['seed'])

        self.stdout.write(self.style.NOTICE(
            f'Rule {rule.sha1[:12]}  K={rule.n_colors}  '
            f'class={cl.wolfram_class if cl else "?"} '
            f'(conf={cl.confidence:.2f})' if cl else ''))
        self.stdout.write(
            f'Tile {size}x{size}, buffer={buffer}, T={steps}, '
            f'candidates={n_cand}, density={density:.2f}')

        mask = _buffer_mask(size, buffer)
        pin_mask = mask if opts['pin_buffer'] else None
        stable_color = opts['stable_color']
        # ---------- Step 1: search for buffer-clean tiles ----------
        clean: list[tuple[int, int, np.ndarray, np.ndarray]] = []
        for i in range(n_cand):
            tile = _make_tile(rng, size, buffer, density,
                              n_colors=rule.n_colors,
                              stable_color=stable_color)
            traj = _simulate(tile, packed, steps, pin_mask=pin_mask)
            leak = _max_buffer_leak(traj, mask)
            if leak == 0:
                # Reject only tiles that are entirely all-zero — a still-life
                # interior is fine (and is in fact what most class-2 rules
                # admit). interior_motion is reported in the stats so the
                # user can see whether they got lifeless or computing tiles.
                if (tile != 0).any():
                    interior_motion = int((traj[steps] != traj[0]).sum())
                    clean.append((i, interior_motion, tile, traj))

        self.stdout.write(self.style.SUCCESS(
            f'Buffer-clean candidates: {len(clean)} / {n_cand}'))
        if len(clean) < 4:
            self.stdout.write(self.style.WARNING(
                'Need ≥4 buffer-clean tiles for a 2×2 join. Try larger '
                '--candidates, smaller --density, or a different --sha.'))
            return

        # Pick the 4 tiles with the most interior motion (the ones doing
        # the most "computing" while still keeping the buffer clean).
        clean.sort(key=lambda t: -t[1])
        chosen = clean[:4]
        for slot, (idx, motion, _, _) in enumerate(chosen):
            self.stdout.write(
                f'  tile {slot} = candidate #{idx}, interior motion={motion}')

        tiles = [c[2] for c in chosen]
        trajs = [c[3] for c in chosen]

        # ---------- Step 2: compose 2x2 and simulate ----------
        joined = _compose_2x2(tiles)
        # Joined buffer band runs along the OUTSIDE of the 2x2. Every
        # internal seam is interior to the join. With --pin-buffer set,
        # we can either pin only the OUTER band (realistic — tiles are
        # supposed to talk through their seams) or pin every seam too
        # (proves tiles can be made identical to standalone, at the cost
        # of all inter-tile signal flow). The default is "outer only".
        if pin_mask is not None:
            joined_pin = np.zeros((2 * size, 2 * size), dtype=bool)
            joined_pin[:buffer, :] = True
            joined_pin[-buffer:, :] = True
            joined_pin[:, :buffer] = True
            joined_pin[:, -buffer:] = True
            if opts['pin_seams']:
                # Also pin the internal seams — both sides of each tile-tile
                # boundary, `buffer` cells thick.
                joined_pin[size - buffer:size + buffer, :] = True
                joined_pin[:, size - buffer:size + buffer] = True
        else:
            joined_pin = None
        joined_traj = _simulate(joined, packed, steps, pin_mask=joined_pin)

        H, W = size, size
        offsets = [(0, 0), (0, W), (H, 0), (H, W)]
        positions = ['top-left', 'top-right', 'bot-left', 'bot-right']

        self.stdout.write('')
        self.stdout.write(self.style.NOTICE('Composition check:'))
        all_ok = True
        for slot, ((dr, dc), pos) in enumerate(zip(offsets, positions)):
            standalone = trajs[slot]
            embedded = joined_traj[:, dr:dr + H, dc:dc + W]
            diffs = (standalone != embedded).sum(axis=(1, 2))
            seam_leak = int(((joined_traj[:, dr:dr + H, dc:dc + W] != 0)
                            & mask).sum())
            verdict = ('IDENTICAL' if diffs.sum() == 0
                       else f'DRIFT (Σ={int(diffs.sum())})')
            self.stdout.write(
                f'  {pos:9s}  per-step diffs={list(int(d) for d in diffs)}  '
                f'seam-leak={seam_leak}  → {verdict}')
            if diffs.sum() != 0:
                all_ok = False

        # The whole-join seam check: are interior boundaries between tiles
        # all zero across all timesteps?
        seam_count = 0
        # Vertical seam at column W (between cols W-1, W) on full join
        for t in range(joined_traj.shape[0]):
            seam_count += int((joined_traj[t, :, W - 1] != 0).sum())
            seam_count += int((joined_traj[t, :, W] != 0).sum())
            seam_count += int((joined_traj[t, H - 1, :] != 0).sum())
            seam_count += int((joined_traj[t, H, :] != 0).sum())

        self.stdout.write('')
        self.stdout.write(
            f'Total non-zero seam cells across all {steps + 1} steps: '
            f'{seam_count}')

        self.stdout.write('')
        if all_ok and seam_count == 0:
            self.stdout.write(self.style.SUCCESS(
                'VERDICT: composition theorem HOLDS for these tiles. '
                'Each tile inside the 2×2 join behaves identically to the '
                'standalone tile, and the seam stays at substrate.'))
        else:
            self.stdout.write(self.style.ERROR(
                'VERDICT: composition theorem FAILS — buffer-clean alone '
                'is insufficient for this rule/tile combination.'))

        # ---------- Step 3: optional PNG output ----------
        if opts['png']:
            png_path = f'wang_proto_{rule.sha1[:12]}.png'
            frames = [
                ('tile 0  t=0', tiles[0]),
                (f'tile 0  t={steps}', trajs[0][steps]),
                ('joined  t=0', joined),
                (f'joined  t={steps}', joined_traj[steps]),
            ]
            _save_png(png_path, frames)
            self.stdout.write(f'Wrote {png_path} ({os.path.getsize(png_path)} bytes)')

        # ---------- Step 4: ASCII snapshot of joined grid at t=steps ----
        self.stdout.write('')
        self.stdout.write(self.style.NOTICE(
            f'Joined grid at t={steps} (.=0, +=1, *=2, #=3):'))
        self.stdout.write(_ascii_grid(joined_traj[steps]))
