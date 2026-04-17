from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.shortcuts import get_object_or_404, redirect, render
from django.utils import timezone
from django.views.decorators.http import require_POST

from attic.models import MediaItem

from .models import FITNESS_MODES, SELECTION_MODES, Reel, ReelTournament


@login_required
def reel_list(request):
    reels = Reel.objects.all()
    ready_reels = Reel.objects.filter(status='ready').exclude(output='').order_by('-rendered_at', '-id')
    return render(request, 'zoetrope/list.html', {
        'reels': reels,
        'ready_reels': ready_reels,
        'image_count': MediaItem.objects.filter(kind='image').count(),
    })


def _clamp_float(raw, lo, hi, default):
    try:
        v = float(raw)
    except (TypeError, ValueError):
        return default
    return max(lo, min(hi, v))


def _clamp_int(raw, lo, hi, default):
    try:
        v = int(raw)
    except (TypeError, ValueError):
        return default
    return max(lo, min(hi, v))


@login_required
def reel_create(request):
    if request.method == 'POST':
        title = request.POST.get('title', '').strip() or 'Untitled reel'
        tag_filter = request.POST.get('tag_filter', '').strip()
        selection_mode = request.POST.get('selection_mode', 'recent')
        if selection_mode not in (m for m, _ in SELECTION_MODES):
            selection_mode = 'recent'

        fps = _clamp_int(request.POST.get('fps'), 12, 60, 30)
        duration = _clamp_float(request.POST.get('duration_seconds'), 2.0, 15.0, 6.0)
        image_count = _clamp_int(request.POST.get('image_count'), 1, 300, 10)
        width = _clamp_int(request.POST.get('width'), 320, 3840, 1280)
        height = _clamp_int(request.POST.get('height'), 240, 2160, 720)
        speech_n = _clamp_int(request.POST.get('speech_sample_count'), 0, 64, 0)
        speech_v = _clamp_float(request.POST.get('speech_volume'), 0.0, 1.0, 0.7)

        reel = Reel.objects.create(
            title=title,
            tag_filter=tag_filter,
            selection_mode=selection_mode,
            fps=fps,
            duration_seconds=duration,
            image_count=image_count,
            width=width,
            height=height,
            speech_sample_count=speech_n,
            speech_volume=speech_v,
        )

        if request.POST.get('render_now'):
            reel.render()
            if reel.status == 'ready':
                messages.success(request, f'Rendered "{reel.title}".')
            else:
                messages.error(request, f'Render failed: {reel.status_message or "unknown error"}')

        return redirect('zoetrope:detail', slug=reel.slug)

    return render(request, 'zoetrope/create.html', {
        'selection_modes': SELECTION_MODES,
        'image_count': MediaItem.objects.filter(kind='image').count(),
    })


@login_required
@require_POST
def reel_quick_random(request):
    """One-click: N seconds @ 30 fps → N*30 random Attic images, each
    shown for exactly one frame. Flicker-book style."""
    duration = _clamp_float(request.POST.get('duration_seconds'), 2.0, 30.0, 6.0)
    fps = 30
    frame_count = int(round(duration * fps))

    available = MediaItem.objects.filter(kind='image').count()
    if available == 0:
        messages.error(request, 'No images in Attic to draw from.')
        return redirect('zoetrope:list')

    stamp = timezone.now().strftime('%Y-%m-%d %H:%M')
    # One speech sample every ~2 seconds so random reels aren't silent.
    speech_n = _clamp_int(
        request.POST.get('speech_sample_count'),
        0, 32, max(1, int(round(duration / 2))),
    )
    speech_v = _clamp_float(request.POST.get('speech_volume'), 0.0, 1.0, 0.7)
    reel = Reel.objects.create(
        title=f'Random · {duration:g}s · {stamp}',
        selection_mode='random',
        image_count=frame_count,
        fps=fps,
        duration_seconds=duration,
        speech_sample_count=speech_n,
        speech_volume=speech_v,
    )
    reel.render()
    if reel.status == 'ready':
        messages.success(
            request,
            f'Rendered "{reel.title}" — {reel.frames_used} random '
            f'image{"s" if reel.frames_used != 1 else ""} × 1 frame each.',
        )
    else:
        messages.error(request, f'Render failed: {reel.status_message or "unknown error"}')
    return redirect('zoetrope:detail', slug=reel.slug)


@login_required
def reel_detail(request, slug):
    reel = get_object_or_404(Reel, slug=slug)
    preview = reel.select_items()[:12]
    return render(request, 'zoetrope/detail.html', {
        'reel': reel,
        'preview': preview,
    })


