from django.contrib.auth.decorators import login_required
from django.shortcuts import render

from .forecast import forecast_table, purchase_recommendation
from .models import HORIZON_YEARS, Server, WorkloadClass, HostedProject


@login_required
def home(request):
    """The Prime Radiant itself — fleet + forecast table + purchase rec."""
    servers = Server.objects.all()
    classes = list(WorkloadClass.objects.all())
    projects = HostedProject.objects.select_related('server', 'workload_class')

    split_wp = request.GET.get('split', '1') != '0'

    rows = forecast_table(classes)
    rec = purchase_recommendation(rows, split_wordpress=split_wp)

    speculative_notes = {
        200:   'Beyond hardware replacement cycles; 50+ generations of '
               'storage media change. Numbers are curve extrapolation only.',
        500:   'Past the operational lifetime of most universities in '
               'continuous existence. Leiden University (founded 1575) is '
               'a rare example — here 951 years old.',
        1000:  'Past recorded history in any computing sense. Project counts '
               'are fictional; the saturation ceiling has dominated.',
        5000:  'Comparable to the entire span of written human history. '
               'Numbers are symbolic; treat as a reminder that predictions '
               'must degrade gracefully.',
        10000: 'Beyond any reasonable claim. Retained only because Seldon '
               'set his equations at this scale. Output is ceremonial.',
    }
    for row in rows:
        row['narrative'] = speculative_notes.get(row['years'], '')

    return render(request, 'radiant/home.html', {
        'servers':        servers,
        'classes':        classes,
        'projects':       projects,
        'forecast_rows':  rows,
        'recommendation': rec,
        'split_wp':       split_wp,
        'horizons':       HORIZON_YEARS,
    })
