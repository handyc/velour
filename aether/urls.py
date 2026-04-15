from django.urls import path

from . import views

app_name = 'aether'

urlpatterns = [
    path('', views.world_list, name='world_list'),
    path('add/', views.world_add, name='world_add'),
    path('generate-random/', views.generate_random_world, name='generate_random'),
    path('generate-legoworld/', views.legoworld_generate, name='generate_legoworld'),
    path('generate-megalegoworld/', views.megalegoworld_generate, name='generate_megalegoworld'),
    path('merge/', views.world_merge, name='world_merge'),
    path('boogaloo/', views.boogaloo, name='boogaloo'),
    path('library/', views.library_list, name='library_list'),
    path('library/json/', views.library_json, name='library_json'),
    path('faces/', views.face_forge, name='face_forge'),
    path('faces/save/', views.face_save, name='face_save'),
    path('faces/library/', views.face_library, name='face_library'),
    path('faces/library.json', views.face_library_json, name='face_library_json'),
    path('faces/<slug:slug>/delete/', views.face_delete, name='face_delete'),
    path('faces/<slug:slug>/favorite/', views.face_favorite, name='face_favorite'),
    path('presets/<slug:slug>.json', views.preset_json, name='preset_json'),
    path('scripts/', views.script_list, name='script_list'),
    path('scripts/add/', views.script_add, name='script_add'),
    path('scripts/<slug:slug>/edit/', views.script_edit, name='script_edit'),
    path('<slug:slug>/', views.world_detail, name='world_detail'),
    path('<slug:slug>/edit/', views.world_edit, name='world_edit'),
    path('<slug:slug>/delete/', views.world_delete, name='world_delete'),
    path('<slug:slug>/reduce/', views.world_reduce, name='world_reduce'),
    path('<slug:slug>/mutate/', views.world_mutate, name='world_mutate'),
    path('<slug:slug>/enter/', views.world_enter, name='world_enter'),
    path('<slug:slug>/scene.json', views.world_scene_json, name='world_scene_json'),
    path('<slug:slug>/entities/add/', views.entity_add, name='entity_add'),
    path('<slug:slug>/entities/<int:entity_pk>/scripts/add/',
         views.entity_script_add, name='entity_script_add'),
    path('<slug:slug>/assets/add/', views.asset_add, name='asset_add'),
    path('<slug:slug>/library/place/', views.library_place, name='library_place'),
]