@login_required
def reel_frames(request, slug):
    """Frame editor — GET shows current frame order, POST saves it.

    The form has two mutable controls:
      - a hidden input `order` containing a comma-separated list of
        MediaItem PKs in final playback order (driven by drag-sort)
      - a textarea `order_text` for direct bulk editing of the PK list

    POST accepts either (textarea wins if non-empty). Missing / invalid
    PKs are dropped silently.
    """
    reel = get_object_or_404(Reel, slug=slug)

    if request.method == 'POST':
        raw = request.POST.get('order_text', '').strip()
        if not raw:
            raw = request.POST.get('order', '').strip()
        pks = []
        for token in raw.replace('\n', ',').replace(' ', ',').split(','):
            token = token.strip()
            if not token:
                continue
            try:
                pks.append(int(token))
            except ValueError:
                continue
        # Filter to PKs that actually exist (and are images).
        valid = set(MediaItem.objects.filter(
            pk__in=pks, kind='image').values_list('pk', flat=True))
        pks = [p for p in pks if p in valid]
        reel.frame_order = pks
        reel.image_count = len(pks) or reel.image_count
        reel.save(update_fields=['frame_order', 'image_count'])
        messages.success(request, f'Saved order of {len(pks)} frame{"s" if len(pks) != 1 else ""}.')
        if request.POST.get('render_now'):
            reel.render()
            if reel.status == 'ready':
                messages.success(request, 'Re-rendered with the new frame order.')
            else:
                messages.error(request, f'Render failed: {reel.status_message or "unknown error"}')
        return redirect('zoetrope:frames', slug=reel.slug)

    # GET — figure out current ordered items
    items = reel.select_items()
    # If frame_order is empty, populate from the current selection so the
    # editor has something to work with.
    seeded_from_selection = not reel.frame_order
    return render(request, 'zoetrope/frames.html', {
        'reel':  reel,
        'items': items,
        'order_pks_csv': ','.join(str(it.pk) for it in items),
        'order_text':    '\n'.join(str(it.pk) for it in items),
        'seeded':        seeded_from_selection,
        'total':         len(items),
    })


@login_required
@require_POST
def reel_render(request, slug):
    reel = get_object_or_404(Reel, slug=slug)
    reel.render()
    if reel.status == 'ready':
        messages.success(request, 'Reel rendered.')
    else:
        messages.error(request, f'Render failed: {reel.status_message or "unknown error"}')
    return redirect('zoetrope:detail', slug=reel.slug)


@login_required
@require_POST
def reel_share(request, slug):
    """Upload the rendered mp4 to s.h4ks.com and redirect to the public URL."""
    reel = get_object_or_404(Reel, slug=slug)
    if not reel.output:
        messages.error(request, 'Render the reel before sharing.')
        return redirect('zoetrope:detail', slug=reel.slug)
    try:
        url = reel.share_to_h4ks()
    except Exception as e:
        messages.error(request, f'Share failed: {e}')
        return redirect('zoetrope:detail', slug=reel.slug)
    return redirect(url)


@login_required
@require_POST
def reel_splice_random(request):
    """Splice two reels into a new reel.

    Reels can come from POST (`reel_a_slug`, `reel_b_slug`) or, when a
    slot is blank / set to 'random', be picked randomly from ready reels.
    `mode=concat` does plain front-to-back; `mode=oscillate` blends
    frame-by-frame along a distorted sine wave.
    """
    import random as _r

    from .models import Reel
    from .splice import splice_reels

    mode = request.POST.get('mode', 'concat')
    if mode not in ('concat', 'oscillate'):
        mode = 'concat'

    def _resolve(slug, exclude_pk=None):
        slug = (slug or '').strip()
        if slug and slug.lower() != 'random':
            try:
                return Reel.objects.exclude(output='').get(slug=slug, status='ready')
            except Reel.DoesNotExist:
                return None
        pool = Reel.objects.filter(status='ready').exclude(output='')
        if exclude_pk is not None:
            pool = pool.exclude(pk=exclude_pk)
        pool = list(pool)
        return _r.choice(pool) if pool else None

    a = _resolve(request.POST.get('reel_a_slug'))
    if a is None:
        messages.error(request, 'Need at least one rendered reel to splice.')
        return redirect('zoetrope:list')
    b = _resolve(request.POST.get('reel_b_slug'), exclude_pk=a.pk)
    if b is None:
        messages.error(request, 'Need at least two rendered reels (or pick a different second reel).')
        return redirect('zoetrope:list')

    try:
        new_reel = splice_reels(a, b, mode=mode)
    except Exception as exc:
        messages.error(request, f'Splice failed: {exc}')
        return redirect('zoetrope:list')
    label = 'Oscillating splice' if mode == 'oscillate' else 'Splice'
    messages.success(
        request,
        f'{label}: "{a.title}" + "{b.title}" → "{new_reel.title}".',
    )
    return redirect('zoetrope:detail', slug=new_reel.slug)


