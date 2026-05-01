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
]
