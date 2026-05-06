from django.urls import path
from . import views

app_name = 'automaton'

urlpatterns = [
    path('',                       views.home,              name='home'),
    path('import-from-s3lab/',     views.import_from_s3lab, name='import_from_s3lab'),
    path('create/',                views.create_simulation, name='create'),
    path('create-life-rules/',     views.create_life_rules, name='create_life_rules'),
    path('create-exact-rules/',    views.create_exact_rules, name='create_exact_rules'),
    path('merge/',                 views.merge_rulesets,    name='merge_rulesets'),
    path('merge-random/',          views.merge_random_rulesets, name='merge_random_rulesets'),
    path('ruleset/<int:pk>/rename/', views.rename_ruleset,  name='rename_ruleset'),
    path('ruleset/<int:pk>/run/',    views.run_ruleset,      name='run_ruleset'),
    path('<slug:slug>/',           views.run_simulation,    name='run'),
    path('<slug:slug>/data.json',  views.simulation_data_json, name='data_json'),
    path('<slug:slug>/export.json', views.export_simulation_json, name='export_json'),
    path('<slug:slug>/genome.bin', views.export_genome_bin, name='export_genome_bin'),
    path('<slug:slug>/rename/',    views.rename_simulation, name='rename'),
    path('<slug:slug>/resize/',    views.resize_simulation, name='resize'),
    path('<slug:slug>/palette/',   views.update_palette,    name='update_palette'),
    path('<slug:slug>/load-image/', views.load_image,       name='load_image'),
]
