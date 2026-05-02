from django.urls import path

from . import views

app_name = 'taxon'

urlpatterns = [
    path('', views.index, name='index'),
    path('library/', views.library, name='library'),
    path('classes/<int:n>/', views.class_view, name='class'),
    path('metrics/', views.metrics_view, name='metrics'),
    path('import/', views.import_view, name='import'),
    path('evolve/', views.evolve_view, name='evolve'),
    path('evolve/save/', views.evolve_save, name='evolve_save'),
    path('rules/<slug:slug>/', views.rule_detail, name='rule_detail'),
    path('rules/<slug:slug>/edit/', views.rule_edit, name='rule_edit'),
    path('rules/<slug:slug>/genome.bin', views.rule_download, name='rule_download'),
    path('rules/<slug:slug>/classify/', views.rule_classify, name='rule_classify'),
    path('rules/<slug:slug>/delete/', views.rule_delete, name='rule_delete'),
    path('rules/<slug:slug>/reroll-palette/', views.rule_reroll_palette, name='rule_reroll_palette'),

    # Agents — same Ruleset, different palette / identity.
    path('agents/<slug:slug>/make-default/', views.agent_make_default, name='agent_make_default'),
    path('agents/<slug:slug>/delete/',       views.agent_delete,       name='agent_delete'),
    path('rules/<slug:slug>/to-automaton/', views.rule_to_automaton, name='rule_to_automaton'),
    path('rules/<slug:slug>/to-s3lab/', views.rule_to_s3lab, name='rule_to_s3lab'),
    path('rules/<slug:slug>/to-device/', views.rule_to_device, name='rule_to_device'),

    # AutoSearch — background hunt for a target Wolfram class.
    path('autosearch/',                      views.autosearch_view,   name='autosearch'),
    path('autosearch/start/',                views.autosearch_start,  name='autosearch_start'),
    path('autosearch/<slug:slug>/stop/',     views.autosearch_stop,   name='autosearch_stop'),
    path('autosearch/<slug:slug>/status.json', views.autosearch_status, name='autosearch_status'),
]
