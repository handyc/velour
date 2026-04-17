from django.conf import settings
from django.http import FileResponse, Http404
from django.shortcuts import get_object_or_404, render

from .models import Experiment


def index(request):
    experiments = list(Experiment.objects.all())
    return render(request, 'casting/index.html', {'experiments': experiments})


def detail(request, slug):
    experiment = get_object_or_404(Experiment, slug=slug)
    return render(request, 'casting/detail.html', {'experiment': experiment})


def source(request, slug):
    """Serve the C source as a download (Content-Disposition: attachment)."""
    experiment = get_object_or_404(Experiment, slug=slug)
    path = settings.BASE_DIR / 'static' / 'casting' / 'sources' / experiment.c_source_filename
    if not path.exists():
        raise Http404('source file not found')
    return FileResponse(
        open(path, 'rb'),
        as_attachment=True,
        filename=experiment.c_source_filename,
        content_type='text/x-c',
    )
