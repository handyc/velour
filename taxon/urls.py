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
    path('rules/<slug:slug>/genome.bin', views.rule_download, name='rule_download'),
    path('rules/<slug:slug>/classify/', views.rule_classify, name='rule_classify'),
    path('rules/<slug:slug>/delete/', views.rule_delete, name='rule_delete'),
]
