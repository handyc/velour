from django.urls import path
from . import views

app_name = 'automaton'

urlpatterns = [
    path('',                       views.home,              name='home'),
    path('create/',                views.create_simulation, name='create'),
    path('create-life-rules/',     views.create_life_rules, name='create_life_rules'),
    path('create-exact-rules/',    views.create_exact_rules, name='create_exact_rules'),
    path('<slug:slug>/',           views.run_simulation,    name='run'),
    path('<slug:slug>/data.json',  views.simulation_data_json, name='data_json'),
    path('<slug:slug>/export.json', views.export_simulation_json, name='export_json'),
    path('<slug:slug>/rename/',    views.rename_simulation, name='rename'),
]
