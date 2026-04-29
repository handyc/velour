"""Helix views — list / detail / upload / delete for the genome viewer.

Detail view ships the parsed record + a feature-track payload sized
for the SVG viewer in templates/helix/detail.html.
"""

from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.core.cache import cache
from django.db import transaction
from django.http import HttpResponse, Http404, JsonResponse, HttpResponseBadRequest
from django.shortcuts import get_object_or_404, redirect, render
from django.views.decorators.http import require_GET, require_POST

from .forms import UploadForm
from .models import AnnotationFeature, SequenceRecord
from .parsers import parse_text


# Cap on a single sequence-range fetch. The viewer never asks for more
# than ~3,000 bases (its sequence panel is hidden past that zoom), but
# we leave a little headroom for adjacent prefetch.
MAX_SEQUENCE_SLICE = 5000

# Bin count for the cached GC profile. 2000 bins gives a clean visual
# at any zoom on the longest record we ship today (32 Mb chr 3R), and
# costs ~16 KB to serialise.
GC_PROFILE_BINS = 2000


@login_required
def list_view(request):
    records = SequenceRecord.objects.all()
    return render(request, 'helix/list.html', {'records': records})


@login_required
def detail(request, pk):
    record = get_object_or_404(SequenceRecord, pk=pk)
    features = list(record.features.all())
    # Compact features payload: a dictionary of type names + an array
    # of fixed-position tuples per feature. JSON keys would otherwise
    # cost ~700 KB of repetition on a 20k-feature chromosome.
    payload = _features_payload(features)
    return render(request, 'helix/detail.html', {
        'record': record,
        'features': features,
        'features_payload': payload,
        'feature_type_counts': record.feature_type_counts(),
    })


# Qualifier keys included in the per-feature search string (kept short —
# product/note can include long English prose).
_SEARCH_QUALIFIERS = ('gene', 'product', 'locus_tag', 'protein_id')


def _features_payload(features):
    """Build the compact viewer payload.

    Schema:
        {
          "types": ["source", "gene", "CDS", ...],
          "rows":  [[id, start, end, strand, type_idx], ...]
                or [[id, start, end, strand, type_idx, name], ...]
                or [[id, start, end, strand, type_idx, name, search], ...]
        }

    `name` is omitted when it equals the type (saves ~50% of payload on
    Drosophila genomes, where most features inherit their type as name).
    `search` is omitted when name + type already subsume the qualifier
    tokens — the viewer falls back to that string.
    """
    type_index = {}
    types_out = []
    rows = []
    for f in features:
        ti = type_index.get(f.feature_type)
        if ti is None:
            ti = len(types_out)
            types_out.append(f.feature_type)
            type_index[f.feature_type] = ti

        name = f.display_name()
        q = f.qualifiers or {}
        extras = []
        for k in _SEARCH_QUALIFIERS:
            v = q.get(k)
            if isinstance(v, list):
                extras.extend(str(x) for x in v)
            elif v:
                extras.append(str(v))
        # Strip duplicates already covered by name + type.
        already = (name + ' ' + f.feature_type).lower()
        novel = [t for t in extras if t.lower() not in already]

        row = [f.pk, f.start, f.end, f.strand, ti]
        if name != f.feature_type or novel:
            row.append(name if name != f.feature_type else None)
        if novel:
            row.append(' '.join(novel).lower())
        rows.append(row)
    return {'types': types_out, 'rows': rows}


@login_required
@require_GET
def feature_qualifiers(request, feature_pk):
    """Return one feature's qualifiers as JSON. Fetched on click so we
    don't embed all of them in the detail page."""
    f = get_object_or_404(AnnotationFeature, pk=feature_pk)
    return JsonResponse({'qualifiers': f.qualifiers or {}})


# Hard cap on the slice we hand to Evolution Engine. Edit-distance
# fitness on a 24-agent population with random ACGT starts becomes
# unfindable past a few hundred bp; 5,000 bp is generous.
EVOLVE_MAX_BP = 5000
EVOLVE_MIN_BP = 10


