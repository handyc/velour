from django.urls import path

from . import views

app_name = 'lsystem'

urlpatterns = [
    path('', views.species_list, name='species_list'),
    path('add/', views.species_add, name='species_add'),
    path('randomize/', views.species_randomize, name='species_randomize'),
    path('seed-defaults/', views.seed_defaults, name='seed_defaults'),
    path('import/', views.import_from_aether, name='import_from_aether'),
    path('<slug:slug>/', views.species_detail, name='species_detail'),
    path('<slug:slug>/edit/', views.species_edit, name='species_edit'),
    path('<slug:slug>/delete/', views.species_delete, name='species_delete'),
    path('<slug:slug>/duplicate/', views.species_duplicate, name='species_duplicate'),
    path('<slug:slug>/preview.json', views.species_preview_json, name='species_preview_json'),
    path('<slug:slug>/export/', views.export_to_aether, name='export_to_aether'),
]
