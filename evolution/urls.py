from django.urls import path

from . import views

app_name = 'evolution'

urlpatterns = [
    path('', views.run_list, name='list'),
    path('new/', views.run_new, name='new'),
    path('speciate/', views.speciate, name='speciate'),
    path('populate-languages/', views.populate_languages,
         name='populate_languages'),
    path('tournament/', views.language_tournament,
         name='language_tournament'),
    path('championship/', views.language_championship,
         name='language_championship'),
    path('agents/', views.agent_list, name='agents'),
    path('agents/save/', views.agent_save, name='agent_save'),
    path('agents/<slug:slug>/', views.agent_detail, name='agent_detail'),
    path('agents/<slug:slug>/delete/', views.agent_delete, name='agent_delete'),
    path('agents/<slug:slug>/export-lsystem/',
         views.agent_export_lsystem, name='agent_export_lsystem'),
    path('agents/<slug:slug>/export-grammar/',
         views.agent_export_grammar, name='agent_export_grammar'),
    path('agents/<slug:slug>/spec.json', views.agent_json, name='agent_json'),
    path('runs/<slug:slug>/', views.run_detail, name='run_detail'),
    path('runs/<slug:slug>/update/', views.run_update, name='run_update'),
    path('runs/<slug:slug>/delete/', views.run_delete, name='run_delete'),
]
