from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.shortcuts import get_object_or_404, redirect, render
from django.utils import timezone
from django.views.decorators.http import require_POST

from attic.models import MediaItem

from .models import SELECTION_MODES, Reel


@login_required
def reel_list(request):
    reels = Reel.objects.all()
    return render(request, 'zoetrope/list.html', {
        'reels': reels,
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

        reel = Reel.objects.create(
            title=title,
            tag_filter=tag_filter,
            selection_mode=selection_mode,
            fps=fps,
            duration_seconds=duration,
            image_count=image_count,
            width=width,
            height=height,
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
    reel = Reel.objects.create(
        title=f'Random · {duration:g}s · {stamp}',
        selection_mode='random',
        image_count=frame_count,
        fps=fps,
        duration_seconds=duration,
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
