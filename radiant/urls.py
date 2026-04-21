from django.urls import path
from . import views

app_name = 'radiant'

urlpatterns = [
    path('',                          views.home,            name='index'),
    path('scenarios/',                views.scenarios,       name='scenarios'),
    path('snapshots/',                views.snapshots,       name='snapshots'),
    path('snapshots/take/',           views.take_snapshot,   name='take_snapshot'),
    path('snapshots/<slug:slug>/',    views.snapshot_detail, name='snapshot_detail'),
]
