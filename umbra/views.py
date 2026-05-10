"""Umbra views — phase 1 catalogue + experiment authoring.

No real ciphertext computation here yet; experiments save their code
as text.  When phase 2 lands, an execution runner will pipe the code
through a Pyfhel / Concrete subprocess and write back to
last_output / last_error / last_run_ms.
"""
from django.contrib import messages
from django.shortcuts import get_object_or_404, redirect, render
from django.utils.text import slugify

from .models import Scheme, Reference, Experiment


SAMPLE_CODE = """\
# Pyfhel BFV add example.
# Phase 1 stores this as text — phase 2 will run it.
from Pyfhel import Pyfhel

he = Pyfhel()
he.contextGen(scheme='BFV', n=2**13, t=65537, t_bits=20)
he.keyGen()

a = he.encryptInt(42)
b = he.encryptInt(58)

c = a + b                    # ciphertext addition
print('a + b =', he.decryptInt(c))   # -> 100
"""


def _ctx():
    return {
        'app_name':   'Umbra',
        'app_tag':    'FHE workbench',
        'scheme_count':     Scheme.objects.count(),
        'reference_count':  Reference.objects.count(),
        'experiment_count': Experiment.objects.count(),
    }


def index(request):
    schemes  = Scheme.objects.all()
    libs     = Reference.objects.filter(kind=Reference.KIND_LIBRARY)[:8]
    awesome  = Reference.objects.filter(kind=Reference.KIND_AWESOME)
    recent   = Experiment.objects.all()[:5]
    ctx = _ctx()
    ctx.update(schemes=schemes, libs=libs, awesome=awesome, recent=recent)
    return render(request, 'umbra/index.html', ctx)


def scheme_list(request):
    schemes = Scheme.objects.all()
    ctx = _ctx(); ctx['schemes'] = schemes
    return render(request, 'umbra/schemes.html', ctx)


def scheme_detail(request, slug):
    scheme = get_object_or_404(Scheme, slug=slug)
    refs   = scheme.references.all()
    expts  = scheme.experiments.all()
    ctx = _ctx(); ctx.update(scheme=scheme, refs=refs, expts=expts)
    return render(request, 'umbra/scheme_detail.html', ctx)


def reference_list(request):
    by_kind = {}
    for r in Reference.objects.all():
        by_kind.setdefault(r.get_kind_display(), []).append(r)
    ordered = sorted(by_kind.items())
    ctx = _ctx(); ctx['ref_groups'] = ordered
    return render(request, 'umbra/references.html', ctx)


def experiment_list(request):
    expts = Experiment.objects.all()
    ctx = _ctx(); ctx['expts'] = expts
    return render(request, 'umbra/experiments.html', ctx)


def experiment_create(request):
    if request.method == 'POST':
        name        = (request.POST.get('name') or '').strip()
        scheme_slug = request.POST.get('scheme') or ''
        description = request.POST.get('description') or ''
        code        = request.POST.get('code') or SAMPLE_CODE
        if not name:
            messages.error(request, 'A name is required.')
            return redirect('umbra:experiment_create')
        scheme = None
        if scheme_slug:
            scheme = Scheme.objects.filter(slug=scheme_slug).first()
        e = Experiment.objects.create(
            name=name, scheme=scheme, description=description,
            code=code, status=Experiment.STATUS_SAVED,
        )
        messages.success(request, f'Saved experiment "{e.name}".')
        return redirect('umbra:experiment_detail', slug=e.slug)
    ctx = _ctx()
    ctx.update(schemes=Scheme.objects.all(), sample_code=SAMPLE_CODE)
    return render(request, 'umbra/experiment_form.html', ctx)


def experiment_detail(request, slug):
    e = get_object_or_404(Experiment, slug=slug)
    ctx = _ctx(); ctx['expt'] = e
    return render(request, 'umbra/experiment_detail.html', ctx)


def experiment_edit(request, slug):
    e = get_object_or_404(Experiment, slug=slug)
    if request.method == 'POST':
        e.name        = (request.POST.get('name') or e.name).strip() or e.name
        scheme_slug   = request.POST.get('scheme') or ''
        e.scheme      = Scheme.objects.filter(slug=scheme_slug).first() if scheme_slug else None
        e.description = request.POST.get('description') or e.description
        e.code        = request.POST.get('code') or e.code
        e.status      = Experiment.STATUS_SAVED
        e.save()
        messages.success(request, 'Saved.')
        return redirect('umbra:experiment_detail', slug=e.slug)
    ctx = _ctx()
    ctx.update(expt=e, schemes=Scheme.objects.all(), edit_mode=True,
               sample_code=e.code or SAMPLE_CODE)
    return render(request, 'umbra/experiment_form.html', ctx)
