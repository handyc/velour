from django.urls import path

from . import views

app_name = 'hexhunt'

urlpatterns = [
    path('',                       views.list_view,    name='list'),
    path('runs/launch/',           views.launch_run,   name='launch_run'),
    path('runs/<slug:slug>/',      views.run_detail,   name='run_detail'),
    path('runs/<slug:slug>/progress.json',
                                   views.run_progress_json, name='run_progress_json'),
    path('rules/<slug:slug>/',     views.rule_detail,  name='rule_detail'),
    path('rules/<slug:slug>/replay/',
                                   views.rule_replay,  name='rule_replay'),
    path('rules/<slug:slug>/scan/',
                                   views.launch_scan,  name='launch_scan'),
    path('scans/<slug:slug>/',     views.scan_detail,  name='scan_detail'),
    path('scans/<slug:slug>/track.json',
                                   views.scan_track_json, name='scan_track_json'),
    path('scans/<slug:slug>/progress.json',
                                   views.scan_progress_json, name='scan_progress_json'),

    # ── Standalone hexhunter library + multi-language ports ──
    path('lib/',                   views.lib_index,        name='lib_index'),
    path('lib/algorithm/',         views.lib_algorithm,    name='lib_algorithm'),
    path('lib/run/',               views.lib_run,          name='lib_run'),
    path('lib/refine/',            views.lib_refine,       name='lib_refine'),
    path('lib/assemble/',          views.lib_assemble,     name='lib_assemble'),
    path('lib/ports/',             views.lib_ports,        name='lib_ports'),
    path('lib/ports/<slug:slug>/', views.lib_port_detail,  name='lib_port_detail'),
    path('lib/ports/<slug:slug>/download/',
                                   views.lib_port_download, name='lib_port_download'),
    path('lib/hexhunter.js',       views.lib_js_port,      name='lib_js_port'),
]
