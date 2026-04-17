"""Random slice-and-splice compositor for Attic images.

Takes random rectangular slices from existing image MediaItems and
pastes them onto a fresh canvas at random positions, rotations, and
scales. The result is saved back to the Attic as a new image, a
procedural collage of whatever the Attic happens to be holding.

Intentionally dumb. No AI, no segmentation — just geometry and
randomness. The charm is that the output depends entirely on what
lives in the Attic right now.
"""

import random
from io import BytesIO
from pathlib import Path

from django.core.files.base import ContentFile
from django.utils import timezone

from .models import MediaItem


def _load_source_images(source_items):
    """Open each MediaItem's file with Pillow. Return list of
    (item, PIL.Image) pairs; skip any item that fails to open."""
    from PIL import Image
    loaded = []
    for item in source_items:
        try:
            with item.file.open('rb') as f:
                data = f.read()
            img = Image.open(BytesIO(data))
            img.load()
            if img.mode not in ('RGB', 'RGBA'):
                img = img.convert('RGBA')
            loaded.append((item, img))
        except Exception:
            continue
    return loaded


def splice(source_items, canvas=(960, 960), slices=24, seed=None,
           background='#0d1117'):
    """Build a collage by pasting `slices` random rectangles taken from
    `source_items` onto a fresh canvas.

    Returns a PIL.Image in RGBA. Raises ValueError if no sources could
    be loaded.
    """
    from PIL import Image

    rng = random.Random(seed)
    loaded = _load_source_images(source_items)
    if not loaded:
        raise ValueError('No usable source images.')

    # Parse background hex
    bg = background.lstrip('#')
    bg_rgb = (int(bg[0:2], 16), int(bg[2:4], 16), int(bg[4:6], 16))
    out = Image.new('RGBA', canvas, bg_rgb + (255,))

    cw, ch = canvas
    for _ in range(slices):
        _, src = rng.choice(loaded)
        sw, sh = src.size
        if sw < 4 or sh < 4:
            continue

        # Random source rectangle: width 15-55% of source, height 15-55%.
        slice_w = rng.randint(max(4, sw // 7), max(5, sw * 55 // 100))
        slice_h = rng.randint(max(4, sh // 7), max(5, sh * 55 // 100))
        sx = rng.randint(0, sw - slice_w)
        sy = rng.randint(0, sh - slice_h)
        piece = src.crop((sx, sy, sx + slice_w, sy + slice_h))
        if piece.mode != 'RGBA':
            piece = piece.convert('RGBA')

        # Random rotation (free-angle, but most of the mass near cardinal
        # directions so the result doesn't feel like pure noise).
        if rng.random() < 0.6:
            angle = rng.choice([0, 90, 180, 270])
        else:
            angle = rng.uniform(-25, 25)
        if angle:
            piece = piece.rotate(angle, expand=True,
                                 resample=Image.BICUBIC)

        # Random scale so some pieces dominate and others recede.
        scale = rng.uniform(0.35, 1.15)
        new_w = max(8, int(piece.width * scale))
        new_h = max(8, int(piece.height * scale))
        piece = piece.resize((new_w, new_h), resample=Image.BICUBIC)

        # Occasional alpha fade so pieces bleed into each other.
        if rng.random() < 0.35:
            alpha = rng.uniform(0.35, 0.85)
            r, g, b, a = piece.split()
            a = a.point(lambda v, al=alpha: int(v * al))
            piece = Image.merge('RGBA', (r, g, b, a))

        # Random placement — piece can hang off the canvas edge a bit.
        px = rng.randint(-new_w // 3, cw - new_w * 2 // 3)
        py = rng.randint(-new_h // 3, ch - new_h * 2 // 3)
        out.alpha_composite(piece, dest=(px, py))

    return out


def splice_to_attic(source_items, canvas=(960, 960), slices=24,
                    seed=None, title=None, tags='spliced, auto',
                    caption='', uploaded_by=None):
    """Run splice() and save the result as a new MediaItem. Returns
    the saved row, or None if no usable source images were available.
    """
    try:
        image = splice(source_items, canvas=canvas, slices=slices, seed=seed)
    except ValueError:
        return None

    buf = BytesIO()
    image.convert('RGB').save(buf, format='PNG', optimize=True)
    buf.seek(0)

    now = timezone.now()
    if not title:
        title = f'Spliced collage {now:%Y-%m-%d %H:%M:%S}'

    slug_filename = f'spliced-{now:%Y%m%d-%H%M%S}.png'
    item = MediaItem(
        title=title,
        caption=caption or (
            f'Collage of {slices} random slices from '
            f'{len(source_items)} Attic images, pasted with random '
            f'rotation, scale, and position.'),
        tags=tags,
        uploaded_by=uploaded_by,
        kind='image',
        mime='image/png',
    )
    item.file.save(slug_filename, ContentFile(buf.getvalue()), save=False)
    item.save()
    return item


def pick_random_image_items(count=8, seed=None):
    """Random sample of `count` image MediaItems. Returns fewer if
    the Attic doesn't have that many images."""
    rng = random.Random(seed)
    qs = list(MediaItem.objects.filter(kind='image'))
    if not qs:
        return []
    if len(qs) <= count:
        return qs
    return rng.sample(qs, count)
