"""Studious views — scholar library + argument workshop.

Phase 1 is deterministic. The ingestion endpoints accept three sources
for a Work's text — URL scrape (trafilatura), PDF upload (pypdf), or
raw paste — and never call out to an LLM. The argument workshop
scaffolds premise / tension blocks from claims the user has already
curated and leaves the synthesis to the user.
"""

from __future__ import annotations

from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.shortcuts import get_object_or_404, redirect, render
from django.views.decorators.http import require_POST

from . import analysis
from .models import (
    ARGUMENT_KINDS, ARGUMENT_ROLES, CLAIM_KINDS, WORK_KINDS,
    Argument, ArgumentClaim, Claim, Domain, Scholar, Work,
)


@login_required
def index(request):
    scholars = Scholar.objects.all()
    works_recent = Work.objects.select_related('scholar').order_by('-ingested_at')[:10]
    arguments = (Argument.objects.filter(user=request.user)
                 .order_by('-modified_at')[:10])
    return render(request, 'studious/index.html', {
        'scholars':      scholars,
        'works_recent':  works_recent,
        'arguments':     arguments,
        'scholar_count': scholars.count(),
        'work_count':    Work.objects.count(),
        'claim_count':   Claim.objects.count(),
        'domains':       Domain.objects.all(),
    })


# ── Scholars ───────────────────────────────────────────────────────

@login_required
def scholar_list(request):
    scholars = Scholar.objects.all()
    return render(request, 'studious/scholar_list.html', {
        'scholars': scholars,
    })


@login_required
def scholar_add(request):
    if request.method == 'POST':
        name = (request.POST.get('name') or '').strip()
        if not name:
            messages.error(request, 'Name is required.')
        else:
            s = Scholar.objects.create(
                name=name[:200],
                affiliation=(request.POST.get('affiliation') or '')[:200],
                active_years=(request.POST.get('active_years') or '')[:40],
                homepage_url=(request.POST.get('homepage_url') or '')[:500],
                bio=(request.POST.get('bio') or ''),
                notes=(request.POST.get('notes') or ''),
            )
            messages.success(request, f'Added {s.name}.')
            return redirect('studious:scholar_detail', slug=s.slug)
    return render(request, 'studious/scholar_form.html', {
        'scholar': None,
    })


@login_required
def scholar_detail(request, slug):
    scholar = get_object_or_404(Scholar, slug=slug)
    works = scholar.works.all()
    return render(request, 'studious/scholar_detail.html', {
        'scholar':    scholar,
        'works':      works,
        'work_kinds': WORK_KINDS,
        'domains':    Domain.objects.all(),
    })


@login_required
def scholar_edit(request, slug):
    scholar = get_object_or_404(Scholar, slug=slug)
    if request.method == 'POST':
        name = (request.POST.get('name') or '').strip()
        if not name:
            messages.error(request, 'Name is required.')
        else:
            scholar.name = name[:200]
            scholar.affiliation = (request.POST.get('affiliation') or '')[:200]
            scholar.active_years = (request.POST.get('active_years') or '')[:40]
            scholar.homepage_url = (request.POST.get('homepage_url') or '')[:500]
            scholar.bio = request.POST.get('bio') or ''
            scholar.notes = request.POST.get('notes') or ''
            scholar.save()
            messages.success(request, 'Saved.')
            return redirect('studious:scholar_detail', slug=scholar.slug)
    return render(request, 'studious/scholar_form.html', {
        'scholar': scholar,
    })


@login_required
@require_POST
def scholar_delete(request, slug):
    scholar = get_object_or_404(Scholar, slug=slug)
    name = scholar.name
    scholar.delete()
    messages.success(request, f'Deleted {name}.')
    return redirect('studious:scholar_list')


# ── Works ──────────────────────────────────────────────────────────

