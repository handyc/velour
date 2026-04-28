"""Helix views — list / detail / upload / delete for the genome viewer.

Detail view ships the parsed record + a feature-track payload sized
for the SVG viewer in templates/helix/detail.html.
"""

from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.db import transaction
from django.http import HttpResponse, Http404
from django.shortcuts import get_object_or_404, redirect, render
from django.views.decorators.http import require_POST

from .forms import UploadForm
from .models import AnnotationFeature, SequenceRecord
from .parsers import parse_text


@login_required
def list_view(request):
    records = SequenceRecord.objects.all()
    return render(request, 'helix/list.html', {'records': records})


@login_required
def detail(request, pk):
    record = get_object_or_404(SequenceRecord, pk=pk)
    features = list(record.features.all())
    return render(request, 'helix/detail.html', {
        'record': record,
        'features': features,
        'feature_type_counts': record.feature_type_counts(),
    })


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
