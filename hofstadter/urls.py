from django.urls import path

from . import views


app_name = 'hofstadter'

urlpatterns = [
    path('',                           views.home,              name='home'),
    path('experiments/',               views.experiment_list,   name='experiment_list'),
    path('experiments/<slug:slug>/',   views.experiment_detail, name='experiment_detail'),
    path('experiments/<slug:slug>/run/', views.experiment_run,  name='experiment_run'),
    path('loops/<slug:slug>/',         views.loop_detail,       name='loop_detail'),
    path('loops/<slug:slug>/traverse/', views.loop_traverse,    name='loop_traverse'),
]