@login_required
def work_add(request):
    scholar_slug = request.GET.get('scholar') or request.POST.get('scholar')
    scholar = None
    if scholar_slug:
        scholar = Scholar.objects.filter(slug=scholar_slug).first()
    if request.method == 'POST':
        if not scholar:
            messages.error(request, 'Pick a scholar.')
            return redirect('studious:scholar_list')
        title = (request.POST.get('title') or '').strip()
        if not title:
            messages.error(request, 'Title is required.')
        else:
            year_raw = (request.POST.get('year') or '').strip()
            year = int(year_raw) if year_raw.isdigit() else None
            url = (request.POST.get('url') or '').strip()
            abstract = request.POST.get('abstract') or ''
            pasted = request.POST.get('full_text') or ''
            ingest = (request.POST.get('ingest') or 'paste').strip()

            full_text = ''
            file_obj = request.FILES.get('source_file')

            if ingest == 'url' and url:
                full_text = analysis.extract_url_text(url)
                if not full_text:
                    messages.warning(request,
                        'URL scrape returned nothing — saved the shell anyway.')
            elif ingest == 'pdf' and file_obj:
                full_text = analysis.extract_pdf_text(file_obj)
                file_obj.seek(0)
                if not full_text:
                    messages.warning(request,
                        'PDF text extraction returned nothing — you can paste manually.')
            elif ingest == 'paste':
                full_text = pasted.strip()
            else:
                full_text = pasted.strip()

            w = Work.objects.create(
                scholar=scholar,
                title=title[:400],
                year=year,
                kind=(request.POST.get('kind') or 'article'),
                doi=(request.POST.get('doi') or '')[:160],
                url=url[:500],
                source_file=file_obj if ingest == 'pdf' else None,
                abstract=abstract,
                full_text=full_text,
                notes=(request.POST.get('notes') or ''),
            )
            for d_slug in request.POST.getlist('domains'):
                d = Domain.objects.filter(slug=d_slug).first()
                if d:
                    w.domains.add(d)

            if full_text.strip():
                try:
                    analysis.analyze_work(w)
                except Exception as e:
                    messages.warning(request, f'Analysis failed: {e}')

            messages.success(request, f'Ingested "{w.title}".')
            return redirect('studious:work_detail', slug=w.slug)

    return render(request, 'studious/work_form.html', {
        'work':       None,
        'scholar':    scholar,
        'scholars':   Scholar.objects.all(),
        'work_kinds': WORK_KINDS,
        'domains':    Domain.objects.all(),
    })


@login_required
def work_detail(request, slug):
    work = get_object_or_404(Work.objects.select_related('scholar'), slug=slug)
    claims = work.claims.all()
    return render(request, 'studious/work_detail.html', {
        'work':       work,
        'claims':     claims,
        'top_terms':  work.top_terms(30),
        'claim_kinds': CLAIM_KINDS,
    })


@login_required
def work_edit(request, slug):
    work = get_object_or_404(Work, slug=slug)
    if request.method == 'POST':
        title = (request.POST.get('title') or '').strip()
        if not title:
            messages.error(request, 'Title is required.')
        else:
            year_raw = (request.POST.get('year') or '').strip()
            work.title = title[:400]
            work.year = int(year_raw) if year_raw.isdigit() else None
            work.kind = request.POST.get('kind') or work.kind
            work.doi = (request.POST.get('doi') or '')[:160]
            work.url = (request.POST.get('url') or '')[:500]
            work.abstract = request.POST.get('abstract') or ''
            full_text = request.POST.get('full_text') or ''
            if full_text.strip() != (work.full_text or '').strip():
                work.full_text = full_text
            work.notes = request.POST.get('notes') or ''
            work.save()
            work.domains.clear()
            for d_slug in request.POST.getlist('domains'):
                d = Domain.objects.filter(slug=d_slug).first()
                if d:
                    work.domains.add(d)
            messages.success(request, 'Saved.')
            return redirect('studious:work_detail', slug=work.slug)
    return render(request, 'studious/work_form.html', {
        'work':       work,
        'scholar':    work.scholar,
        'scholars':   Scholar.objects.all(),
        'work_kinds': WORK_KINDS,
        'domains':    Domain.objects.all(),
    })


@login_required
@require_POST
def work_delete(request, slug):
    work = get_object_or_404(Work, slug=slug)
    scholar_slug = work.scholar.slug
    title = work.title
    work.delete()
    messages.success(request, f'Deleted "{title}".')
    return redirect('studious:scholar_detail', slug=scholar_slug)


@login_required
@require_POST
def work_analyze(request, slug):
    work = get_object_or_404(Work, slug=slug)
    try:
        analysis.analyze_work(work)
        messages.success(request, 'Re-scored top terms.')
    except Exception as e:
        messages.warning(request, f'Analysis failed: {e}')
    return redirect('studious:work_detail', slug=work.slug)


