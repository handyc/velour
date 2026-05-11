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
]
