from django.urls import path

from . import views

app_name = 'forge'

urlpatterns = [
    path('',                  views.circuit_list,    name='list'),
    path('gates/',            views.gate_list,       name='gates'),
    path('new/',              views.circuit_new,     name='new'),
    path('<slug:slug>/',      views.circuit_detail,  name='detail'),
    path('<slug:slug>/clone/', views.circuit_clone,  name='clone'),
    path('<slug:slug>/save/', views.circuit_save,    name='save'),
    path('<slug:slug>/run/',  views.circuit_run,     name='run'),
    path('<slug:slug>/score/', views.circuit_score,  name='score'),
    path('<slug:slug>/evolve/',           views.circuit_evolve,         name='evolve'),
    path('<slug:slug>/evolve/start/',     views.circuit_evolve_start,   name='evolve_start'),
    path('<slug:slug>/evolve/<int:run_id>/status.json',
         views.circuit_evolve_status,  name='evolve_status'),
    path('<slug:slug>/evolve/<int:run_id>/promote/',
         views.circuit_evolve_promote, name='evolve_promote'),
    path('<slug:slug>/delete/', views.circuit_delete, name='delete'),
]
