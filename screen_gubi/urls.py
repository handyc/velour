from django.urls import path

from . import views

app_name = 'screen_gubi'

urlpatterns = [
    path('', views.index, name='index'),
    path('new/', views.new, name='new'),
    path('<slug:slug>/', views.detail, name='detail'),
    path('<slug:slug>/edit/', views.edit, name='edit'),
    path('<slug:slug>/delete/', views.delete, name='delete'),
    path('<slug:slug>/scene.json', views.scene_json, name='scene_json'),
]