@login_required
@require_POST
def reel_aether_random(request):
    """Pick a random published Aether world and kick off client-side
    autofilm so the user ends up at a new Zoetrope reel of that world.
    The actual capture + upload + render happens in the browser via
    enter.html's maybeAutofilm() handler + aether:world_film endpoint.
    """
    import random as _r

    from django.urls import reverse

    from aether.models import World

    duration = _clamp_float(request.POST.get('duration_seconds'), 2.0, 12.0, 4.0)
    capture_fps = _clamp_int(request.POST.get('capture_fps'), 4, 24, 8)

    qs = World.objects.filter(published=True)
    if not qs.exists():
        messages.error(request, 'No published Aether worlds to film.')
        return redirect('zoetrope:list')
    world = _r.choice(list(qs))

    url = (
        reverse('aether:world_enter', args=[world.slug])
        + f'?autofilm=1&duration={duration:g}&capture_fps={capture_fps}'
    )
    messages.info(
        request,
        f'Filming "{world.title}" — the browser will redirect to the reel '
        f'when the {duration:g}s capture finishes.',
    )
    return redirect(url)


@login_required
@require_POST
def reel_auto_edit(request):
    """One-click: curate up to 3000 frames from Attic via color-TSP
    ordering, render a 10s film at 300 fps, return the detail page.
    """
    from .autoedit import auto_edit_reel

    count = _clamp_int(request.POST.get('count'), 30, 3000, 3000)
    duration = _clamp_float(request.POST.get('duration_seconds'), 2.0, 30.0, 10.0)
    fps = _clamp_int(request.POST.get('fps'), 24, 300, 300)
    speech_n = _clamp_int(request.POST.get('speech_sample_count'), 0, 24, 6)

    available = MediaItem.objects.filter(kind='image').count()
    if available == 0:
        messages.error(request, 'No images in Attic to auto-edit from.')
        return redirect('zoetrope:list')

    reel = auto_edit_reel(
        count=count, duration_seconds=duration, fps=fps,
        speech_sample_count=speech_n,
    )
    if reel is None:
        messages.error(request, 'Auto-edit could not fingerprint any images.')
        return redirect('zoetrope:list')
    if reel.status == 'ready':
        messages.success(
            request,
            f'Auto-edited {reel.frames_used} frames into '
            f'"{reel.title}" ({reel.duration_seconds:g}s @ {reel.fps}fps).',
        )
    else:
        messages.error(request, f'Auto-edit render failed: {reel.status_message or "unknown"}')
    return redirect('zoetrope:detail', slug=reel.slug)


@login_required
def tournament_list(request):
    tournaments = ReelTournament.objects.all()[:60]
    return render(request, 'zoetrope/tournaments.html', {
        'tournaments': tournaments,
        'fitness_modes': FITNESS_MODES,
        'ready_reel_count': Reel.objects.filter(status='ready').exclude(output='').count(),
    })


@login_required
@require_POST
def tournament_create(request):
    """Pick N random ready reels and run a tournament among them."""
    import random as _r

    count = _clamp_int(request.POST.get('count'), 3, 16, 6)
    mode = request.POST.get('fitness_mode', 'aesthetic')
    if mode not in {m for m, _ in FITNESS_MODES}:
        mode = 'aesthetic'

    ready = list(Reel.objects.filter(status='ready').exclude(output=''))
    if len(ready) < 3:
        messages.error(request, 'Need at least 3 rendered reels to hold a tournament.')
        return redirect('zoetrope:tournaments')
    rng = _r.Random()
    participants = rng.sample(ready, min(count, len(ready)))

    stamp = timezone.now().strftime('%Y-%m-%d %H:%M')
    tourney = ReelTournament.objects.create(
        name=f'{mode.title()} tournament · {stamp}',
        fitness_mode=mode,
    )
    try:
        tourney.run(participants, rng=rng)
    except Exception as exc:
        messages.error(request, f'Tournament failed: {exc}')
        return redirect('zoetrope:tournaments')

    if tourney.winner:
        messages.success(
            request,
            f'Tournament crowned "{tourney.winner.title}" '
            f'under mode "{mode}".',
        )
    else:
        messages.error(request, 'Tournament produced no winner.')
    return redirect('zoetrope:tournaments')


@login_required
@require_POST
def reel_delete(request, slug):
    reel = get_object_or_404(Reel, slug=slug)
    title = reel.title
    try:
        if reel.output:
            reel.output.delete(save=False)
        if reel.poster:
            reel.poster.delete(save=False)
    except Exception:
        pass
    reel.delete()
    messages.success(request, f'Removed "{title}".')
    return redirect('zoetrope:list')
