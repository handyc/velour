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

    path('tournaments/',              views.tournament_index,  name='tournament_index'),
    path('tournaments/new/',          views.tournament_create, name='tournament_create'),
    path('tournaments/<slug:slug>/',  views.tournament_detail, name='tournament_detail'),
    path('tournaments/<slug:slug>/run/', views.tournament_run, name='tournament_run'),
    path('tournaments/<slug:slug>/delete/', views.tournament_delete, name='tournament_delete'),

    path('meta/',                     views.meta_index,  name='meta_index'),
    path('meta/new/',                 views.meta_create, name='meta_create'),
    path('meta/<slug:slug>/',         views.meta_detail, name='meta_detail'),
    path('meta/<slug:slug>/run/',     views.meta_run,    name='meta_run'),
    path('meta/<slug:slug>/delete/',  views.meta_delete, name='meta_delete'),
]
