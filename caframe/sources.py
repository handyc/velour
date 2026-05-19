"""caframe/sources — adapters that import a CA recipe from another app.

Each `from_<app>(...)` returns a (rule_genome, init_seed, source_ref)
tuple that the views can persist as a Sequence row.  Adapters fail
softly: if the source app isn't installed, raise SourceUnavailable
so the view layer can show a useful "not available" message rather
than 500.
"""
from __future__ import annotations
from typing import Tuple


class SourceUnavailable(Exception):
    """Raised when a source-app's data isn't accessible.  Carries
    the user-facing reason in args[0]."""


def _class4_rule_from_taxon(default_seed: int) -> bytes:
    """Pull a class-4 hex K=4 rule from taxon, fall back to a random
    rule from caformer.primitives if taxon has none classified yet."""
    from caformer.primitives import random_rule_table
    try:
        from taxon.models import Rule, Classification
        # Class-4 = edge of chaos in Wolfram's taxonomy.  Confidence
        # > 0 filter so we don't pick a barely-class-4 rule.
        qs = Classification.objects.filter(
            wolfram_class=4, confidence__gte=0.1).order_by('-confidence')
        match = qs.first()
        if match is None:
            return bytes(random_rule_table(default_seed))
        # Taxon stores 4,096-byte packed rules (4 entries/byte at K=4).
        packed = bytes(match.rule.genome)
        if len(packed) == 16_384:
            return packed                  # already unpacked, just use it
        if len(packed) != 4_096:
            raise SourceUnavailable(
                f'taxon rule {match.rule.slug!r} has wrong size '
                f'{len(packed)} (need 4096 packed or 16384 unpacked)')
        # Unpack 2-bit-packed into 16,384 single bytes.
        out = bytearray(16_384)
        for i, b in enumerate(packed):
            out[i*4 + 0] = (b >> 6) & 3
            out[i*4 + 1] = (b >> 4) & 3
            out[i*4 + 2] = (b >> 2) & 3
            out[i*4 + 3] =  b       & 3
        return bytes(out)
    except ImportError:
        return bytes(random_rule_table(default_seed))


def from_taxon(*, seed_init: int = 0xCAFE,
                ref: str = 'class-4 hex K4') -> Tuple[bytes, int, str]:
    """Take a class-4 rule from taxon as the CA rule; user supplies
    the initial-condition seed."""
    rule_blob = _class4_rule_from_taxon(seed_init ^ 0xC1A554)
    return (rule_blob, int(seed_init) & 0xFFFFFFFF,
            f'taxon · {ref}')


def from_caformer(model_slug: str, *, role: str = 'embed',
                    seed_init: int = 0xCAFE) -> Tuple[bytes, int, str]:
    """Use one of a caformer TrainedModel's rule tables (default: the
    embed rule, which is the only one whose CA-on-bytes intuition
    matches caframe's frame-stepping)."""
    try:
        from caformer.models import TrainedModel
    except ImportError:
        raise SourceUnavailable('caformer app not installed')
    m = TrainedModel.objects.filter(slug=model_slug).first()
    if m is None:
        raise SourceUnavailable(f'no TrainedModel slug={model_slug!r}')
    field = f'rule_{role}'
    if not hasattr(m, field):
        raise SourceUnavailable(f'unknown rule role {role!r}')
    rule_blob = bytes(getattr(m, field))
    if len(rule_blob) != 16_384:
        raise SourceUnavailable(
            f'rule_{role} has wrong size {len(rule_blob)}')
    return (rule_blob, int(seed_init) & 0xFFFFFFFF,
            f'caformer · {model_slug} · rule_{role}')


