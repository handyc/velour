from django.urls import path

from . import views

app_name = 'roomplanner'

urlpatterns = [
    path('', views.index, name='index'),
    path('catalog/', views.catalog, name='catalog'),
    path('building/<slug:slug>/',
         views.building_detail, name='building_detail'),

    # catalog API (not room-scoped)
    path('api/piece/add/',  views.api_piece_add,  name='api_piece_add'),
    path('api/piece/<int:piece_id>/delete/',
         views.api_piece_delete, name='api_piece_delete'),

    # room-scoped API
    path('<slug:slug>/api/placement/add/',
         views.api_placement_add, name='api_placement_add'),
    path('<slug:slug>/api/placement/<int:pk>/update/',
         views.api_placement_update, name='api_placement_update'),
    path('<slug:slug>/api/placement/<int:pk>/delete/',
         views.api_placement_delete, name='api_placement_delete'),

    path('<slug:slug>/api/feature/add/',
         views.api_feature_add, name='api_feature_add'),
    path('<slug:slug>/api/feature/<int:pk>/update/',
         views.api_feature_update, name='api_feature_update'),
    path('<slug:slug>/api/feature/<int:pk>/delete/',
         views.api_feature_delete, name='api_feature_delete'),

    path('<slug:slug>/api/room/update/',
         views.api_room_update, name='api_room_update'),
    path('<slug:slug>/api/room/locate/',
         views.api_room_locate, name='api_room_locate'),
    path('<slug:slug>/api/room/score/',
         views.api_room_score, name='api_room_score'),
    path('<slug:slug>/api/room/evolve/',
         views.api_room_evolve, name='api_room_evolve'),

    path('<slug:slug>/api/layout/',
         views.api_layout_list, name='api_layout_list'),
    path('<slug:slug>/api/layout/save/',
         views.api_layout_save, name='api_layout_save'),
    path('<slug:slug>/api/layout/<int:pk>/load/',
         views.api_layout_load, name='api_layout_load'),
    path('<slug:slug>/api/layout/<int:pk>/delete/',
         views.api_layout_delete, name='api_layout_delete'),

    # room page — keep last so the /api/ paths above don't collide
    path('<slug:slug>/', views.room_detail, name='room_detail'),
]
