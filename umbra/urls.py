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

    path('csvlab/',                       views.csvlab_index,     name='csvlab'),
    path('csvlab/upload/',                views.csvlab_upload,    name='csvlab_upload'),
    path('csvlab/<slug:slug>/',           views.csvlab_session,   name='csvlab_session'),
    path('csvlab/<slug:slug>/add-op/',    views.csvlab_add_op,    name='csvlab_add_op'),
    path('csvlab/<slug:slug>/clear-ops/', views.csvlab_clear_ops, name='csvlab_clear_ops'),
    path('csvlab/<slug:slug>/run/',       views.csvlab_run,       name='csvlab_run'),
    path('csvlab/<slug:slug>/download/',  views.csvlab_download,  name='csvlab_download'),

    path('corpuslab/',                       views.corpuslab_index,     name='corpuslab'),
    path('corpuslab/upload/',                views.corpuslab_upload,    name='corpuslab_upload'),
    path('corpuslab/<slug:slug>/',           views.corpuslab_session,   name='corpuslab_session'),
    path('corpuslab/<slug:slug>/add-op/',    views.corpuslab_add_op,    name='corpuslab_add_op'),
    path('corpuslab/<slug:slug>/clear-ops/', views.corpuslab_clear_ops, name='corpuslab_clear_ops'),
    path('corpuslab/<slug:slug>/run/',       views.corpuslab_run,       name='corpuslab_run'),
    path('corpuslab/<slug:slug>/download/',  views.corpuslab_download,  name='corpuslab_download'),
]
