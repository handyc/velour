from django.urls import path

from . import views

app_name = 'zoetrope'

urlpatterns = [
    path('', views.reel_list, name='list'),
    path('new/', views.reel_create, name='create'),
    path('quick-random/', views.reel_quick_random, name='quick_random'),
    path('auto-edit/', views.reel_auto_edit, name='auto_edit'),
    path('aether-random/', views.reel_aether_random, name='aether_random'),
    path('splice-random/', views.reel_splice_random, name='splice_random'),
    path('tournaments/', views.tournament_list, name='tournaments'),
    path('tournaments/run/', views.tournament_create, name='tournament_run'),
    path('<slug:slug>/', views.reel_detail, name='detail'),
    path('<slug:slug>/frames/', views.reel_frames, name='frames'),
    path('<slug:slug>/render/', views.reel_render, name='render'),
    path('<slug:slug>/share/', views.reel_share, name='share'),
    path('<slug:slug>/delete/', views.reel_delete, name='delete'),
]
