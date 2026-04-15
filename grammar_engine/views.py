"""Grammar Engine views.

For now the views are stubs — we wire them in after the engine module
is extracted. The URL resolver needs to see them to pass startup
checks, that's all.
"""

import json

from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.core.paginator import Paginator
from django.db.models import Q
from django.http import HttpResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse
from django.utils.crypto import get_random_string
from django.views.decorators.http import require_POST

from .models import Language


@login_required
def language_list(request):
    qs = Language.objects.all()
    q = (request.GET.get('q') or '').strip()
    if q:
        qs = qs.filter(Q(name__icontains=q) | Q(slug__icontains=q)
                       | Q(notes__icontains=q))
    total = qs.count()
    grand_total = Language.objects.count()
    paginator = Paginator(qs, 50)
    page = paginator.get_page(request.GET.get('page'))
    return render(request, 'grammar_engine/list.html', {
        'page': page,
        'languages': page.object_list,
        'total': total,
        'grand_total': grand_total,
        'q': q,
    })


@login_required
@require_POST
def language_new(request):
    """Create a blank Language with a random seed. The browser generates
    the spec from the seed on page load and POSTs it back to `spec`
    (or the user can leave it unseeded and regenerate in the browser)."""
    import secrets
    name = request.POST.get('name', '').strip()
    if not name:
        name = 'Unnamed-' + get_random_string(6).lower()
    try:
        seed = int(request.POST.get('seed') or secrets.randbits(31))
    except (TypeError, ValueError):
        seed = secrets.randbits(31)
    language = Language.objects.create(name=name, seed=seed)
    messages.success(request, f'Created language "{language.name}".')
    return redirect('grammar_engine:detail', slug=language.slug)


@login_required
def language_detail(request, slug):
    language = get_object_or_404(Language, slug=slug)
    return render(request, 'grammar_engine/detail.html', {
        'language': language,
        'spec_json': json.dumps(language.spec or {}),
    })


@login_required
@require_POST
def language_regenerate(request, slug):
    """Receive a freshly-generated spec from the browser and store it."""
    language = get_object_or_404(Language, slug=slug)
    try:
        spec = json.loads(request.body.decode('utf-8'))
    except (ValueError, UnicodeDecodeError):
        return HttpResponse('invalid json', status=400)
    language.spec = spec
    language.save()
    return HttpResponse('ok')


@login_required
@require_POST
def language_delete(request, slug):
    language = get_object_or_404(Language, slug=slug)
    name = language.name
    language.delete()
    messages.info(request, f'Deleted language "{name}".')
    return redirect('grammar_engine:list')


@login_required
def language_spec(request, slug):
    """JSON endpoint — Bridge and Aether fetch the spec for playback."""
    language = get_object_or_404(Language, slug=slug)
    return HttpResponse(
        json.dumps({
            'id': language.id,
            'slug': language.slug,
            'name': language.name,
            'seed': language.seed,
            'spec': language.spec,
        }),
        content_type='application/json',
    )
