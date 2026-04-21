from django.urls import path
from . import views

app_name = 'radiant'

urlpatterns = [
    path('',                          views.home,            name='index'),
    path('scenarios/',                views.scenarios,       name='scenarios'),
    path('snapshots/',                views.snapshots,       name='snapshots'),
    path('snapshots/take/',           views.take_snapshot,   name='take_snapshot'),
    path('snapshots/<slug:slug>/',    views.snapshot_detail, name='snapshot_detail'),

    path('evolve/',                   views.evolve_index,    name='evolve_index'),
    path('evolve/new/',               views.evolve_create,   name='evolve_create'),
    path('evolve/<slug:slug>/',       views.evolve_detail,   name='evolve_detail'),
    path('evolve/<slug:slug>/step/',  views.evolve_step,     name='evolve_step'),
    path('evolve/<slug:slug>/run/',   views.evolve_run,      name='evolve_run'),
    path('evolve/<slug:slug>/reseed/', views.evolve_reseed,  name='evolve_reseed'),
    path('evolve/<slug:slug>/delete/', views.evolve_delete,  name='evolve_delete'),
]
