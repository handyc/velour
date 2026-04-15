from django.urls import path

from . import views

app_name = 'zoetrope'

urlpatterns = [
    path('', views.reel_list, name='list'),
    path('new/', views.reel_create, name='create'),
    path('quick-random/', views.reel_quick_random, name='quick_random'),
    path('<slug:slug>/', views.reel_detail, name='detail'),
    path('<slug:slug>/render/', views.reel_render, name='render'),
    path('<slug:slug>/share/', views.reel_share, name='share'),
    path('<slug:slug>/delete/', views.reel_delete, name='delete'),
]