@login_required
@require_POST
def to_evolution(request, pk):
    """Slice this record's sequence and create an EvolutionRun seeded
    with the slice. Two modes:

    - mode=toward (default): the slice becomes goal_string, the
      population starts from random ACGT and evolves toward the slice.
    - mode=from: same goal_string, but seed_string is set to the slice
      so the population starts as copies of it. Useful for measuring
      how stable the sequence is under mutation pressure (or, after
      manually editing the run's goal_string, for "evolve from A toward
      B" gene-divergence experiments).
    """
    record = get_object_or_404(SequenceRecord, pk=pk)
    try:
        start = int(request.POST.get('start', 0))
        end = int(request.POST.get('end', 0))
    except (TypeError, ValueError):
        return HttpResponseBadRequest('start/end must be integers')
    if not (0 <= start < end <= record.length_bp):
        return HttpResponseBadRequest(
            f'range out of bounds (sequence is {record.length_bp} bp)'
        )

    span = end - start
    if span > EVOLVE_MAX_BP:
        return HttpResponseBadRequest(
            f'slice too long ({span:,} bp); cap is {EVOLVE_MAX_BP:,} bp'
        )
    if span < EVOLVE_MIN_BP:
        return HttpResponseBadRequest(
            f'slice too short ({span} bp); need at least {EVOLVE_MIN_BP} bp'
        )

    mode = (request.POST.get('mode') or 'toward').strip()
    if mode not in ('toward', 'from'):
        mode = 'toward'

    slice_seq = record.sequence[start:end].upper()

    label = (request.POST.get('name') or '').strip()
    if not label:
        label = f'{record.accession or record.title} {start + 1}-{end}'
    name = f'{label} (evolve {mode})'

    # Lazy import — keeps helix decoupled from evolution at module load.
    from django.utils.crypto import get_random_string

    from evolution.models import EvolutionRun

    if EvolutionRun.objects.filter(name=name).exists():
        name = f'{name} {get_random_string(4).lower()}'

    params = {
        'gene_type': 'dna',
        'mutation_rate': 0.25,
        'helix_origin': {
            'record_pk':    record.pk,
            'record_title': record.title,
            'accession':    record.accession,
            'start':        start,
            'end':          end,
            'length':       span,
            'mode':         mode,
        },
    }
    if mode == 'from':
        # Engine reads params.seed_string into ctx for dna.random().
        params['seed_string'] = slice_seq

    run = EvolutionRun.objects.create(
        name=name,
        level=0,
        goal_string=slice_seq,
        population_size=32,
        generations_target=500,
        target_score=0.99,
        params=params,
    )
    messages.success(
        request,
        f'Created evolution run "{run.name}" — {span} bp from {record.title}.'
    )
    return redirect('evolution:run_detail', slug=run.slug)


@login_required
def upload(request):
    if request.method == 'POST':
        form = UploadForm(request.POST, request.FILES)
        if form.is_valid():
            f = form.cleaned_data.get('file')
            pasted = form.cleaned_data.get('pasted', '')
            title_override = form.cleaned_data.get('title_override', '').strip()

            if f:
                try:
                    text = f.read().decode('utf-8', errors='replace')
                except Exception as e:
                    messages.error(request, f'Could not read upload: {e}')
                    return render(request, 'helix/upload.html', {'form': form})
                source_filename = f.name
            else:
                text = pasted
                source_filename = 'pasted'

            try:
                fmt, records = parse_text(text, filename=source_filename)
            except ValueError as e:
                messages.error(request, str(e))
                return render(request, 'helix/upload.html', {'form': form})
            except Exception as e:
                messages.error(request, f'Parse failed: {type(e).__name__}: {e}')
                return render(request, 'helix/upload.html', {'form': form})

            if not records:
                messages.warning(request, 'No records found in the input.')
                return render(request, 'helix/upload.html', {'form': form})

            saved = _persist_records(records, request.user, title_override)
            messages.success(
                request,
                f'Imported {len(saved)} record(s) ({fmt}). '
                f'Total features: {sum(len(r.features.all()) for r in saved)}.'
            )
            if len(saved) == 1:
                return redirect('helix:detail', pk=saved[0].pk)
            return redirect('helix:list')
    else:
        form = UploadForm()
    return render(request, 'helix/upload.html', {'form': form})


def _persist_records(record_dicts, user, title_override):
    """Insert the parsed records + their features in one transaction so
    a half-saved upload can never poison the list."""
    saved = []
    with transaction.atomic():
        for i, rd in enumerate(record_dicts):
            features = rd.pop('features', [])
            if title_override and i == 0:
                rd['title'] = title_override
            rec = SequenceRecord.objects.create(created_by=user, **rd)
            AnnotationFeature.objects.bulk_create([
                AnnotationFeature(record=rec, **f) for f in features
            ])
            saved.append(rec)
    return saved