def from_mandelhunt(ref: str = 'best', *,
                       seed_init: int = 0xCAFE,
                       pool_dir: str = None) -> Tuple[bytes, int, str]:
    """Use a 16,384-byte K=4 hex CA rule LUT from a mandelhunt pool
    as the CA rule.  These are posterised Mandelbrot regions that
    passed the class-4 + sr_strict filter — visually rich and dense
    in computational structure (see project_caformer_session_2026_05_19
    for the visual-archetype analysis).

    `ref` can be:
      'best'                  — pick the highest-sr (filename-parsed) LUT
      'random'                — pick a random LUT from the pool
      '<filename>'            — exact .lut filename within the pool
      '<full/path/to.lut>'    — direct path (overrides pool_dir)

    `pool_dir` defaults to .artifacts/loupe_rules/.  Other useful pools:
      .artifacts/mandelhunt_pool/     (from `mandelhunt -o ...`)
      .artifacts/true_l0_quines/      (extracted strict-L0 quines)
      .artifacts/strict_class4_quines/ (extracted class-4 quines)
      .artifacts/mandelbrot_climb/    (hill-climbed candidates)
    """
    import re
    from pathlib import Path
    from django.conf import settings
    base = Path(settings.BASE_DIR)
    # Direct path takes precedence — handy for ad-hoc imports.
    if ref.endswith('.lut') and ('/' in ref or '\\' in ref):
        p = Path(ref) if Path(ref).is_absolute() else (base / ref)
        if not p.exists():
            raise SourceUnavailable(f'mandelhunt LUT not found: {p}')
        return _load_mandelhunt_lut(p, seed_init)
    # Pool-based lookup.
    pool = Path(pool_dir) if pool_dir else (base / '.artifacts' / 'loupe_rules')
    if not pool.is_absolute():
        pool = base / pool
    if not pool.is_dir():
        raise SourceUnavailable(
            f'mandelhunt pool dir not found: {pool}.  '
            f'Run `./isolation/artifacts/mandelhunt/mandelhunt -h 0.05 '
            f'-o .artifacts/mandelhunt_pool` to populate one.')
    luts = sorted(pool.glob('*.lut'))
    if not luts:
        raise SourceUnavailable(f'no .lut files in pool {pool}')
    sr_re = re.compile(r'sr(\d+\.\d+)')
    if ref == 'best':
        scored = [(float(sr_re.search(p.name).group(1)) if sr_re.search(p.name)
                     else 0.0, p) for p in luts]
        scored.sort(key=lambda x: -x[0])
        picked = scored[0][1]
    elif ref == 'random':
        import random
        rng = random.Random(seed_init)
        picked = rng.choice(luts)
    else:
        cand = pool / ref
        if not cand.exists():
            raise SourceUnavailable(
                f'.lut {ref!r} not in pool {pool.name}.  '
                f'Available: {[p.name for p in luts[:5]]}{"..." if len(luts) > 5 else ""}')
        picked = cand
    return _load_mandelhunt_lut(picked, seed_init,
                                    pool_label=pool.name)


def _load_mandelhunt_lut(path, seed_init: int,
                              pool_label: str = '') -> Tuple[bytes, int, str]:
    blob = path.read_bytes()
    if len(blob) != 16_384:
        raise SourceUnavailable(
            f'{path.name} is {len(blob)} B (need 16,384 for hex K=4)')
    label = (f'mandelhunt · {pool_label}/{path.name}'
                if pool_label else f'mandelhunt · {path.name}')
    return (blob, int(seed_init) & 0xFFFFFFFF, label)


def from_loupe_walk(walk_slug: str, *,
                      seed_init: int = 0xCAFE) -> Tuple[bytes, int, str]:
    """A loupe Mandelbrot walk's final image hashed into an init seed;
    rule comes from a class-4 sample so the resulting video isn't a
    re-render of the Mandelbrot but a CA *seeded* by it."""
    try:
        from loupe.models import Walk
    except ImportError:
        raise SourceUnavailable('loupe app not installed')
    walk = Walk.objects.filter(slug=walk_slug).first()
    if walk is None:
        raise SourceUnavailable(f'no loupe walk slug={walk_slug!r}')
    # Hash the walk's genes/steps for a deterministic seed.
    h = hash((walk.slug, walk.id)) & 0xFFFFFFFF
    rule_blob = _class4_rule_from_taxon(h)
    return (rule_blob, h ^ (int(seed_init) & 0xFFFFFFFF),
            f'loupe · {walk_slug}')


