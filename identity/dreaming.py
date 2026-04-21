"""Identity's Dream sequence.

Chains five Velour apps into one gesture:

  1. `attic.splicer` — pick a handful of random Attic images and paste
     slices from them onto a fresh canvas (a collage).
  2. `identity.dialogue.compose_therapy_exchange` — patient/clinician
     voices look at current mood + diagnosis. The resulting
     InternalDialogue gets a back-reference to the splice so the
     exchange sits in the dream record, not in open air.
  3. `identity.tiles_reflection.generate_tileset_from_identity` — run
     twice. Each call composes a new Wang-tile set from Identity
     state and renders an artwork image to the Attic. The
     `originating_meditation_pk` sentinel suppresses the usual
     bounce-meditation so the tree stays shallow.
  4. `attic.splicer.splice_to_attic([artwork_a, artwork_b])` — splice
     the two fresh tileset artworks into one tileset collage.
  5. `zoetrope.models.Reel` — build a 10-second film titled
     "Dream Movie — <timestamp>" from the four fresh Attic images
     (two artworks + two splices) and render it synchronously.

Each step catches its own exceptions so a degrade (no images, ffmpeg
missing) does not wipe out preceding work. The returned dict links
every output that actually made it to the DB.
"""

import random
from datetime import datetime

from django.utils import timezone


DREAM_TITLE_PREFIX = 'Dream Movie'


def run_dream_sequence(user=None, seed=None):
    """Run the full Dream chain. Returns a dict with keys:

        image_splice       attic.MediaItem or None (step 1)
        dialogue           identity.InternalDialogue or None (step 2)
        tilesets           list[tiles.TileSet]  (step 3)
        tileset_artworks   list[attic.MediaItem]  (step 3)
        tileset_splice     attic.MediaItem or None  (step 4)
        reel               zoetrope.Reel or None  (step 5)
        errors             list[str]
    """
    from attic.splicer import pick_random_image_items, splice_to_attic
    from .dialogue import compose_therapy_exchange
    from .tiles_reflection import generate_tileset_from_identity

    rng = random.Random(seed)
    errors = []
    result = {
        'image_splice':     None,
        'dialogue':         None,
        'tilesets':         [],
        'tileset_artworks': [],
        'tileset_splice':   None,
        'reel':             None,
        'errors':           errors,
    }

    now = timezone.now()
    dream_tag = f'dream-{now:%Y%m%d-%H%M%S}'

    # --- 1. Splice random Attic images ---------------------------------
    try:
        sources = pick_random_image_items(count=8, seed=rng.random())
        if sources:
            splice = splice_to_attic(
                sources,
                canvas=(1024, 1024),
                slices=28,
                seed=rng.random(),
                title=f'Dream splice · {now:%Y-%m-%d %H:%M:%S}',
                tags=f'dream, {dream_tag}, spliced, auto',
                caption='Random-slice collage assembled at the start '
                        'of a Dream sequence.',
                uploaded_by=user,
            )
            result['image_splice'] = splice
        else:
            errors.append('no Attic images available for the opening splice')
    except Exception as exc:
        errors.append(f'splice step failed: {exc}')

    # --- 2. Ego / self in conversation about the splice ---------------
    try:
        dialogue = compose_therapy_exchange(save=True, triggered_by='dream')
        if dialogue is not None and result['image_splice'] is not None:
            snap = dict(dialogue.state_snapshot or {})
            snap['dream_splice_pk'] = result['image_splice'].pk
            snap['dream_splice_title'] = result['image_splice'].title
            dialogue.state_snapshot = snap
            dialogue.save(update_fields=['state_snapshot'])
        result['dialogue'] = dialogue
    except Exception as exc:
        errors.append(f'therapy exchange failed: {exc}')

    # --- 3. Two fresh tilesets from current Identity ------------------
    # Sentinel suppresses the bounce-meditation side-effect — the dream
    # is the framing, not another meditation chain.
    for i in range(2):
        try:
            ts = generate_tileset_from_identity(
                force_name=f'Dream tileset {i+1} · {now:%Y-%m-%d %H:%M:%S}',
                originating_meditation_pk=0,
            )
            result['tilesets'].append(ts)
            artwork = _find_artwork(ts)
            if artwork is not None:
                result['tileset_artworks'].append(artwork)
        except Exception as exc:
            errors.append(f'tileset {i+1} failed: {exc}')

    # --- 4. Splice the two tileset artworks together ------------------
    try:
        arts = result['tileset_artworks']
        if len(arts) >= 2:
            ts_splice = splice_to_attic(
                arts,
                canvas=(1024, 1024),
                slices=20,
                seed=rng.random(),
                title=f'Dream tileset splice · {now:%Y-%m-%d %H:%M:%S}',
                tags=f'dream, {dream_tag}, tileset-splice, auto',
                caption='Splice of two tileset artworks born in the same '
                        'Dream sequence.',
                uploaded_by=user,
            )
            result['tileset_splice'] = ts_splice
        else:
            errors.append('fewer than 2 tileset artworks to splice')
    except Exception as exc:
        errors.append(f'tileset-splice step failed: {exc}')

    # --- 5. Ten-second Dream Movie ------------------------------------
    try:
        frame_items = []
        for item in (result['image_splice'], *result['tileset_artworks'],
                     result['tileset_splice']):
            if item is not None:
                frame_items.append(item)
        if frame_items:
            result['reel'] = _build_dream_reel(frame_items, now, dream_tag)
        else:
            errors.append('no frames available for the Dream Movie')
    except Exception as exc:
        errors.append(f'reel step failed: {exc}')

    return result


def _find_artwork(tileset):
    """The tileset generator saves its rendered artwork to Attic with
    slug `artwork-<tileset.slug>`. Fetch it for the splice step."""
    try:
        from attic.models import MediaItem
        meta = tileset.source_metadata or {}
        slug = meta.get('artwork_slug') or f'artwork-{tileset.slug}'
        return MediaItem.objects.filter(slug=slug).first()
    except Exception:
        return None


def _build_dream_reel(frame_items, now, dream_tag):
    """Create a Reel row with the given Attic images as its frame order
    and render it synchronously. 10 seconds at 24 fps, square canvas
    to match the splice outputs."""
    from zoetrope.models import Reel

    title = f'{DREAM_TITLE_PREFIX} · {now:%Y-%m-%d %H:%M:%S}'
    reel = Reel.objects.create(
        title=title,
        tag_filter='',
        selection_mode='random',
        image_count=len(frame_items),
        fps=24,
        duration_seconds=10.0,
        width=1024,
        height=1024,
        speech_sample_count=4,
        speech_volume=0.7,
        frame_order=[it.pk for it in frame_items],
    )
    reel.render()
    return reel