@login_required
@require_POST
def work_extract_claims(request, slug):
    """Run the heuristic claim picker. Skips duplicates already on the Work."""
    work = get_object_or_404(Work, slug=slug)
    text = work.full_text or work.abstract or ''
    if not text.strip():
        messages.warning(request, 'No text to extract from — ingest first.')
        return redirect('studious:work_detail', slug=work.slug)
    existing = {c.text.strip()[:120] for c in work.claims.all()}
    candidates = analysis.extract_candidate_claims(text, max_candidates=40)
    made = 0
    next_order = (work.claims.order_by('-order').values_list('order', flat=True)
                  .first() or 0)
    for sent, kind, score in candidates:
        key = sent.strip()[:120]
        if key in existing:
            continue
        existing.add(key)
        next_order += 1
        Claim.objects.create(
            work=work,
            text=sent,
            kind=kind if kind in dict(CLAIM_KINDS) else 'claim',
            auto_extracted=True,
            score=score,
            order=next_order,
        )
        made += 1
    messages.success(request, f'Proposed {made} candidate claim(s).')
    return redirect('studious:work_detail', slug=work.slug)


# ── Claims ─────────────────────────────────────────────────────────

@login_required
def claim_list(request):
    scholar_slug = request.GET.get('scholar') or ''
    domain_slug = request.GET.get('domain') or ''
    q = (request.GET.get('q') or '').strip()
    qs = Claim.objects.select_related('work__scholar').order_by(
        'work__scholar__name', 'work__title', 'order')
    if scholar_slug:
        qs = qs.filter(work__scholar__slug=scholar_slug)
    if domain_slug:
        qs = qs.filter(work__domains__slug=domain_slug).distinct()
    if q:
        qs = qs.filter(text__icontains=q)
    return render(request, 'studious/claim_list.html', {
        'claims':   qs[:400],
        'total':    qs.count(),
        'scholars': Scholar.objects.all(),
        'domains':  Domain.objects.all(),
        'q':        q,
        'scholar_slug': scholar_slug,
        'domain_slug':  domain_slug,
    })


@login_required
def claim_add(request, slug):
    """Add a hand-written claim to a Work."""
    work = get_object_or_404(Work, slug=slug)
    if request.method == 'POST':
        text = (request.POST.get('text') or '').strip()
        if not text:
            messages.error(request, 'Claim text is required.')
        else:
            next_order = (work.claims.order_by('-order')
                          .values_list('order', flat=True).first() or 0)
            Claim.objects.create(
                work=work,
                text=text,
                kind=request.POST.get('kind') or 'claim',
                page_ref=(request.POST.get('page_ref') or '')[:40],
                notes=request.POST.get('notes') or '',
                order=next_order + 1,
            )
            messages.success(request, 'Added claim.')
            return redirect('studious:work_detail', slug=work.slug)
    return render(request, 'studious/claim_form.html', {
        'claim':       None,
        'work':        work,
        'claim_kinds': CLAIM_KINDS,
    })


@login_required
def claim_edit(request, pk):
    claim = get_object_or_404(Claim, pk=pk)
    if request.method == 'POST':
        text = (request.POST.get('text') or '').strip()
        if not text:
            messages.error(request, 'Claim text is required.')
        else:
            claim.text = text
            claim.kind = request.POST.get('kind') or claim.kind
            claim.page_ref = (request.POST.get('page_ref') or '')[:40]
            claim.notes = request.POST.get('notes') or ''
            claim.auto_extracted = False
            claim.save()
            messages.success(request, 'Saved.')
            return redirect('studious:work_detail', slug=claim.work.slug)
    return render(request, 'studious/claim_form.html', {
        'claim':       claim,
        'work':        claim.work,
        'claim_kinds': CLAIM_KINDS,
    })


@login_required
@require_POST
def claim_delete(request, pk):
    claim = get_object_or_404(Claim, pk=pk)
    work_slug = claim.work.slug
    claim.delete()
    messages.success(request, 'Deleted claim.')
    return redirect('studious:work_detail', slug=work_slug)


# ── Arguments ──────────────────────────────────────────────────────

@login_required
def argument_list(request):
    args = Argument.objects.filter(user=request.user)
    return render(request, 'studious/argument_list.html', {
        'arguments':     args,
        'argument_kinds': ARGUMENT_KINDS,
    })


