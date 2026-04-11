from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.shortcuts import get_object_or_404, redirect, render
from django.views.decorators.http import require_POST

from .models import KIND_CHOICES, MediaItem


@login_required
def attic_list(request):
    qs = MediaItem.objects.all()

    kind = request.GET.get('kind', '').strip()
    if kind in (k for k, _ in KIND_CHOICES):
        qs = qs.filter(kind=kind)

    search = request.GET.get('q', '').strip()
    if search:
        qs = qs.filter(title__icontains=search) | qs.filter(tags__icontains=search) | qs.filter(caption__icontains=search)

    return render(request, 'attic/list.html', {
        'items': qs,
        'kind_choices': KIND_CHOICES,
        'kind_filter': kind,
        'search': search,
        'item_count': qs.count(),
        'total_count': MediaItem.objects.count(),
    })


@login_required
def attic_detail(request, slug):
    item = get_object_or_404(MediaItem, slug=slug)
    return render(request, 'attic/detail.html', {'item': item})


_TEXT_FIELDS = ('title', 'caption', 'alt_text', 'tags', 'notes')


def _apply_post(item, post):
    for f in _TEXT_FIELDS:
        setattr(item, f, post.get(f, '').strip())


@login_required
def attic_upload(request):
    """Upload one or more files. Multi-file via the 'files' field name
    on a regular HTML <input type="file" multiple>."""
    if request.method == 'POST':
        files = request.FILES.getlist('files')
        if not files:
            messages.error(request, 'No files selected.')
            return redirect('attic:upload')

        common_tags = request.POST.get('tags', '').strip()
        common_caption = request.POST.get('caption', '').strip()

        created = 0
        for upload in files:
            try:
                m = MediaItem(
                    file=upload,
                    title=request.POST.get('title', '').strip() or '',
                    caption=common_caption,
                    tags=common_tags,
                    uploaded_by=request.user if request.user.is_authenticated else None,
                )
                m.save()
                created += 1
            except Exception as e:
                messages.error(request, f'Could not save {upload.name}: {e}')

        if created:
            messages.success(request, f'Uploaded {created} item{"s" if created != 1 else ""}.')
        return redirect('attic:list')

    return render(request, 'attic/upload.html')


@login_required
def attic_edit(request, slug):
    item = get_object_or_404(MediaItem, slug=slug)
    if request.method == 'POST':
        _apply_post(item, request.POST)
        item.save()
        messages.success(request, f'Updated "{item.title}".')
        return redirect('attic:detail', slug=item.slug)
    return render(request, 'attic/edit.html', {'item': item})


@login_required
@require_POST
def attic_delete(request, slug):
    item = get_object_or_404(MediaItem, slug=slug)
    title = item.title
    # Best-effort: delete the file from disk too.
    try:
        if item.file:
            item.file.delete(save=False)
        if item.thumbnail:
            item.thumbnail.delete(save=False)
    except Exception:
        pass
    item.delete()
    messages.success(request, f'Removed "{title}".')
    return redirect('attic:list')