@login_required
@require_POST
def delete(request, pk):
    record = get_object_or_404(SequenceRecord, pk=pk)
    title = record.title
    record.delete()
    messages.success(request, f'Deleted "{title}".')
    return redirect('helix:list')


@login_required
@require_GET
def sequence_range(request, pk):
    """Return a slice of the record's sequence as JSON.

    The detail page no longer embeds the full sequence — multi-megabase
    chromosomes would bloat the HTML for no gain (the sequence panel
    only renders ≤ 3,000 bp at a time). The viewer fetches just the
    visible window from here.
    """
    try:
        start = int(request.GET.get('start', 0))
        end   = int(request.GET.get('end', 0))
    except ValueError:
        return HttpResponseBadRequest('start and end must be integers')
    if end <= start:
        return HttpResponseBadRequest('end must be greater than start')
    if end - start > MAX_SEQUENCE_SLICE:
        return HttpResponseBadRequest(f'slice exceeds {MAX_SEQUENCE_SLICE} bp cap')

    record = get_object_or_404(SequenceRecord, pk=pk)
    a = max(0, start)
    b = min(record.length_bp, end)
    return JsonResponse({
        'start': a,
        'end': b,
        'sequence': record.sequence[a:b],
    })


@login_required
@require_GET
def gc_profile(request, pk):
    """Return a binned GC% profile for the record's sequence.

    Computing GC across a 32 Mb chromosome in JS would mean shipping
    32 MB of bases over the wire, then iterating them in the browser.
    Instead, we precompute a coarse binned profile server-side once,
    cache it (`helix.gc.<pk>.<bins>` key), and ship ~16 KB of floats.
    The viewer can resample this profile at any zoom.
    """
    try:
        bins = int(request.GET.get('bins', GC_PROFILE_BINS))
    except ValueError:
        return HttpResponseBadRequest('bins must be an integer')
    bins = max(50, min(4000, bins))

    record = get_object_or_404(SequenceRecord, pk=pk)
    profile = _get_gc_profile(record, bins)
    return JsonResponse({
        'bins': bins,
        'length': record.length_bp,
        # Round to 4 sig figs so the payload stays compact.
        'profile': [round(v, 4) for v in profile],
    })


def _get_gc_profile(record, bins):
    cache_key = f'helix.gc.{record.pk}.{bins}'
    hit = cache.get(cache_key)
    if hit is not None:
        return hit
    profile = _compute_gc_profile(record.sequence, bins)
    # 30 days — sequence and bin count are both stable; only invalidate
    # if the record itself is rewritten (deleted on save in models.py).
    cache.set(cache_key, profile, 60 * 60 * 24 * 30)
    return profile


def _compute_gc_profile(sequence, bins):
    """Return `bins` floats in [0, 1] giving GC% per equal-width bin.

    Uses str.count() per bin so the actual scanning happens in C —
    a 32 Mb chromosome takes ~0.2s instead of ~3s for the per-char
    Python loop. Equal-width bins; the last bin absorbs any rounding
    remainder.
    """
    n = len(sequence)
    if n == 0 or bins <= 0:
        return [0.0] * max(0, bins)
    out = [0.0] * bins
    bin_size = n / bins
    for i in range(bins):
        a = int(i * bin_size)
        b = n if i == bins - 1 else int((i + 1) * bin_size)
        if b <= a:
            continue
        chunk = sequence[a:b]
        gc = (chunk.count('G') + chunk.count('C')
              + chunk.count('g') + chunk.count('c'))
        out[i] = gc / (b - a)
    return out


@login_required
def download_fasta(request, pk):
    """Re-emit the record as FASTA. Useful for round-tripping a GenBank
    upload back out as plain sequence."""
    record = get_object_or_404(SequenceRecord, pk=pk)
    header = f'>{record.accession or record.title.replace(" ", "_")}'
    if record.organism:
        header += f' [{record.organism}]'
    # 60 bases per line — the FASTA convention.
    body = '\n'.join(
        record.sequence[i:i + 60] for i in range(0, len(record.sequence), 60)
    )
    payload = f'{header}\n{body}\n'
    resp = HttpResponse(payload, content_type='text/plain; charset=utf-8')
    safe_name = (record.accession or record.title or f'record_{record.pk}')
    safe_name = ''.join(c if c.isalnum() else '_' for c in safe_name)[:80]
    resp['Content-Disposition'] = f'attachment; filename="{safe_name}.fasta"'
    return resp