@login_required
def argument_new(request):
    """Create an argument from a set of selected Claim pks.

    GET: render the claim picker. POST: create the Argument, pin chosen
    claims with order-preserving ArgumentClaim rows, and scaffold the
    premise + tension blocks.
    """
    if request.method == 'POST':
        title = (request.POST.get('title') or '').strip()
        if not title:
            messages.error(request, 'Title is required.')
            return redirect('studious:argument_new')
        kind = request.POST.get('kind') or 'across'
        domain_slug = request.POST.get('domain') or ''
        domain = Domain.objects.filter(slug=domain_slug).first() if domain_slug else None

        claim_pks = [int(pk) for pk in request.POST.getlist('claims')
                     if pk.isdigit()]
        claims = list(Claim.objects.select_related('work__scholar')
                      .filter(pk__in=claim_pks))
        claims.sort(key=lambda c: claim_pks.index(c.pk))

        premises, tension = analysis.build_argument_scaffold(claims)

        arg = Argument.objects.create(
            user=request.user,
            title=title[:200],
            kind=kind,
            domain=domain,
            premises_text=premises,
            tension_text=tension,
            synthesis_text='',
        )
        for i, c in enumerate(claims):
            ArgumentClaim.objects.create(
                argument=arg, claim=c, role='premise', order=i + 1)

        messages.success(request, f'Scaffolded "{arg.title}".')
        return redirect('studious:argument_detail', slug=arg.slug)

    scholar_slug = request.GET.get('scholar') or ''
    qs = Claim.objects.select_related('work__scholar').order_by(
        'work__scholar__name', 'work__title', 'order')
    if scholar_slug:
        qs = qs.filter(work__scholar__slug=scholar_slug)
    return render(request, 'studious/argument_form.html', {
        'argument':       None,
        'argument_kinds': ARGUMENT_KINDS,
        'scholars':       Scholar.objects.all(),
        'domains':        Domain.objects.all(),
        'claims':         qs[:400],
        'scholar_slug':   scholar_slug,
    })


@login_required
def argument_detail(request, slug):
    arg = get_object_or_404(Argument.objects.filter(user=request.user), slug=slug)
    items = (arg.items.select_related('claim__work__scholar')
             .order_by('order'))
    return render(request, 'studious/argument_detail.html', {
        'argument': arg,
        'items':    items,
    })


@login_required
def argument_edit(request, slug):
    arg = get_object_or_404(Argument.objects.filter(user=request.user), slug=slug)
    if request.method == 'POST':
        title = (request.POST.get('title') or '').strip()
        if not title:
            messages.error(request, 'Title is required.')
        else:
            arg.title = title[:200]
            arg.kind = request.POST.get('kind') or arg.kind
            domain_slug = request.POST.get('domain') or ''
            arg.domain = (Domain.objects.filter(slug=domain_slug).first()
                          if domain_slug else None)
            arg.premises_text  = request.POST.get('premises_text') or ''
            arg.tension_text   = request.POST.get('tension_text') or ''
            arg.synthesis_text = request.POST.get('synthesis_text') or ''
            arg.save()
            messages.success(request, 'Saved.')
            return redirect('studious:argument_detail', slug=arg.slug)
    items = arg.items.select_related('claim__work__scholar').order_by('order')
    return render(request, 'studious/argument_form.html', {
        'argument':       arg,
        'items':          items,
        'argument_kinds': ARGUMENT_KINDS,
        'argument_roles': ARGUMENT_ROLES,
        'domains':        Domain.objects.all(),
    })


@login_required
@require_POST
def argument_delete(request, slug):
    arg = get_object_or_404(Argument.objects.filter(user=request.user), slug=slug)
    arg.delete()
    messages.success(request, 'Argument deleted.')
    return redirect('studious:argument_list')


# ── Domains ────────────────────────────────────────────────────────

@login_required
@require_POST
def domain_add(request):
    name = (request.POST.get('name') or '').strip()
    if not name:
        messages.error(request, 'Name is required.')
    else:
        Domain.objects.get_or_create(
            name=name[:120],
            defaults={'description': request.POST.get('description') or ''},
        )
        messages.success(request, f'Added domain "{name}".')
    back = request.POST.get('back') or ''
    if back:
        return redirect(back)
    return redirect('studious:index')


@login_required
@require_POST
def domain_delete(request, slug):
    d = get_object_or_404(Domain, slug=slug)
    name = d.name
    d.delete()
    messages.success(request, f'Deleted domain "{name}".')
    return redirect('studious:index')