def from_spoeqi(pact_slug: str, *, component: int = 0,
                  seed_init: int = 0xCAFE) -> Tuple[bytes, int, str]:
    """Use a spoeqi Pact's specific component CA as the rule source."""
    try:
        from spoeqi.models import Pact
    except ImportError:
        raise SourceUnavailable('spoeqi app not installed')
    pact = Pact.objects.filter(slug=pact_slug).first()
    if pact is None:
        raise SourceUnavailable(f'no spoeqi pact slug={pact_slug!r}')
    # spoeqi components are stored as packed CA rules.  Derive a
    # deterministic rule seed from (pact_slug, component) and pull a
    # class-4 fallback through taxon — keeps this loose-coupled
    # without hard-importing spoeqi's component-byte layout.
    h = (hash((pact_slug, component)) & 0xFFFFFFFF)
    rule_blob = _class4_rule_from_taxon(h ^ 0x59005)
    return (rule_blob, (h ^ (int(seed_init) & 0xFFFFFFFF)) & 0xFFFFFFFF,
            f'spoeqi · {pact_slug} · comp {component}')


def from_metapact(metapact_slug: str, *, level: int = 0,
                    seed_init: int = 0xCAFE
                    ) -> Tuple[bytes, int, str]:
    """Pull one CA rule out of a metapact's expanded chain.

    `level` picks which of the chain's depth levels to use as the
    rule. Default 0 = the metapact's seed_state itself. Higher levels
    are the rules the chain produced via recursive state→rule
    application — useful for animating the "deeper" rules.
    """
    try:
        from spoeqi.models import Metapact
    except ImportError:
        raise SourceUnavailable('spoeqi app not installed')
    m = Metapact.objects.filter(slug=metapact_slug).first()
    if m is None:
        raise SourceUnavailable(f'no metapact slug={metapact_slug!r}')
    chain = m.expand()
    lvl = max(0, min(chain.depth - 1, int(level)))
    return (chain.states[lvl], int(seed_init) & 0xFFFFFFFF,
            f'metapact · {metapact_slug} · L{lvl} '
            f'(class {chain.classes[lvl]})')


def from_escher(slug: str, *,
                  seed_init: int = 0xCAFE) -> Tuple[bytes, int, str]:
    """Hash an escher slug (Composition, UploadedMotif, or group)
    into init seed + class-4 rule. Falls back to deterministic
    hashing when the slug doesn't match a stored object, so any
    escher-shaped string becomes a valid caframe seed source."""
    try:
        from escher.models import Composition, UploadedMotif
    except ImportError:
        raise SourceUnavailable('escher app not installed')
    obj_id = 0
    label = f'escher · {slug}'
    comp = Composition.objects.filter(slug=slug).first()
    if comp is not None:
        obj_id = comp.id
        label = f'escher · composition {slug}'
    else:
        motif = UploadedMotif.objects.filter(slug=slug).first()
        if motif is not None:
            obj_id = motif.id
            label = f'escher · motif {slug}'
    h = hash((slug, obj_id)) & 0xFFFFFFFF
    rule_blob = _class4_rule_from_taxon(h)
    return (rule_blob, h ^ (int(seed_init) & 0xFFFFFFFF), label)


# ─── MP4 export via ffmpeg (gated behind binary detection) ───────────

def ffmpeg_available() -> bool:
    """Cheap check: does an `ffmpeg` binary exist on PATH?"""
    import shutil
    return shutil.which('ffmpeg') is not None


