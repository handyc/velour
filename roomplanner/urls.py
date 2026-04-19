from django.urls import path

from . import views

app_name = 'roomplanner'

urlpatterns = [
    path('', views.index, name='index'),
    path('catalog/', views.catalog, name='catalog'),

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

    # room page — keep last so the /api/ paths above don't collide
    path('<slug:slug>/', views.room_detail, name='room_detail'),
]
