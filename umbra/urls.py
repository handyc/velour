from django.urls import path

from . import views


app_name = 'umbra'

urlpatterns = [
    path('',                       views.index,            name='index'),
    path('schemes/',               views.scheme_list,      name='schemes'),
    path('schemes/<slug:slug>/',   views.scheme_detail,    name='scheme_detail'),
    path('references/',            views.reference_list,   name='references'),
    path('experiments/',           views.experiment_list,  name='experiments'),
    path('experiments/new/',       views.experiment_create, name='experiment_create'),
    path('experiments/<slug:slug>/',
         views.experiment_detail,  name='experiment_detail'),
    path('experiments/<slug:slug>/edit/',
         views.experiment_edit,    name='experiment_edit'),
    path('experiments/<slug:slug>/run/',
         views.experiment_run,     name='experiment_run'),

    path('sealedlex/',                       views.sealedlex_index,     name='sealedlex'),
    path('sealedlex/upload/',                views.sealedlex_upload,    name='sealedlex_upload'),
    path('sealedlex/<slug:slug>/',           views.sealedlex_session,   name='sealedlex_session'),
    path('sealedlex/<slug:slug>/add-op/',    views.sealedlex_add_op,    name='sealedlex_add_op'),
    path('sealedlex/<slug:slug>/clear-ops/', views.sealedlex_clear_ops, name='sealedlex_clear_ops'),
    path('sealedlex/<slug:slug>/run/',       views.sealedlex_run,       name='sealedlex_run'),
    path('sealedlex/<slug:slug>/download/',  views.sealedlex_download,  name='sealedlex_download'),
]