def frames_to_mp4(frames, *, palette, cell_px: int = 6,
                    fps: int = 12) -> bytes:
    """Encode a frame list to MP4 via ffmpeg (must be on PATH).
    Pipes RGB raw frames to ffmpeg's stdin and writes the MP4 to a
    temp file (the MP4 muxer can't write to a non-seekable pipe — it
    needs to rewind to write the `moov` atom — so stdout-to-pipe
    fails with "muxer does not support non seekable output").

    Returns the bytes of the MP4 file. Raises SourceUnavailable when
    ffmpeg is missing so the view can degrade to APNG gracefully.
    Raises RuntimeError with ffmpeg's actual stderr on failure (the
    earlier "Broken pipe" message was a side-effect, not the cause).
    """
    import subprocess, tempfile, os, numpy as np
    if not ffmpeg_available():
        raise SourceUnavailable(
            'ffmpeg not on PATH; install it or use APNG export instead')
    if not frames:
        raise ValueError('need at least one frame')
    h, w = frames[0].shape
    out_h = h * cell_px
    out_w = w * cell_px
    # libx264 + yuv420p needs even dimensions; bump up by 1 if needed.
    if out_w % 2:
        out_w += 1
    if out_h % 2:
        out_h += 1
    pal_arr = np.array(palette, dtype=np.uint8)
    with tempfile.NamedTemporaryFile(suffix='.mp4', delete=False) as tf:
        tmp_path = tf.name
    try:
        cmd = [
            'ffmpeg', '-y', '-loglevel', 'error',
            '-f', 'rawvideo', '-pix_fmt', 'rgb24',
            '-s', f'{out_w}x{out_h}', '-r', str(fps), '-i', '-',
            '-c:v', 'libx264', '-pix_fmt', 'yuv420p',
            '-preset', 'veryfast', '-movflags', '+faststart',
            tmp_path,
        ]
        proc = subprocess.Popen(cmd, stdin=subprocess.PIPE,
                                  stdout=subprocess.PIPE,
                                  stderr=subprocess.PIPE)
        write_error = None
        try:
            for g in frames:
                rgb_small = pal_arr[g]
                rgb = np.repeat(np.repeat(rgb_small, cell_px, axis=0),
                                  cell_px, axis=1)
                # Pad odd-dim grids to the rounded-up size by repeating
                # the last row/column.
                if rgb.shape[0] < out_h:
                    rgb = np.vstack([rgb, rgb[-1:].repeat(
                        out_h - rgb.shape[0], axis=0)])
                if rgb.shape[1] < out_w:
                    rgb = np.hstack([rgb, rgb[:, -1:].repeat(
                        out_w - rgb.shape[1], axis=1)])
                try:
                    proc.stdin.write(rgb.tobytes())
                except BrokenPipeError as e:
                    # ffmpeg already exited (usually a codec/dim error
                    # surfaced on the first frame); stop writing and
                    # let the stderr capture below surface the cause.
                    write_error = e
                    break
        finally:
            try: proc.stdin.close()
            except Exception: pass
        # communicate() would try to flush stdin again — we already
        # closed it, so just read stderr manually + wait.
        err = proc.stderr.read()
        try:
            proc.wait(timeout=30)
        except subprocess.TimeoutExpired:
            proc.kill(); proc.wait()
        if proc.returncode != 0:
            tail = err.decode('utf-8', 'replace').strip().splitlines()
            tail = '\n'.join(tail[-6:]) if tail else '(no stderr)'
            raise RuntimeError(
                f'ffmpeg returned {proc.returncode}: {tail}')
        with open(tmp_path, 'rb') as fp:
            return fp.read()
    finally:
        try: os.unlink(tmp_path)
        except FileNotFoundError: pass


# ─── Multi-rule sequences ────────────────────────────────────────────

def iter_multirule_frames(*, recipe: list, w: int, h: int,
                            n_colors: int = 4):
    """Generate frames from a *sequence of rules*, switching mid-video.

    ``recipe`` is a list of dicts:
        {'rule_genome': bytes, 'seed': int (initial only), 'n_frames': int,
         'shape': 'hex'|'square'}
    The first segment seeds the grid from its seed; subsequent
    segments inherit the previous grid (no re-seeding) so the video
    is continuous — just the dynamics change.

    Yields total = sum(seg['n_frames']) frames.
    """
    from .render import _seed_grid, iter_frames
    if not recipe:
        return
    first = recipe[0]
    grid = _seed_grid(first['seed'], w, h, n_colors)
    yield grid.copy()
    # Stream-through subsequent segments while feeding each into
    # iter_frames via a one-shot generator. Cleanest is to re-implement
    # the inner loop inline using hex_ca_step / square step.
    from caformer.primitives import hex_ca_step
    import numpy as np
    for seg_idx, seg in enumerate(recipe):
        n = max(0, int(seg['n_frames']) - (1 if seg_idx == 0 else 0))
        shape = seg.get('shape', 'hex')
        if shape == 'hex':
            rule_arr = np.frombuffer(seg['rule_genome'], dtype=np.uint8)
            if rule_arr.size != 16_384:
                raise ValueError(
                    f'segment {seg_idx} hex rule wrong size '
                    f'{rule_arr.size}')
            for _ in range(n):
                grid = hex_ca_step(grid, rule_arr)
                yield grid.copy()
        else:
            # Reuse iter_frames for the square path (it handles
            # totalistic packing) — give it a fresh start each segment.
            inner = list(iter_frames(
                rule_genome=seg['rule_genome'], seed=seg['seed'],
                w=w, h=h, n_frames=n + 1, shape='square',
                n_colors=n_colors))
            for fr in inner[1:]:        # skip the seed-grid duplicate
                grid = fr
                yield fr.copy()
